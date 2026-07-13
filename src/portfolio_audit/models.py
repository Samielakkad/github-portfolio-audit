"""Serializable audit result models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

CheckStatus = Literal["pass", "fail", "skip"]


@dataclass(frozen=True)
class CheckResult:
    key: str
    label: str
    status: CheckStatus
    weight: int
    evidence: str
    remediation: str = ""


@dataclass
class RepositoryResult:
    name: str
    url: str
    language: str | None
    stars: int
    forks: int
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def score(self) -> int:
        return weighted_score(self.checks)

    def to_dict(self) -> dict:
        result = asdict(self)
        result["score"] = self.score
        return result


@dataclass
class AuditReport:
    owner: str
    generated_at: str
    profile_url: str
    profile_checks: list[CheckResult]
    repositories: list[RepositoryResult]

    @property
    def profile_score(self) -> int:
        return weighted_score(self.profile_checks)

    @property
    def repository_score(self) -> int:
        if not self.repositories:
            return 0
        return round(sum(repo.score for repo in self.repositories) / len(self.repositories))

    @property
    def score(self) -> int:
        if not self.repositories:
            return self.profile_score
        return round(self.profile_score * 0.3 + self.repository_score * 0.7)

    def to_dict(self) -> dict:
        return {
            "owner": self.owner,
            "generated_at": self.generated_at,
            "profile_url": self.profile_url,
            "score": self.score,
            "profile_score": self.profile_score,
            "repository_score": self.repository_score,
            "profile_checks": [asdict(check) for check in self.profile_checks],
            "repositories": [repo.to_dict() for repo in self.repositories],
        }


def weighted_score(checks: list[CheckResult]) -> int:
    scorable = [check for check in checks if check.status != "skip"]
    denominator = sum(check.weight for check in scorable)
    if denominator == 0:
        return 0
    numerator = sum(check.weight for check in scorable if check.status == "pass")
    return round(numerator * 100 / denominator)

