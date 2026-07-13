"""Evidence collection and deterministic portfolio checks."""

from __future__ import annotations

import base64
import binascii
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

import yaml

from .client import GitHubAPIError, GitHubClient
from .models import AuditReport, CheckResult, RepositoryResult

README_NAMES = ["README.md", "README.rst", "README.txt", "README"]
CONTRIBUTING_NAMES = [
    "CONTRIBUTING.md",
    "CONTRIBUTING.rst",
    "CONTRIBUTING.txt",
    "CONTRIBUTING",
]
MAINTENANCE_FILES = {
    "readme": [
        *(f".github/{name}" for name in README_NAMES),
        *README_NAMES,
        *(f"docs/{name}" for name in README_NAMES),
    ],
    "contributing": [
        *(f".github/{name}" for name in CONTRIBUTING_NAMES),
        *CONTRIBUTING_NAMES,
        *(f"docs/{name}" for name in CONTRIBUTING_NAMES),
    ],
    "security": [".github/SECURITY.md", "SECURITY.md", "docs/SECURITY.md"],
}
TEST_PATHS = ["tests", "test", "spec", "__tests__"]
WORKFLOW_PATH = ".github/workflows"
MAX_WORKFLOW_BYTES = 1_000_000
MAX_WORKFLOW_CANDIDATES = 10
CI_TRIGGERS = {"merge_group", "pull_request", "pull_request_target", "push"}
TEST_FILE_SUFFIXES = {
    ".bash",
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".dart",
    ".exs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".lua",
    ".mjs",
    ".php",
    ".ps1",
    ".py",
    ".r",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".swift",
    ".ts",
    ".tsx",
}
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


@dataclass(frozen=True)
class TreeEntry:
    path: str
    kind: str
    size: int | None
    mode: str | None
    sha: str | None

    @property
    def is_nonempty_blob(self) -> bool:
        return (
            self.kind == "blob"
            and self.mode != "120000"
            and self.size is not None
            and self.size > 0
        )


@dataclass(frozen=True)
class RepositoryTree:
    entries: dict[str, TreeEntry]
    complete: bool


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
    selected_names = _deduplicate_repository_names(repository_names or [])

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
    if (
        isinstance(profile_repo, dict)
        and not profile_repo.get("private")
        and profile_repo.get("visibility") in (None, "public")
    ):
        has_profile_readme = _has_profile_readme(client, canonical_owner)
    profile_checks = _profile_checks(user, social_accounts, has_profile_readme)
    community_defaults = _community_default_tree(client, canonical_owner)

    explicit_selection = bool(selected_names)
    if explicit_selection:
        selected_names = selected_names[:max_repositories]
        raw_repositories = [
            client.get_json(
                f"repos/{canonical_owner}/{urllib.parse.quote(name, safe='')}"
            )
            for name in selected_names
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
        ineligibility = _repository_ineligibility(raw_repo, canonical_owner)
        if ineligibility is not None:
            if explicit_selection:
                name = raw_repo.get("name") or "requested repository"
                raise ValueError(f"{name} is not auditable: {ineligibility}")
            continue
        repositories.append(
            _audit_repository(
                client,
                canonical_owner,
                raw_repo,
                community_defaults,
            )
        )
        if len(repositories) >= max_repositories:
            break

    if explicit_selection and not repositories:
        raise ValueError("none of the requested repositories could be audited")

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
            evidence="non-empty root README.md" if has_profile_readme else "not found",
            remediation=""
            if has_profile_readme
            else (
                f"Add a non-empty root README.md to the public "
                f"{user.get('login')}/{user.get('login')} repository."
            ),
        ),
    ]


