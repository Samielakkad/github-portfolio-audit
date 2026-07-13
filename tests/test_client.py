import json
import urllib.parse

import pytest

from portfolio_audit.client import GitHubAPIError, GitHubClient


def test_get_json_sends_versioned_headers_and_token():
    calls = []

    def transport(url, headers):
        calls.append((url, headers))
        return 200, {}, json.dumps({"login": "octocat"}).encode()

    client = GitHubClient(" secret ", transport=transport)
    result = client.get_json("users/octocat", params={"answer": 42})

    assert result == {"login": "octocat"}
    url, headers = calls[0]
    assert url == "https://api.github.com/users/octocat?answer=42"
    assert headers["Authorization"] == "Bearer secret"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert headers["User-Agent"].startswith("github-portfolio-audit/")


def test_allow_not_found_returns_none():
    client = GitHubClient(transport=lambda _url, _headers: (404, {}, b"{}"))
    assert client.get_json("missing", allow_not_found=True) is None


def test_regular_not_found_raises_with_api_message():
    payload = json.dumps({"message": "Not Found"}).encode()
    client = GitHubClient(transport=lambda _url, _headers: (404, {}, payload))

    with pytest.raises(GitHubAPIError, match="404: Not Found"):
        client.get_json("missing")


def test_rate_limit_error_has_actionable_message():
    client = GitHubClient(
        transport=lambda _url, _headers: (
            403,
            {"X-RateLimit-Remaining": "0"},
            b"{}",
        )
    )

    with pytest.raises(GitHubAPIError, match="provide GH_TOKEN"):
        client.get_json("users/octocat")


def test_invalid_success_payload_is_rejected():
    client = GitHubClient(transport=lambda _url, _headers: (200, {}, b"not-json"))

    with pytest.raises(GitHubAPIError, match="not valid UTF-8 JSON"):
        client.get_json("users/octocat")


def test_get_all_paginates_until_short_page():
    requested_pages = []

    def transport(url, _headers):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        page = int(query["page"][0])
        requested_pages.append(page)
        items = [{"id": number} for number in range(100)] if page == 1 else [{"id": 100}]
        return 200, {}, json.dumps(items).encode()

    result = GitHubClient(transport=transport).get_all("users/octocat/repos")

    assert requested_pages == [1, 2]
    assert len(result) == 101


def test_get_all_rejects_non_array_page():
    client = GitHubClient(
        transport=lambda _url, _headers: (200, {}, json.dumps({"id": 1}).encode())
    )

    with pytest.raises(GitHubAPIError, match="not an array"):
        client.get_all("users/octocat/repos")

