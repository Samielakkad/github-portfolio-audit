import json

from portfolio_audit.models import AuditReport, CheckResult, RepositoryResult
from portfolio_audit.render import render_console, render_json, render_markdown


def sample_report():
    return AuditReport(
        owner="example",
        generated_at="2026-07-13T00:00:00+00:00",
        profile_url="https://github.com/example",
        profile_checks=[
            CheckResult("bio", "Profile | bio", "fail", 20, "missing", "Add bio."),
            CheckResult("url", "Portfolio", "pass", 10, "https://example.dev"),
        ],
        repositories=[
            RepositoryResult(
                name="tool",
                url="https://github.com/example/tool",
                language="Python",
                stars=500,
                forks=2,
                checks=[
                    CheckResult("readme", "README", "pass", 80, "README.md"),
                    CheckResult(
                        "security",
                        "Security",
                        "fail",
                        20,
                        "not found",
                        "Add SECURITY.md.",
                    ),
                ],
            )
        ],
    )


def test_json_renderer_is_machine_readable():
    value = json.loads(render_json(sample_report()))
    assert value["owner"] == "example"
    assert value["repositories"][0]["stars"] == 500
    assert value["repositories"][0]["score"] == 80


def test_console_renderer_includes_remediation():
    value = render_console(sample_report())
    assert "[FAIL] Profile | bio: missing -> Add bio." in value
    assert "tool: 80/100" in value


def test_markdown_renderer_escapes_tables_and_rejects_vanity_scoring():
    value = render_markdown(sample_report())
    assert "Profile \\| bio" in value
    assert "**tool / Security:** Add SECURITY.md." in value
    assert "Stars, followers" in value
    assert "500" in value


def test_markdown_renderer_surfaces_unknown_applicable_evidence():
    report = sample_report()
    report.repositories[0].checks = [
        CheckResult("ci", "CI", "skip", 100, "tree unavailable")
    ]

    value = render_markdown(report)

    assert "Evidence was unavailable" in value
    assert "No scored gaps found" not in value
