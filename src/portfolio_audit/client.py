"""Small GitHub REST API client with injectable transport for offline tests."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

Transport = Callable[[str, Mapping[str, str]], tuple[int, Mapping[str, str], bytes]]


class GitHubAPIError(RuntimeError):
    """Raised when GitHub returns a response the audit cannot use."""

    def __init__(self, status: int, message: str, url: str):
        super().__init__(f"GitHub API returned {status}: {message} ({url})")
        self.status = status
        self.url = url


def _http_transport(
    url: str, headers: Mapping[str, str]
) -> tuple[int, Mapping[str, str], bytes]:
    request = urllib.request.Request(url, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


class GitHubClient:
    """Read-only client for the public GitHub REST API."""

    def __init__(
        self,
        token: str | None = None,
        *,
        transport: Transport | None = None,
        api_url: str = "https://api.github.com",
    ):
        self._token = token.strip() if token else None
        self._transport = transport or _http_transport
        self._api_url = api_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "github-portfolio-audit/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        allow_not_found: bool = False,
    ) -> Any:
        query = urllib.parse.urlencode(params or {})
        url = f"{self._api_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{query}"

        status, response_headers, payload = self._transport(url, self._headers())
        if status == 404 and allow_not_found:
            return None
        if status < 200 or status >= 300:
            message = _decode_error(payload)
            remaining = response_headers.get("X-RateLimit-Remaining")
            if status == 403 and remaining == "0":
                message = "API rate limit exhausted; provide GH_TOKEN and retry"
            raise GitHubAPIError(status, message, url)
        if not payload:
            return None
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GitHubAPIError(status, "response was not valid UTF-8 JSON", url) from error

    def get_all(
        self,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        max_pages: int = 10,
    ) -> list[dict[str, Any]]:
        """Read a paginated array endpoint without following untrusted links."""
        base_params = dict(params or {})
        per_page = 100
        items: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            page_items = self.get_json(
                path,
                params={**base_params, "per_page": per_page, "page": page},
            )
            if not isinstance(page_items, list):
                raise GitHubAPIError(200, "paginated response was not an array", path)
            if not all(isinstance(item, dict) for item in page_items):
                raise GitHubAPIError(200, "paginated array contained a non-object", path)
            items.extend(page_items)
            if len(page_items) < per_page:
                break
        return items


def _decode_error(payload: bytes) -> str:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "request failed"
    if isinstance(value, dict) and isinstance(value.get("message"), str):
        return value["message"]
    return "request failed"

