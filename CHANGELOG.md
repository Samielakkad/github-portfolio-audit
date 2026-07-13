# Changelog

All notable changes are documented here. The project follows semantic versioning.

## 0.1.1 - 2026-07-13

- Isolate Action reports in a private runner temporary directory and remove them
  on exit instead of trusting a caller-workspace path.
- Validate Git tree object types, non-empty file sizes, workflow extensions, and
  test-directory contents before awarding repository evidence.
- Distinguish inapplicable checks from unknown evidence and report weighted
  evidence coverage; zero audited repositories now produce a zero overall score.
- Handle empty Git repositories without aborting a portfolio audit.
- Recognize GitHub-supported README and community-file locations, including
  applicable defaults from an account's public `.github` repository.
- Reject explicitly selected ineligible repositories and deduplicate repeated
  repository names case-insensitively.
- Retry transient read-only API requests with bounded exponential backoff and
  `Retry-After` support.

## 0.1.0 - 2026-07-13

- Add read-only GitHub REST API profile and repository audits.
- Add deterministic profile and repository evidence scoring.
- Add console, JSON, and Markdown output.
- Add a reusable composite GitHub Action with a minimum-score gate.
- Add offline transport, audit, rendering, and CLI tests.
