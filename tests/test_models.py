from portfolio_audit.models import (
    AuditReport,
    CheckResult,
    RepositoryResult,
    evidence_coverage,
    weighted_score,
)


def check(status, weight, *, applicable=True):
    return CheckResult(
        "key", "Label", status, weight, "evidence", applicable=applicable
    )


def test_weighted_score_excludes_only_not_applicable_checks():
    checks = [
        check("pass", 20),
        check("fail", 10),
        check("skip", 20),
        check("skip", 50, applicable=False),
    ]

    assert weighted_score(checks) == 40
    assert evidence_coverage(checks) == 60


def test_empty_weighted_score_is_zero():
    assert weighted_score([check("skip", 10, applicable=False)]) == 0


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
    assert report.coverage == 100
    assert report.to_dict()["repositories"][0]["score"] == 80


def test_report_with_no_repositories_has_zero_overall_score_and_coverage():
    report = AuditReport(
        owner="example",
        generated_at="2026-07-13T00:00:00+00:00",
        profile_url="https://github.com/example",
        profile_checks=[check("pass", 100)],
        repositories=[],
    )

    assert report.profile_score == 100
    assert report.score == 0
    assert report.coverage == 0
