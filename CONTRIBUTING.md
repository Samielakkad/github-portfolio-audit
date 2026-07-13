# Contributing

Contributions should improve the audit's evidence quality, API correctness, or
portability. A new scored check needs:

1. a public GitHub API signal that can be reproduced;
2. a documented reason the signal matters to a repository reviewer;
3. passing and failing fixture tests;
4. no dependence on followers, stars, streaks, or raw activity volume.

Checks must distinguish evidence that is genuinely not applicable from evidence
that could not be verified. Unknown evidence remains part of the score denominator
and must reduce the reported coverage percentage.

## Development

```bash
python -m pip install -e ".[dev]"
python -m ruff check src tests
python -m pytest
python -m build
```

Open an issue before changing score weights or adding network permissions.
