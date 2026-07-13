import pytest

from portfolio_audit.audit import PROFILE_WEIGHTS, REPOSITORY_WEIGHTS, audit_portfolio
from portfolio_audit.client import GitHubAPIError


class FakeClient:
    def __init__(self, responses=None, repositories=None):
        self.responses = responses or {}
        self.repositories = repositories or []
        self.get_json_calls = []
        self.get_all_calls = []

    def get_json(self, path, *, params=None, allow_not_found=False):
        del params
        self.get_json_calls.append(path)
        if path in self.responses:
            response = self.responses[path]
            if isinstance(response, BaseException):
                raise response
            return response
        if allow_not_found:
            return None
        raise AssertionError(f"unexpected API path: {path}")

    def get_all(self, path, *, params=None, max_pages=10):
        self.get_all_calls.append((path, params, max_pages))
        return self.repositories


def user(**overrides):
    value = {
        "login": "Example",
        "name": "Example Developer",
        "bio": "Builds reliable developer tools.",
        "blog": "https://example.dev",
        "location": "Rabat, Morocco",
    }
    value.update(overrides)
    return value


def repository(name="quality-tool", **overrides):
    value = {
        "name": name,
        "html_url": f"https://github.com/Example/{name}",
        "description": "A tested quality tool.",
        "topics": ["github", "quality", "audit"],
        "license": {"spdx_id": "MIT"},
        "language": "Python",
        "default_branch": "main",
        "stargazers_count": 4,
        "forks_count": 2,
        "fork": False,
        "archived": False,
        "private": False,
    }
    value.update(overrides)
    return value


def complete_responses(repo_name="quality-tool"):
    return {
        "users/Example": user(),
        "users/Example/social_accounts": [
            {"provider": "linkedin", "url": "https://social.test"}
        ],
        "repos/Example/Example": {"name": "Example"},
        "repos/Example/Example/contents/README.md": {
            "name": "README.md",
            "type": "file",
            "size": 100,
        },
        f"repos/Example/{repo_name}/git/trees/main": {
            "truncated": False,
            "tree": [
                {"path": "README.md", "type": "blob", "size": 100},
                {
                    "path": ".github/workflows/ci.yml",
                    "type": "blob",
                    "size": 100,
                },
                {"path": "tests/test_tool.py", "type": "blob", "size": 100},
                {"path": "CONTRIBUTING.md", "type": "blob", "size": 100},
                {"path": "SECURITY.md", "type": "blob", "size": 100},
            ],
        },
    }


def test_complete_profile_and_repository_score_100():
    client = FakeClient(complete_responses(), [repository()])

    report = audit_portfolio(client, " Example ")

    assert report.owner == "Example"
    assert report.profile_score == 100
    assert report.repository_score == 100
    assert report.score == 100
    assert report.repositories[0].stars == 4
    assert client.get_all_calls[0][0] == "users/Example/repos"


def test_scoring_contracts_each_total_100():
    assert sum(PROFILE_WEIGHTS.values()) == 100
    assert sum(REPOSITORY_WEIGHTS.values()) == 100


def test_missing_evidence_fails_without_counting_code_only_checks():
    docs_repo = repository(
        "docs",
        description=None,
        topics=[],
        license=None,
        language=None,
        stargazers_count=999,
    )
    responses = {
        "users/Example": user(name=None, bio=None, blog=None, location=None),
        "users/Example/social_accounts": [],
        "repos/Example/Example": None,
        "repos/Example/docs/git/trees/main": {
            "truncated": False,
            "tree": [{"path": "README.md", "type": "blob", "size": 100}],
        },
    }
    report = audit_portfolio(FakeClient(responses, [docs_repo]), "Example")

    result = report.repositories[0]
    assert result.score == 29
    assert next(check for check in result.checks if check.key == "ci").status == "skip"
    assert not next(check for check in result.checks if check.key == "ci").applicable
    assert (
        next(check for check in result.checks if check.key == "tests").status == "skip"
    )
    assert report.profile_score == 0
    assert report.score == 20


