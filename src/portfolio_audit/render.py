"""Human, Markdown, and JSON renderers for audit reports."""

from __future__ import annotations

import json

from .models import AuditReport, CheckResult


def render_json(report: AuditReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n"


def render_console(report: AuditReport) -> str:
    lines = [
        f"GitHub portfolio audit: {report.owner}",
        f"Overall {report.score}/100 | profile {report.profile_score}/100 | "
        f"repositories {report.repository_score}/100",
        "",
        "Profile",
    ]
    lines.extend(_console_check(check) for check in report.profile_checks)
    for repository in report.repositories:
        context = f"{repository.language or 'docs/data'}; {repository.stars} stars"
        lines.extend(["", f"{repository.name}: {repository.score}/100 ({context})"])
        lines.extend(_console_check(check) for check in repository.checks)
    return "\n".join(lines) + "\n"


def render_markdown(report: AuditReport) -> str:
    lines = [
        f"# GitHub portfolio audit: `{_escape(report.owner)}`",
        "",
        "| Overall | Profile | Repository average | Repositories audited |",
        "|---:|---:|---:|---:|",
        f"| **{report.score}** | {report.profile_score} | "
        f"{report.repository_score} | {len(report.repositories)} |",
        "",
        "## Profile evidence",
        "",
        "| Status | Check | Evidence |",
        "|:---:|---|---|",
    ]
    lines.extend(_markdown_check(check) for check in report.profile_checks)
    lines.extend(
        [
            "",
            "## Repositories",
            "",
            "| Repository | Score | Language | Stars | Forks |",
            "|---|---:|---|---:|---:|",
        ]
    )
    for repository in report.repositories:
        lines.append(
            f"| [{_escape(repository.name)}]({repository.url}) | "
            f"{repository.score} | {_escape(repository.language or 'docs/data')} | "
            f"{repository.stars} | {repository.forks} |"
        )

    failed = [
        (repository, check)
        for repository in report.repositories
        for check in repository.checks
        if check.status == "fail"
    ]
    failed.extend((None, check) for check in report.profile_checks if check.status == "fail")
    lines.extend(["", "## Actionable gaps", ""])
    if not failed:
        lines.append("No scored gaps found.")
    else:
        for repository, check in failed:
            scope = repository.name if repository is not None else "profile"
            lines.append(
                f"- **{_escape(scope)} / {_escape(check.label)}:** "
                f"{_escape(check.remediation)}"
            )

    lines.extend(
        [
            "",
            "> Scores use only verifiable repository hygiene. Stars, followers, "
            "commit streaks, and raw contribution counts do not increase the score.",
            "",
        ]
    )
    return "\n".join(lines)


def _console_check(check: CheckResult) -> str:
    marker = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}[check.status]
    line = f"  [{marker}] {check.label}: {check.evidence}"
    if check.status == "fail" and check.remediation:
        line += f" -> {check.remediation}"
    return line


def _markdown_check(check: CheckResult) -> str:
    marker = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}[check.status]
    return f"| {marker} | {_escape(check.label)} | {_escape(check.evidence)} |"


def _escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")