def _audit_repository(
    client: GitHubClient,
    owner: str,
    repo: dict[str, Any],
    community_defaults: RepositoryTree,
) -> RepositoryResult:
    name = str(repo["name"])
    language = repo.get("language") if isinstance(repo.get("language"), str) else None
    code_repository = language is not None
    tree = _repository_tree(client, owner, name, repo)
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
        _file_check(tree, "readme", REPOSITORY_WEIGHTS["readme"]),
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
        _ci_check(
            client,
            owner,
            name,
            tree,
            REPOSITORY_WEIGHTS["ci"],
            applicable=code_repository,
        ),
        _tests_check(
            tree,
            REPOSITORY_WEIGHTS["tests"],
            applicable=code_repository,
        ),
        _file_check(
            tree,
            "contributing",
            REPOSITORY_WEIGHTS["contributing"],
            fallback=community_defaults,
        ),
        _file_check(
            tree,
            "security",
            REPOSITORY_WEIGHTS["security"],
            fallback=community_defaults,
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
    tree: RepositoryTree,
    kind: str,
    weight: int,
    *,
    fallback: RepositoryTree | None = None,
) -> CheckResult:
    candidates = MAINTENANCE_FILES[kind]
    label = {
        "readme": "Project README",
        "contributing": "Contribution guide",
        "security": "Security policy",
    }[kind]
    local = _first_existing_entry(tree, candidates)
    if local is not None:
        index, entry = local
        if not tree.complete and index > 0:
            return _unknown_check(kind, label, weight)
        return _maintenance_file_result(kind, label, weight, entry)

    if not tree.complete:
        return _unknown_check(kind, label, weight)

    if fallback is not None:
        default = _first_existing_entry(fallback, candidates)
        if default is not None:
            index, entry = default
            if not fallback.complete and index > 0:
                return _unknown_check(kind, label, weight)
            return _maintenance_file_result(
                kind,
                label,
                weight,
                entry,
                prefix="account .github default: ",
            )
        if not fallback.complete:
            return _unknown_check(kind, label, weight)

    return CheckResult(
        kind,
        label,
        "fail",
        weight,
        "no non-empty file found",
        f"Add one of: {', '.join(candidates)}.",
    )


def _maintenance_file_result(
    kind: str,
    label: str,
    weight: int,
    entry: TreeEntry,
    *,
    prefix: str = "",
) -> CheckResult:
    if entry.is_nonempty_blob:
        return CheckResult(kind, label, "pass", weight, f"{prefix}{entry.path}")
    return CheckResult(
        kind,
        label,
        "fail",
        weight,
        f"{prefix}{entry.path} is empty or not a regular file",
        f"Replace {entry.path} with a non-empty regular file.",
    )


def _ci_check(
    client: GitHubClient,
    owner: str,
    name: str,
    tree: RepositoryTree,
    weight: int,
    *,
    applicable: bool,
) -> CheckResult:
    label = "Continuous integration workflow"
    if not applicable:
        return _not_applicable_check("ci", label, weight)
    prefix = f"{WORKFLOW_PATH.casefold()}/"
    candidates = sorted(
        (
            entry
            for path, entry in tree.entries.items()
            if path.startswith(prefix)
            and "/" not in path[len(prefix) :]
            and path.endswith((".yml", ".yaml"))
            and entry.is_nonempty_blob
            and entry.size is not None
            and entry.size <= MAX_WORKFLOW_BYTES
            and entry.sha is not None
        ),
        key=lambda entry: entry.path.casefold(),
    )
    for workflow in candidates[:MAX_WORKFLOW_CANDIDATES]:
        if _is_valid_workflow(client, owner, name, workflow):
            return CheckResult("ci", label, "pass", weight, workflow.path)
    if not tree.complete:
        return _unknown_check("ci", label, weight)
    if len(candidates) > MAX_WORKFLOW_CANDIDATES:
        return CheckResult(
            "ci",
            label,
            "skip",
            weight,
            f"more than {MAX_WORKFLOW_CANDIDATES} workflow candidates",
            "Remove obsolete or invalid workflows so validation can finish safely.",
        )
    return CheckResult(
        "ci",
        label,
        "fail",
        weight,
        "no valid continuous-integration workflow found",
        "Add a push, pull-request, or merge-queue workflow with an executable job.",
    )