def test_filters_profile_forks_archives_and_private_repositories():
    active = repository("active")
    repositories = [
        repository("Example"),
        repository("fork", fork=True),
        repository("archive", archived=True),
        repository("private", private=True),
        active,
        repository("second"),
    ]
    client = FakeClient(complete_responses("active"), repositories)

    report = audit_portfolio(client, "Example", max_repositories=1)

    assert [result.name for result in report.repositories] == ["active"]


def test_named_repository_bypasses_repository_listing():
    selected = repository("selected")
    responses = complete_responses("selected")
    responses["repos/Example/selected"] = selected
    client = FakeClient(responses)

    report = audit_portfolio(client, "Example", repository_names=["selected"])

    assert [result.name for result in report.repositories] == ["selected"]
    assert client.get_all_calls == []


def test_truncated_tree_skips_unknown_paths_instead_of_false_failure():
    repo = repository("large")
    responses = complete_responses("large")
    responses["repos/Example/large/git/trees/main"] = {
        "truncated": True,
        "tree": [{"path": "README.md", "type": "blob", "size": 100}],
    }
    report = audit_portfolio(FakeClient(responses, [repo]), "Example")

    checks = {check.key: check for check in report.repositories[0].checks}
    assert checks["readme"].status == "pass"
    assert checks["ci"].status == "skip"
    assert checks["security"].status == "skip"
    assert checks["ci"].applicable
    assert report.repositories[0].score == 60
    assert report.repositories[0].coverage == 60


def test_default_branch_is_url_encoded_for_tree_lookup():
    repo = repository("release", default_branch="release/v1")
    responses = complete_responses("release")
    responses["repos/Example/release/git/trees/release%2Fv1"] = responses.pop(
        "repos/Example/release/git/trees/main"
    )

    report = audit_portfolio(FakeClient(responses, [repo]), "Example")
    assert report.repositories[0].score == 100


def test_rejects_invalid_owner_and_repository_limit():
    client = FakeClient()

    for owner in ("", "   "):
        try:
            audit_portfolio(client, owner)
        except ValueError as error:
            assert "owner" in str(error)
        else:
            raise AssertionError("blank owner was accepted")

    for limit in (0, 101):
        try:
            audit_portfolio(client, "Example", max_repositories=limit)
        except ValueError as error:
            assert "between 1 and 100" in str(error)
        else:
            raise AssertionError("invalid repository limit was accepted")


def test_zero_eligible_repositories_cannot_receive_profile_score():
    report = audit_portfolio(FakeClient(complete_responses(), []), "Example")

    assert report.profile_score == 100
    assert report.repository_score == 0
    assert report.score == 0
    assert report.coverage == 0


def test_explicit_ineligible_repository_is_an_error():
    responses = complete_responses()
    client = FakeClient(responses)

    with pytest.raises(ValueError, match="not auditable"):
        audit_portfolio(client, "Example", repository_names=["Example"])


def test_named_repositories_are_deduplicated_case_insensitively():
    responses = complete_responses("selected")
    responses["repos/Example/selected"] = repository("selected")
    client = FakeClient(responses)

    report = audit_portfolio(
        client,
        "Example",
        repository_names=[" selected ", "SELECTED", "selected"],
    )

    assert [result.name for result in report.repositories] == ["selected"]
    assert client.get_json_calls.count("repos/Example/selected") == 1


def test_tree_entry_types_sizes_and_workflow_extension_are_verified():
    repo = repository("bogus")
    responses = complete_responses("bogus")
    responses["repos/Example/bogus/git/trees/main"] = {
        "truncated": False,
        "tree": [
            {"path": "README.md", "type": "tree"},
            {
                "path": "docs/README.md",
                "type": "blob",
                "mode": "120000",
                "size": 16,
            },
            {
                "path": ".github/workflows/README.md",
                "type": "blob",
                "size": 100,
            },
            {"path": "tests", "type": "blob", "size": 100},
            {"path": "CONTRIBUTING.md", "type": "tree"},
            {"path": "SECURITY.md", "type": "blob", "size": 0},
        ],
    }

    result = audit_portfolio(FakeClient(responses, [repo]), "Example").repositories[0]
    checks = {check.key: check for check in result.checks}

    assert result.score == 40
    assert result.coverage == 100
    for key in ("readme", "ci", "tests", "contributing", "security"):
        assert checks[key].status == "fail"


