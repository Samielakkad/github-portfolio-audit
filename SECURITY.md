# Security policy

## Reporting

Report vulnerabilities privately to `sam25@mails.tsinghua.edu.cn`. Do not put
tokens, private repository names, or API responses containing private data in a
public issue.

## Token handling

The CLI reads `GH_TOKEN` or `GITHUB_TOKEN` from the environment. It never writes
the token to output and makes only read-only API requests. For public portfolio
audits, use the default GitHub Actions token with `contents: read` permissions.

