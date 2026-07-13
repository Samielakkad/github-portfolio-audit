"""Deterministic GitHub REST fixture for the composite Action integration test."""

from __future__ import annotations

import base64
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


def _blob(value: str) -> dict[str, str]:
    return {
        "encoding": "base64",
        "content": base64.b64encode(value.encode()).decode(),
    }


RESPONSES = {
    "/health": {"ok": True},
    "/users/Example": {
        "login": "Example",
        "name": "Example Developer",
        "bio": "Builds reliable developer tools.",
        "blog": "https://example.test",
        "location": "Rabat, Morocco",
    },
    "/users/Example/social_accounts": [
        {"provider": "linkedin", "url": "https://example.test/profile"}
    ],
    "/repos/Example/Example": {
        "name": "Example",
        "private": False,
        "visibility": "public",
    },
    "/repos/Example/Example/contents/README.md": {
        "name": "README.md",
        "type": "file",
        "size": 100,
    },
    "/repos/Example/quality-tool": {
        "name": "quality-tool",
        "html_url": "https://github.com/Example/quality-tool",
        "description": "A tested quality tool.",
        "topics": ["github", "quality", "audit"],
        "license": {"spdx_id": "MIT"},
        "language": "Python",
        "default_branch": "main",
        "stargazers_count": 4,
        "forks_count": 2,
        "fork": False,
        "archived": False,
        "disabled": False,
        "private": False,
        "visibility": "public",
    },
    "/repos/Example/quality-tool/git/trees/main": {
        "truncated": False,
        "tree": [
            {"path": "README.md", "type": "blob", "size": 100},
            {
                "path": ".github/workflows/ci.yml",
                "type": "blob",
                "size": 100,
                "sha": "ci-workflow",
            },
            {"path": "tests/test_tool.py", "type": "blob", "size": 100},
            {"path": "CONTRIBUTING.md", "type": "blob", "size": 100},
            {"path": "SECURITY.md", "type": "blob", "size": 100},
        ],
    },
    "/repos/Example/quality-tool/git/blobs/ci-workflow": _blob(
        "on: [push, pull_request]\n"
        "jobs:\n  test:\n    runs-on: ubuntu-latest\n    steps: []\n"
    ),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        if path not in RESPONSES:
            self._write(404, {"message": "Not Found"})
            return
        self._write(200, RESPONSES[path])

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _write(self, status: int, value: object) -> None:
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    port = int(sys.argv[1])
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