def test_empty_repository_409_is_scored_without_aborting_audit():
    repo = repository("empty")
    responses = complete_responses("empty")
    responses["repos/Example/empty/git/trees/main"] = GitHubAPIError(
        409,
        "Git Repository is empty.",
        "https://api.github.test/repos/Example/empty/git/trees/main",
    )

    result = audit_portfolio(FakeClient(responses, [repo]), "Example").repositories[0]

    assert result.score == 40
    assert result.coverage == 100
    assert (
        next(check for check in result.checks if check.key == "readme").status == "fail"
    )


def test_supported_readme_locations_and_account_community_defaults_count():
    repo = repository("locations")
    responses = complete_responses("locations")
    responses["repos/Example/locations/git/trees/main"] = {
        "truncated": False,
        "tree": [
            {"path": "docs/README.rst", "type": "blob", "size": 100},
            {
                "path": ".github/workflows/ci.yaml",
                "type": "blob",
                "size": 100,
            },
            {"path": "tests/test_tool.py", "type": "blob", "size": 100},
        ],
    }
    responses["repos/Example/.github"] = {
        "name": ".github",
        "private": False,
        "visibility": "public",
        "default_branch": "main",
    }
    responses["repos/Example/.github/git/trees/main"] = {
        "truncated": False,
        "tree": [
            {
                "path": "docs/CONTRIBUTING.md",
                "type": "blob",
                "size": 100,
            },
            {
                "path": ".github/SECURITY.md",
                "type": "blob",
                "size": 100,
            },
        ],
    }

    result = audit_portfolio(FakeClient(responses, [repo]), "Example").repositories[0]
    checks = {check.key: check for check in result.checks}

    assert result.score == 100
    assert checks["readme"].evidence == "docs/README.rst"
    assert checks["contributing"].evidence.startswith("account .github default")
    assert checks["security"].evidence.startswith("account .github default")


def test_profile_readme_must_be_nonempty_root_markdown_file():
    responses = complete_responses()
    responses["repos/Example/Example/contents/README.md"] = {
        "name": "README.md",
        "type": "file",
        "size": 0,
    }

    report = audit_portfolio(FakeClient(responses, [repository()]), "Example")
    check = next(
        check for check in report.profile_checks if check.key == "profile_readme"
    )

    assert check.status == "fail"
    assert report.profile_score == 70


def test_private_profile_repository_does_not_count_as_public_evidence():
    responses = complete_responses()
    responses["repos/Example/Example"] = {
        "name": "Example",
        "private": True,
        "visibility": "private",
    }
    client = FakeClient(responses, [repository()])

    report = audit_portfolio(client, "Example")
    check = next(
        check for check in report.profile_checks if check.key == "profile_readme"
    )

    assert check.status == "fail"
    assert "repos/Example/Example/contents/README.md" not in client.get_json_calls


def test_empty_local_policy_does_not_fall_back_to_account_default():
    repo = repository("local-empty")
    responses = complete_responses("local-empty")
    local_tree = responses["repos/Example/local-empty/git/trees/main"]["tree"]
    responses["repos/Example/local-empty/git/trees/main"]["tree"] = [
        *(item for item in local_tree if item["path"] != "CONTRIBUTING.md"),
        {"path": "docs/CONTRIBUTING.md", "type": "blob", "size": 0},
    ]
    responses["repos/Example/.github"] = {
        "name": ".github",
        "private": False,
        "visibility": "public",
        "default_branch": "main",
    }
    responses["repos/Example/.github/git/trees/main"] = {
        "truncated": False,
        "tree": [
            {"path": "CONTRIBUTING.md", "type": "blob", "size": 100},
        ],
    }

    result = audit_portfolio(FakeClient(responses, [repo]), "Example").repositories[0]
    check = next(check for check in result.checks if check.key == "contributing")

    assert check.status == "fail"
