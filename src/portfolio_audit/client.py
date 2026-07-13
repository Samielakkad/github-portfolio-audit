"""Small GitHub REST API client with injectable transport for offline tests."""

from __future__ import annotations

import http.client
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

Transport = Callable[[str, Mapping[str, str]], tuple[int, Mapping[str, str], bytes]]
Sleeper = Callable[[float], None]
TRANSIENT_STATUSES = {408, 500, 502, 503, 504}
RATE_LIMIT_STATUSES = {403, 429}
MAX_RETRY_DELAY_SECONDS = 300.0


class GitHubAPIError(RuntimeError):
    """Raised when GitHub returns a response the audit cannot use."""

    def __init__(self, status: int, message: str, url: str):
        super().__init__(f"GitHub API returned {status}: {message} ({url})")
        self.status = status
        self.message = message
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
        sleep: Sleeper | None = None,
        max_retries: int = 2,
    ):
        if max_retries < 0 or max_retries > 10:
            raise ValueError("max_retries must be between 0 and 10")
        self._token = token.strip() if token else None
        self._transport = transport or _http_transport
        self._api_url = api_url.rstrip("/")
        self._sleep = sleep or time.sleep
        self._max_retries = max_retries

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "github-portfolio-audit/0.1.1",
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

        for attempt in range(self._max_retries + 1):
            try:
                status, response_headers, payload = self._transport(
                    url, self._headers()
                )
            except (OSError, http.client.HTTPException):
                if attempt >= self._max_retries:
                    raise
                self._sleep(_transient_delay(attempt))
                continue
            if attempt >= self._max_retries:
                break
            delay = _retry_delay(status, response_headers, payload, attempt)
            if delay is None:
                break
            self._sleep(delay)

        if status == 404 and allow_not_found:
            return None
        if status < 200 or status >= 300:
            message = _decode_error(payload)
            remaining = _header(response_headers, "X-RateLimit-Remaining")
            if status == 403 and remaining == "0":
                message = "API rate limit exhausted; provide GH_TOKEN and retry"
            raise GitHubAPIError(status, message, url)
        if not payload:
            return None
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GitHubAPIError(
                status, "response was not valid UTF-8 JSON", url
            ) from error

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
                raise GitHubAPIError(
                    200, "paginated array contained a non-object", path
                )
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


def _retry_delay(
    status: int,
    headers: Mapping[str, str],
    payload: bytes,
    attempt: int,
) -> float | None:
    if status not in TRANSIENT_STATUSES | RATE_LIMIT_STATUSES:
        return None

    retry_after = _header(headers, "Retry-After")
    if retry_after is not None:
        return _safe_retry_delay(retry_after)

    if status in RATE_LIMIT_STATUSES:
        remaining = _header(headers, "X-RateLimit-Remaining")
        if remaining == "0":
            reset = _header(headers, "X-RateLimit-Reset")
            if reset is None:
                return None
            try:
                delay = max(float(reset) - time.time() + 1.0, 0.0)
            except ValueError:
                return None
            return _bounded_delay(delay)

        message = _decode_error(payload).casefold()
        is_secondary = status == 429 or "secondary rate limit" in message
        if not is_secondary:
            return None
        return _bounded_delay(60.0 * (2**attempt))

    return _transient_delay(attempt)


def _safe_retry_delay(value: str) -> float | None:
    try:
        delay = float(value)
    except ValueError:
        return None
    return _bounded_delay(delay)


def _bounded_delay(delay: float) -> float | None:
    if not math.isfinite(delay) or delay < 0 or delay > MAX_RETRY_DELAY_SECONDS:
        return None
    return delay


def _transient_delay(attempt: int) -> float:
    return min(0.5 * (2**attempt), 4.0)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.casefold()
    for key, value in headers.items():
        if key.casefold() == expected:
            return value
    return None
