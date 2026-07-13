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
- a non-empty README in a GitHub-supported location and a detected license;
- a parseable GitHub Actions workflow triggered by pushes, pull requests, or
  merge queues, with at least one executable job;
- recognizable automated test source in conventional directories or filenames
  across common language ecosystems;
- non-empty contribution and security policies, including applicable defaults
  from the account's public `.github` repository.

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
never printed or written to a report. Read-only requests retry transient network
errors and common server failures twice. Rate-limit retries honor GitHub's full
`Retry-After` or reset window; waits over five minutes fail promptly instead of
retrying early.

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
      - uses: Samielakkad/github-portfolio-audit@v1
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          min-score: "80"
```

The Action writes a Markdown report to the workflow job summary and fails when
the score is below `min-score`. It performs read-only API calls, so consumers do
not need to check out their repository first. Reports are created inside a
private directory under `RUNNER_TEMP`, never in the caller workspace, and are
removed when the step exits.

## Score model

Each scored check has a fixed weight:

| Profile check | Weight | Repository check | Weight |
|---|---:|---|---:|
| Public name | 10 | Description | 15 |
| Specific bio | 25 | Three or more topics | 10 |
| Portfolio/product URL | 15 | README | 20 |
| Location | 5 | Detected license | 15 |
| Professional social link | 15 | Continuous integration workflow | 20 |
| Profile README | 30 | Recognizable automated tests | 10 |
| | | Contribution guide | 5 |
| | | Security policy | 5 |

Checks that do not apply are removed from the denominator, so a documentation
repository is not penalized for lacking a test suite. Unknown evidence from an
unavailable or truncated Git tree remains in the denominator but is shown as
`SKIP`, avoiding both a false failure label and an inflated score. Reports expose
weighted evidence coverage separately from score. The total combines profile
evidence (30%) and the mean repository score (70%); when no eligible repository
is audited, the overall score and coverage are zero. Explicitly selected forks,
archives, private repositories, and profile README repositories produce an
error instead of silently falling back to a profile-only score.

JSON output includes every check's weight, status, applicability, evidence, and
remediation, plus repository and overall coverage. Repeated `--repo` names are
deduplicated case-insensitively before API requests.

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
