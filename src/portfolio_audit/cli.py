"""Command-line interface."""

from __future__ import annotations

import argparse
import http.client
import os
import sys
from pathlib import Path

from . import __version__
from .audit import audit_portfolio
from .client import GitHubAPIError, GitHubClient
from .render import render_console, render_json, render_markdown

RENDERERS = {
    "console": render_console,
    "json": render_json,
    "markdown": render_markdown,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="github-portfolio-audit",
        description="Audit verifiable GitHub profile and repository quality evidence.",
    )
    parser.add_argument("owner", help="GitHub account login to audit")
    parser.add_argument(
        "--repo",
        action="append",
        dest="repositories",
        metavar="NAME",
        help="audit one named repository (repeatable)",
    )
    parser.add_argument(
        "--max-repositories",
        type=int,
        default=20,
        metavar="N",
        help="maximum active public repositories to audit (default: 20)",
    )
    parser.add_argument(
        "--format",
        choices=sorted(RENDERERS),
        default="console",
        help="output format (default: console)",
    )
    parser.add_argument("--output", type=Path, help="write output to this file")
    parser.add_argument(
        "--min-score",
        type=_score,
        metavar="0-100",
        help="exit 1 when the overall score is below this threshold",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    api_url = (
        os.environ.get("PORTFOLIO_AUDIT_API_URL")
        or os.environ.get("GITHUB_API_URL")
        or "https://api.github.com"
    )
    try:
        report = audit_portfolio(
            GitHubClient(token, api_url=api_url),
            args.owner,
            repository_names=args.repositories,
            max_repositories=args.max_repositories,
        )
    except (
        GitHubAPIError,
        OSError,
        http.client.HTTPException,
        ValueError,
    ) as error:
        parser.exit(2, f"error: {error}\n")

    rendered = RENDERERS[args.format](report)
    try:
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            _write_stdout(rendered)
    except OSError as error:
        parser.exit(2, f"error: could not write report: {error}\n")

    if args.min_score is not None and report.score < args.min_score:
        return 1
    return 0


def _score(value: str) -> int:
    try:
        score = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if score < 0 or score > 100:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return score


def _write_stdout(value: str) -> None:
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(value.encode("utf-8"))
        return
    sys.stdout.write(value)


if __name__ == "__main__":
    raise SystemExit(main())
