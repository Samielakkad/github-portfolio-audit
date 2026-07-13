import http.client
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
            {"x-ratelimit-remaining": "0"},
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
        items = (
            [{"id": number} for number in range(100)] if page == 1 else [{"id": 100}]
        )
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


def test_retry_after_is_honored_without_shortening():
    responses = [
        (503, {"retry-after": "45"}, b"{}"),
        (200, {}, json.dumps({"login": "octocat"}).encode()),
    ]
    sleeps = []
    client = GitHubClient(
        transport=lambda _url, _headers: responses.pop(0),
        sleep=sleeps.append,
    )

    assert client.get_json("users/octocat") == {"login": "octocat"}
    assert sleeps == [45.0]


def test_invalid_retry_after_fails_without_an_early_retry():
    calls = 0
    sleeps = []

    def transport(_url, _headers):
        nonlocal calls
        calls += 1
        return 429, {"Retry-After": "NaN"}, b"{}"

    client = GitHubClient(
        transport=transport,
        sleep=sleeps.append,
    )

    with pytest.raises(GitHubAPIError, match="429"):
        client.get_json("users/octocat")

    assert calls == 1
    assert sleeps == []


def test_secondary_rate_limit_without_headers_waits_at_least_a_minute():
    responses = [
        (429, {}, json.dumps({"message": "secondary rate limit"}).encode()),
        (200, {}, b"{}"),
    ]
    sleeps = []
    client = GitHubClient(
        transport=lambda _url, _headers: responses.pop(0),
        sleep=sleeps.append,
    )

    assert client.get_json("users/octocat") == {}
    assert sleeps == [60.0]


def test_primary_rate_limit_waits_until_after_reset(monkeypatch):
    responses = [
        (
            403,
            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1030"},
            b"{}",
        ),
        (200, {}, b"{}"),
    ]
    sleeps = []
    monkeypatch.setattr("portfolio_audit.client.time.time", lambda: 1000.0)
    client = GitHubClient(
        transport=lambda _url, _headers: responses.pop(0),
        sleep=sleeps.append,
    )

    assert client.get_json("users/octocat") == {}
    assert sleeps == [31.0]


def test_rate_limit_wait_over_five_minutes_fails_without_retry():
    calls = 0
    sleeps = []

    def transport(_url, _headers):
        nonlocal calls
        calls += 1
        return 429, {"Retry-After": "301"}, b"{}"

    client = GitHubClient(transport=transport, sleep=sleeps.append)

    with pytest.raises(GitHubAPIError, match="429"):
        client.get_json("users/octocat")

    assert calls == 1
    assert sleeps == []


def test_transport_error_retries_with_exponential_backoff():
    calls = 0
    sleeps = []

    def transport(_url, _headers):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("temporary network failure")
        return 200, {}, b"{}"

    client = GitHubClient(transport=transport, sleep=sleeps.append)

    assert client.get_json("users/octocat") == {}
    assert calls == 2
    assert sleeps == [0.5]


def test_incomplete_response_retries():
    calls = 0
    sleeps = []

    def transport(_url, _headers):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise http.client.IncompleteRead(b"partial", 5)
        return 200, {}, b"{}"

    client = GitHubClient(transport=transport, sleep=sleeps.append)

    assert client.get_json("users/octocat") == {}
    assert calls == 2
    assert sleeps == [0.5]


def test_incomplete_response_exhaustion_raises_transport_error():
    calls = 0
    sleeps = []

    def transport(_url, _headers):
        nonlocal calls
        calls += 1
        raise http.client.IncompleteRead(b"partial", 5)

    client = GitHubClient(transport=transport, sleep=sleeps.append)

    with pytest.raises(http.client.IncompleteRead):
        client.get_json("users/octocat")

    assert calls == 3
    assert sleeps == [0.5, 1.0]


def test_retry_exhaustion_raises_last_api_error():
    calls = 0
    sleeps = []

    def transport(_url, _headers):
        nonlocal calls
        calls += 1
        return 503, {}, json.dumps({"message": "Unavailable"}).encode()

    client = GitHubClient(transport=transport, sleep=sleeps.append)

    with pytest.raises(GitHubAPIError, match="503: Unavailable"):
        client.get_json("users/octocat")

    assert calls == 3
    assert sleeps == [0.5, 1.0]


def test_rejects_invalid_retry_limit():
    with pytest.raises(ValueError, match="max_retries"):
        GitHubClient(max_retries=11)
