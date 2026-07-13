import http.client
import io
import json
from unittest.mock import patch

import pytest

from portfolio_audit.cli import _write_stdout, main
from portfolio_audit.client import GitHubAPIError
from portfolio_audit.models import AuditReport, CheckResult


def report(score_pass=True):
    checks = [
        CheckResult(
            "bio",
            "Bio",
            "pass" if score_pass else "fail",
            100,
            "present" if score_pass else "missing",
            "Add bio.",
        )
    ]
    return AuditReport(
        owner="example",
        generated_at="2026-07-13T00:00:00+00:00",
        profile_url="https://github.com/example",
        profile_checks=checks,
        repositories=[],
    )


@patch("portfolio_audit.cli.audit_portfolio")
def test_json_output_and_token_forwarding(mock_audit, monkeypatch, capsys):
    mock_audit.return_value = report()
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("GITHUB_API_URL", "https://github.example.test/api/v3")

    assert main(["example", "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["owner"] == "example"
    client = mock_audit.call_args.args[0]
    assert client._token == "secret"
    assert client._api_url == "https://github.example.test/api/v3"


@patch("portfolio_audit.cli.audit_portfolio")
def test_project_api_override_takes_precedence(mock_audit, monkeypatch):
    mock_audit.return_value = report()
    monkeypatch.setenv("GITHUB_API_URL", "https://api.github.com")
    monkeypatch.setenv("PORTFOLIO_AUDIT_API_URL", "http://127.0.0.1:8765")

    assert main(["example"]) == 0

    client = mock_audit.call_args.args[0]
    assert client._api_url == "http://127.0.0.1:8765"


@patch("portfolio_audit.cli.audit_portfolio")
def test_writes_markdown_output_file(mock_audit, tmp_path):
    mock_audit.return_value = report()
    output = tmp_path / "nested" / "report.md"

    assert main(["example", "--format", "markdown", "--output", str(output)]) == 0
    assert "GitHub portfolio audit" in output.read_text(encoding="utf-8")


@patch("portfolio_audit.cli.audit_portfolio")
def test_minimum_score_returns_one(mock_audit):
    mock_audit.return_value = report(score_pass=False)
    assert main(["example", "--min-score", "1"]) == 1


@patch("portfolio_audit.cli.audit_portfolio")
def test_profile_only_report_cannot_pass_positive_threshold(mock_audit):
    mock_audit.return_value = report(score_pass=True)
    assert main(["example", "--min-score", "1"]) == 1


@patch("portfolio_audit.cli.audit_portfolio")
def test_api_error_exits_two_with_message(mock_audit, capsys):
    mock_audit.side_effect = GitHubAPIError(403, "rate limited", "https://api.test")

    with pytest.raises(SystemExit) as error:
        main(["example"])

    assert error.value.code == 2
    assert "rate limited" in capsys.readouterr().err


@patch("portfolio_audit.cli.audit_portfolio")
def test_incomplete_response_exits_two_without_traceback(mock_audit, capsys):
    mock_audit.side_effect = http.client.IncompleteRead(b"partial", 5)

    with pytest.raises(SystemExit) as error:
        main(["example"])

    assert error.value.code == 2
    stderr = capsys.readouterr().err
    assert stderr.startswith("error: IncompleteRead")
    assert "Traceback" not in stderr


@patch("portfolio_audit.cli.audit_portfolio")
def test_output_write_error_exits_two_without_traceback(mock_audit, tmp_path, capsys):
    mock_audit.return_value = report()

    with pytest.raises(SystemExit) as error:
        main(["example", "--output", str(tmp_path)])

    assert error.value.code == 2
    stderr = capsys.readouterr().err
    assert stderr.startswith("error: could not write report:")
    assert "Traceback" not in stderr


def test_stdout_is_always_written_as_utf8(monkeypatch):
    class LegacyConsole:
        encoding = "cp1252"

        def __init__(self):
            self.buffer = io.BytesIO()

        def write(self, value):
            raise AssertionError(f"text stream used instead of UTF-8 buffer: {value}")

    console = LegacyConsole()
    monkeypatch.setattr("portfolio_audit.cli.sys.stdout", console)

    _write_stdout("Applied AI · أدوات\n")

    assert console.buffer.getvalue().decode("utf-8") == "Applied AI · أدوات\n"


def test_rejects_score_outside_range():
    with pytest.raises(SystemExit) as error:
        main(["example", "--min-score", "101"])
    assert error.value.code == 2
