"""Evidence collection and deterministic portfolio checks."""

from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone
from typing import Any

from .client import GitHubClient
from .models import AuditReport, CheckResult, RepositoryResult

MAINTENANCE_FILES = {
    "readme": ["README.md", "README.rst", "README.txt", "README"],
    "contributing": ["CONTRIBUTING.md", ".github/CONTRIBUTING.md"],
    "security": ["SECURITY.md", ".github/SECURITY.md"],
}
TEST_PATHS = ["tests", "test", "spec", "__tests__"]
WORKFLOW_PATH = ".github/workflows"
PROFILE_WEIGHTS = {
    "profile_name": 10,
    "profile_bio": 25,
    "profile_url": 15,
    "profile_location": 5,
    "profile_socials": 15,
    "profile_readme": 30,
}
REPOSITORY_WEIGHTS = {
    "description": 15,
    "topics": 10,
    "readme": 20,
    "license": 15,
    "ci": 20,
    "tests": 10,
    "contributing": 5,
    "security": 5,
}


def audit_portfolio(
    client: GitHubClient,
    owner: str,
    *,
    repository_names: list[str] | None = None,
    max_repositories: int = 20,
) -> AuditReport:
    """Audit one GitHub profile and its active, original public repositories."""
    owner = owner.strip()
    if not owner:
        raise ValueError("owner must not be empty")
    if max_repositories < 1 or max_repositories > 100:
        raise ValueError("max_repositories must be between 1 and 100")

    user = client.get_json(f"users/{owner}")
    if not isinstance(user, dict):
        raise ValueError("GitHub user response must be an object")
    canonical_owner = str(user.get("login") or owner)

    social_accounts = client.get_json(
        f"users/{canonical_owner}/social_accounts", allow_not_found=True
    )
    profile_repo = client.get_json(
        f"repos/{canonical_owner}/{canonical_owner}", allow_not_found=True
    )
    has_profile_readme = False
    if isinstance(profile_repo, dict):
        has_profile_readme = _first_existing_path(
            client,
            canonical_owner,
            canonical_owner,
            MAINTENANCE_FILES["readme"],
        ) is not None
    profile_checks = _profile_checks(user, social_accounts, has_profile_readme)

    if repository_names:
        raw_repositories = [
            client.get_json(f"repos/{canonical_owner}/{name}")
            for name in repository_names
        ]
    else:
        raw_repositories = client.get_all(
            f"users/{canonical_owner}/repos",
            params={"type": "owner", "sort": "pushed", "direction": "desc"},
        )

    repositories = []
    for raw_repo in raw_repositories:
        if not isinstance(raw_repo, dict):
            continue
        if raw_repo.get("fork") or raw_repo.get("archived"):
            continue
        if raw_repo.get("private"):
            continue
        if raw_repo.get("name", "").casefold() == canonical_owner.casefold():
            continue
        repositories.append(_audit_repository(client, canonical_owner, raw_repo))
        if len(repositories) >= max_repositories:
            break

    return AuditReport(
        owner=canonical_owner,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        profile_url=f"https://github.com/{canonical_owner}",
        profile_checks=profile_checks,
        repositories=repositories,
    )


def _profile_checks(
    user: dict[str, Any],
    social_accounts: object,
    has_profile_readme: bool,
) -> list[CheckResult]:
    socials = social_accounts if isinstance(social_accounts, list) else []
    valid_socials = [
        value
        for value in socials
        if isinstance(value, dict) and isinstance(value.get("url"), str)
    ]
    return [
        _present(
            "profile_name",
            "Public name",
            user.get("name"),
            PROFILE_WEIGHTS["profile_name"],
        ),
        _present(
            "profile_bio",
            "Specific profile bio",
            user.get("bio"),
            PROFILE_WEIGHTS["profile_bio"],
        ),
        _present(
            "profile_url",
            "Portfolio or product URL",
            user.get("blog"),
            PROFILE_WEIGHTS["profile_url"],
        ),
        _present(
            "profile_location",
            "Location",
            user.get("location"),
            PROFILE_WEIGHTS["profile_location"],
        ),
        CheckResult(
            key="profile_socials",
            label="Social proof links",
            status="pass" if valid_socials else "fail",
            weight=PROFILE_WEIGHTS["profile_socials"],
            evidence=f"{len(valid_socials)} public social link(s)",
            remediation="Add at least one relevant professional social account.",
        ),
        CheckResult(
            key="profile_readme",
            label="Profile README repository",
            status="pass" if has_profile_readme else "fail",
            weight=PROFILE_WEIGHTS["profile_readme"],
            evidence="profile repository exists" if has_profile_readme else "not found",
            remediation=f"Create a public {user.get('login')}/{user.get('login')} repository.",
        ),
    ]


