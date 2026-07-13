from portfolio_audit.models import (
    AuditReport,
    CheckResult,
    RepositoryResult,
    weighted_score,
)


def check(status, weight):
    return CheckResult("key", "Label", status, weight, "evidence")


def test_weighted_score_excludes_skips():
    assert weighted_score([check("pass", 20), check("fail", 10), check("skip", 70)]) == 67


def test_empty_weighted_score_is_zero():
    assert weighted_score([check("skip", 10)]) == 0


def test_report_combines_profile_and_repository_evidence():
    repository = RepositoryResult(
        name="tool",
        url="https://github.com/example/tool",
        language="Python",
        stars=3,
        forks=1,
        checks=[check("pass", 80), check("fail", 20)],
    )
    report = AuditReport(
        owner="example",
        generated_at="2026-07-13T00:00:00+00:00",
        profile_url="https://github.com/example",
        profile_checks=[check("pass", 50), check("fail", 50)],
        repositories=[repository],
    )

    assert report.profile_score == 50
    assert report.repository_score == 80
    assert report.score == 71
    assert report.to_dict()["repositories"][0]["score"] == 80