def _tests_check(tree: RepositoryTree, weight: int, *, applicable: bool) -> CheckResult:
    label = "Recognizable automated tests"
    if not applicable:
        return _not_applicable_check("tests", label, weight)
    test_file = next(
        (
            entry
            for entry in tree.entries.values()
            if entry.is_nonempty_blob
            and _is_plausible_test_file(entry.path)
        ),
        None,
    )
    if test_file is not None:
        return CheckResult("tests", label, "pass", weight, test_file.path)
    if not tree.complete:
        return _unknown_check("tests", label, weight)
    return CheckResult(
        "tests",
        label,
        "fail",
        weight,
        "no recognizable non-empty test file found",
        f"Add conventionally named test files below one of: {', '.join(TEST_PATHS)}.",
    )


def _is_valid_workflow(
    client: GitHubClient,
    owner: str,
    name: str,
    entry: TreeEntry,
) -> bool:
    blob = client.get_json(
        f"repos/{owner}/{name}/git/blobs/{entry.sha}", allow_not_found=True
    )
    if not isinstance(blob, dict) or blob.get("encoding") != "base64":
        return False
    content = blob.get("content")
    if not isinstance(content, str):
        return False
    try:
        decoded = base64.b64decode("".join(content.split()), validate=True)
        workflow = yaml.load(decoded.decode("utf-8"), Loader=yaml.BaseLoader)
    except (binascii.Error, RecursionError, UnicodeDecodeError, yaml.YAMLError):
        return False
    if not isinstance(workflow, dict) or not isinstance(workflow.get("jobs"), dict):
        return False
    return _has_ci_trigger(workflow.get("on")) and any(
        _is_executable_job(job) for job in workflow["jobs"].values()
    )


def _has_ci_trigger(value: object) -> bool:
    if isinstance(value, str):
        return value in CI_TRIGGERS
    if isinstance(value, list):
        return any(isinstance(item, str) and item in CI_TRIGGERS for item in value)
    if isinstance(value, dict):
        return any(isinstance(key, str) and key in CI_TRIGGERS for key in value)
    return False


def _is_executable_job(job: object) -> bool:
    if not isinstance(job, dict):
        return False
    reusable_workflow = job.get("uses")
    if isinstance(reusable_workflow, str):
        return _is_reusable_workflow_reference(reusable_workflow.strip())
    runner = job.get("runs-on")
    valid_runner = (isinstance(runner, str) and bool(runner.strip())) or (
        isinstance(runner, list)
        and bool(runner)
        and all(isinstance(label, str) and bool(label.strip()) for label in runner)
    )
    if not valid_runner or not isinstance(job.get("steps"), list):
        return False
    return any(_is_executable_step(step) for step in job["steps"])


def _is_reusable_workflow_reference(value: str) -> bool:
    if not value or any(character.isspace() for character in value):
        return False
    if value.startswith("./.github/workflows/"):
        return "@" not in value and value.endswith((".yml", ".yaml"))
    path, separator, reference = value.rpartition("@")
    return (
        bool(separator)
        and bool(reference)
        and "/.github/workflows/" in path
        and path.endswith((".yml", ".yaml"))
    )


def _is_executable_step(step: object) -> bool:
    if not isinstance(step, dict):
        return False
    return any(
        isinstance(step.get(key), str) and bool(step[key].strip())
        for key in ("run", "uses")
    )


def _is_plausible_test_file(path: str) -> bool:
    file = PurePosixPath(path)
    suffix = file.suffix.casefold()
    if suffix not in TEST_FILE_SUFFIXES:
        return False
    if any(part.casefold() in TEST_PATHS for part in file.parts[:-1]):
        return True

    name = file.name.casefold()
    stem = file.stem
    folded_stem = stem.casefold()
    if (
        name.startswith(("test_", "test-", "test."))
        or folded_stem.endswith(("_test", "-test", "_spec", "-spec"))
        or ".test." in name
        or ".spec." in name
    ):
        return True
    return suffix in {".cs", ".java", ".kt", ".kts"} and stem.endswith(
        ("Test", "Tests", "TestCase", "Spec")
    )