def _audit_repository(
    client: GitHubClient, owner: str, repo: dict[str, Any]
) -> RepositoryResult:
    name = str(repo["name"])
    language = repo.get("language") if isinstance(repo.get("language"), str) else None
    code_repository = language is not None
    paths, paths_complete = _repository_paths(client, owner, name, repo)
    checks = [
        _present(
            "description",
            "Repository description",
            repo.get("description"),
            REPOSITORY_WEIGHTS["description"],
        ),
        CheckResult(
            key="topics",
            label="Three or more discovery topics",
            status="pass" if len(repo.get("topics") or []) >= 3 else "fail",
            weight=REPOSITORY_WEIGHTS["topics"],
            evidence=f"{len(repo.get('topics') or [])} topic(s)",
            remediation="Add at least three accurate GitHub topics.",
        ),
        _file_check(paths, paths_complete, "readme", REPOSITORY_WEIGHTS["readme"]),
        CheckResult(
            key="license",
            label="Detected license",
            status="pass" if repo.get("license") else "fail",
            weight=REPOSITORY_WEIGHTS["license"],
            evidence=(repo.get("license") or {}).get("spdx_id", "not detected")
            if isinstance(repo.get("license"), dict)
            else "not detected",
            remediation="Add a license file GitHub can detect.",
        ),
        _path_check(
            paths,
            paths_complete,
            "ci",
            "Continuous integration workflow",
            [WORKFLOW_PATH],
            REPOSITORY_WEIGHTS["ci"],
            skip=not code_repository,
        ),
        _path_check(
            paths,
            paths_complete,
            "tests",
            "Automated test directory",
            TEST_PATHS,
            REPOSITORY_WEIGHTS["tests"],
            skip=not code_repository,
        ),
        _file_check(
            paths,
            paths_complete,
            "contributing",
            REPOSITORY_WEIGHTS["contributing"],
        ),
        _file_check(
            paths,
            paths_complete,
            "security",
            REPOSITORY_WEIGHTS["security"],
        ),
    ]
    return RepositoryResult(
        name=name,
        url=str(repo.get("html_url") or f"https://github.com/{owner}/{name}"),
        language=language,
        stars=_nonnegative_int(repo.get("stargazers_count")),
        forks=_nonnegative_int(repo.get("forks_count")),
        checks=checks,
    )


def _file_check(
    paths: set[str], paths_complete: bool, kind: str, weight: int
) -> CheckResult:
    candidates = MAINTENANCE_FILES[kind]
    return _path_check(
        paths,
        paths_complete,
        kind,
        {
            "readme": "Project README",
            "contributing": "Contribution guide",
            "security": "Security policy",
        }[kind],
        candidates,
        weight,
    )


def _path_check(
    repository_paths: set[str],
    paths_complete: bool,
    key: str,
    label: str,
    paths: list[str],
    weight: int,
    *,
    skip: bool = False,
) -> CheckResult:
    if skip:
        return CheckResult(key, label, "skip", weight, "not a detected code repository")
    path = next(
        (
            path
            for path in paths
            if path.casefold() in repository_paths
            or any(
                repository_path.startswith(f"{path.casefold()}/")
                for repository_path in repository_paths
            )
        ),
        None,
    )
    if path is not None:
        return CheckResult(key, label, "pass", weight, path)
    if not paths_complete:
        return CheckResult(
            key,
            label,
            "skip",
            weight,
            "repository tree was unavailable or truncated",
        )
    return CheckResult(
        key,
        label,
        "fail",
        weight,
        "not found",
        f"Add one of: {', '.join(paths)}.",
    )


def _first_existing_path(
    client: GitHubClient, owner: str, repo: str, paths: list[str]
) -> str | None:
    for path in paths:
        value = client.get_json(
            f"repos/{owner}/{repo}/contents/{path}", allow_not_found=True
        )
        if value is not None:
            return path
    return None


def _repository_paths(
    client: GitHubClient,
    owner: str,
    name: str,
    repo: dict[str, Any],
) -> tuple[set[str], bool]:
    default_branch = repo.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        return set(), True
    encoded_branch = urllib.parse.quote(default_branch, safe="")
    tree = client.get_json(
        f"repos/{owner}/{name}/git/trees/{encoded_branch}",
        params={"recursive": 1},
        allow_not_found=True,
    )
    if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
        return set(), False
    paths = {
        item["path"].casefold()
        for item in tree["tree"]
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    return paths, not bool(tree.get("truncated"))


def _present(key: str, label: str, value: object, weight: int) -> CheckResult:
    present = isinstance(value, str) and bool(value.strip())
    return CheckResult(
        key=key,
        label=label,
        status="pass" if present else "fail",
        weight=weight,
        evidence=value.strip() if present else "missing",
        remediation=f"Add a {label.lower()}." if not present else "",
    )


def _nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
