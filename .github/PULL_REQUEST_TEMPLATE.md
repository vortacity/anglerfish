## What

<!-- One or two sentences: what does this change and why. -->

## Checklist

- [ ] Tests added or updated for the change (`pytest --cov=anglerfish --cov-fail-under=85` passes)
- [ ] `ruff check src tests` and `ruff format --check src tests` are clean
- [ ] `mypy` passes
- [ ] `bandit -r src -ll` is clean
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] No credentials, tenant IDs, certificate material, or live-tenant artifacts in the diff