def _not_applicable_check(key: str, label: str, weight: int) -> CheckResult:
    return CheckResult(
        key,
        label,
        "skip",
        weight,
        "not a detected code repository",
        applicable=False,
    )


def _unknown_check(key: str, label: str, weight: int) -> CheckResult:
    return CheckResult(
        key,
        label,
        "skip",
        weight,
        "repository tree was unavailable or truncated",
    )


def _first_existing_entry(
    tree: RepositoryTree, candidates: list[str]
) -> tuple[int, TreeEntry] | None:
    for index, candidate in enumerate(candidates):
        entry = tree.entries.get(candidate.casefold())
        if entry is not None:
            return index, entry
    return None


def _has_profile_readme(client: GitHubClient, owner: str) -> bool:
    value = client.get_json(
        f"repos/{owner}/{owner}/contents/README.md", allow_not_found=True
    )
    return (
        isinstance(value, dict)
        and value.get("type") == "file"
        and _nonnegative_int(value.get("size")) > 0
    )


def _community_default_tree(client: GitHubClient, owner: str) -> RepositoryTree:
    repo = client.get_json(f"repos/{owner}/.github", allow_not_found=True)
    if not isinstance(repo, dict):
        return RepositoryTree({}, True)
    if repo.get("private") or repo.get("visibility") not in (None, "public"):
        return RepositoryTree({}, True)
    return _repository_tree(client, owner, ".github", repo)


def _repository_tree(
    client: GitHubClient,
    owner: str,
    name: str,
    repo: dict[str, Any],
) -> RepositoryTree:
    default_branch = repo.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch:
        return RepositoryTree({}, True)
    encoded_branch = urllib.parse.quote(default_branch, safe="")
    try:
        tree = client.get_json(
            f"repos/{owner}/{name}/git/trees/{encoded_branch}",
            params={"recursive": 1},
            allow_not_found=True,
        )
    except GitHubAPIError as error:
        if error.status == 409 and "empty" in error.message.casefold():
            return RepositoryTree({}, True)
        raise
    if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
        return RepositoryTree({}, False)

    entries: dict[str, TreeEntry] = {}
    for item in tree["tree"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        path = item["path"]
        kind = item.get("type") if isinstance(item.get("type"), str) else ""
        mode = item.get("mode") if isinstance(item.get("mode"), str) else None
        sha = item.get("sha") if isinstance(item.get("sha"), str) else None
        raw_size = item.get("size")
        size = (
            raw_size
            if isinstance(raw_size, int)
            and not isinstance(raw_size, bool)
            and raw_size >= 0
            else None
        )
        entries[path.casefold()] = TreeEntry(path, kind, size, mode, sha)
    return RepositoryTree(entries, not bool(tree.get("truncated")))


def _deduplicate_repository_names(names: list[str]) -> list[str]:
    result = []
    seen = set()
    for raw_name in names:
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError("repository names must be non-empty strings")
        name = raw_name.strip()
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            result.append(name)
    return result


def _repository_ineligibility(repo: dict[str, Any], owner: str) -> str | None:
    name = repo.get("name")
    if not isinstance(name, str) or not name:
        return "repository metadata did not include a name"
    if name.casefold() == owner.casefold():
        return "profile README repositories are audited as profile evidence"
    if repo.get("fork"):
        return "forks are excluded"
    if repo.get("archived"):
        return "archived repositories are excluded"
    if repo.get("disabled"):
        return "disabled repositories are excluded"
    if repo.get("private") or repo.get("visibility") not in (None, "public"):
        return "only public repositories are supported"
    return None


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
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )
