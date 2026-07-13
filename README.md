# github-portfolio-audit

[![CI](https://github.com/Samielakkad/github-portfolio-audit/actions/workflows/ci.yml/badge.svg)](https://github.com/Samielakkad/github-portfolio-audit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)

Evidence-based GitHub profile and repository audits from the command line or a
reusable GitHub Action.

The score answers a narrow question: **can a reviewer verify that these public
repositories are documented, testable, licensed, maintained, and discoverable?**
It does not reward stars, followers, commit streaks, contribution volume, or
other signals that can be inflated without improving the work.

## What it checks

Profile evidence:

- specific bio, location, portfolio URL, and professional social links;
- a public profile README repository.

Repository evidence:

- description and at least three accurate topics;
- README and detected license;
- CI and test directories for detected code repositories;
- contribution and security policies.

Stars and forks appear as context only. They never change the score.

## Install and run

```bash
python -m pip install git+https://github.com/Samielakkad/github-portfolio-audit.git
github-portfolio-audit octocat --format console
```

Audit selected repositories and write machine-readable output:

```bash
github-portfolio-audit octocat \
  --repo Spoon-Knife \
  --format json \
  --output audit.json \
  --min-score 70
```

Anonymous GitHub API access is enough for small public profiles. Set `GH_TOKEN`
to avoid the anonymous rate limit when auditing many repositories. The token is
never printed or written to a report.

## Use as a GitHub Action

```yaml
name: Portfolio evidence

on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: Samielakkad/github-portfolio-audit@v1
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          min-score: "80"
```

The Action writes a Markdown report to the workflow job summary and fails when
the score is below `min-score`. It performs read-only API calls.

## Score model

Each scored check has a fixed weight:

| Profile check | Weight | Repository check | Weight |
|---|---:|---|---:|
| Public name | 10 | Description | 15 |
| Specific bio | 25 | Three or more topics | 10 |
| Portfolio/product URL | 15 | README | 20 |
| Location | 5 | Detected license | 15 |
| Professional social link | 15 | CI workflow | 20 |
| Profile README | 30 | Test directory | 10 |
| | | Contribution guide | 5 |
| | | Security policy | 5 |

Skipped checks are removed from the denominator, so a documentation repository
is not penalized for lacking a test suite. An unavailable or truncated Git tree
also produces `SKIP`, never a false failure. The total combines profile evidence
(30%) and the mean repository score (70%). JSON output includes every check,
weight, status, evidence string, and remediation.

This is a hygiene audit, not a hiring verdict. It cannot assess code design,
research validity, product usefulness, security quality, or whether stars came
from real adoption. Read the repositories before making those judgments.

## Development

```bash
python -m pip install -e ".[dev]"
python -m ruff check src tests
python -m pytest
python -m build
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the evidence standard and
[SECURITY.md](SECURITY.md) for responsible disclosure and token handling.
