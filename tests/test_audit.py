from portfolio_audit.audit import PROFILE_WEIGHTS, REPOSITORY_WEIGHTS, audit_portfolio


class FakeClient:
    def __init__(self, responses=None, repositories=None):
        self.responses = responses or {}
        self.repositories = repositories or []
        self.get_all_calls = []

    def get_json(self, path, *, params=None, allow_not_found=False):
        del params
        if path in self.responses:
            return self.responses[path]
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
        "users/Example/social_accounts": [{"provider": "linkedin", "url": "https://social.test"}],
        "repos/Example/Example": {"name": "Example"},
        "repos/Example/Example/contents/README.md": {"name": "README.md"},
        f"repos/Example/{repo_name}/git/trees/main": {
            "truncated": False,
            "tree": [
                {"path": "README.md"},
                {"path": ".github/workflows/ci.yml"},
                {"path": "tests/test_tool.py"},
                {"path": "CONTRIBUTING.md"},
                {"path": "SECURITY.md"},
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
            "tree": [{"path": "README.md"}],
        },
    }
    report = audit_portfolio(FakeClient(responses, [docs_repo]), "Example")

    result = report.repositories[0]
    assert result.score == 29
    assert next(check for check in result.checks if check.key == "ci").status == "skip"
    assert next(check for check in result.checks if check.key == "tests").status == "skip"
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
        "tree": [{"path": "README.md"}],
    }
    report = audit_portfolio(FakeClient(responses, [repo]), "Example")

    checks = {check.key: check for check in report.repositories[0].checks}
    assert checks["readme"].status == "pass"
    assert checks["ci"].status == "skip"
    assert checks["security"].status == "skip"


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
