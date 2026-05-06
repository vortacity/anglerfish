# Contributing to Anglerfish

Thank you for your interest in contributing. This document covers development setup,
template authoring, and the pull request process.

---

## Development Setup

**Requirements:** Python 3.10+, `git`.

```bash
# 1. Clone the repository
git clone https://github.com/vortacity/anglerfish.git
cd anglerfish

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install the package in editable mode with dev dependencies
pip install -e ".[dev]"

# 4. Verify the CLI is available
anglerfish --version
```

---

## Running Tests and Linting

```bash
# Run all tests
pytest

# Run tests with verbose output
pytest -v

# Lint
ruff check src tests

# Check formatting
ruff format --check src tests

# Apply formatting
ruff format src tests

# Security scan (optional, requires dev install)
bandit -r src

# Dependency vulnerability audit (optional)
pip-audit
```

All tests must pass and `ruff check` must be clean before a PR can be merged.

---

## Template Authoring Guide

Canary templates live under `src/anglerfish/templates/outlook/`.
Each template is a YAML file. This release supports Outlook templates only.

### Outlook Template Schema

```yaml
name: Human-readable template name
description: One-line description shown in the CLI template picker
type: outlook

# Variables are optional. Each variable is prompted for during deployment.
variables:
  - name: var_name
    description: Prompt shown to the user
    default: "optional default value"

folder_name: Hidden Folder Name          # Required
subject: "[Tag] Email subject"           # Required
sender_name: Display Name                # Required
sender_email: from@contoso.com           # Required
body_html: |                             # Required - HTML string
  <html>
  <body>
  <p>Dear ${var_name},</p>
  <p>Body content here.</p>
  </body>
  </html>
```

**Important:** Do not include clickable hyperlinks (`<a href="...">`) in `body_html`.
Detection is access-based (UAL `MailItemsAccessed`); no URL callbacks are used.
Body content should be plausible as a standalone internal communication.

### Variable Substitution

All templates use Python `string.Template` syntax: `${variable_name}`.
Variables without a `default` are required at deployment time.
Variable names must be valid Python identifiers.

### Testing Your Template

After adding a template, run the template tests to verify it loads correctly:

```bash
pytest tests/test_templates.py -v
```

Then do a smoke test with `--dry-run` to confirm the CLI accepts it:

```bash
anglerfish --canary-type outlook --template "Your Template Name" \
  --target test@example.com --delivery-mode draft --non-interactive --dry-run
```

---

## Adding a New Deployer Type

New deployer types are future extension work, not part of the current
Outlook-only product surface. If you add one, update the public docs and
permissions guidance in the same change.

1. Create `src/anglerfish/deployers/<type>.py` implementing `BaseDeployer`.
2. Add a corresponding `dataclass` model to `src/anglerfish/models.py`.
3. Register the new type in `src/anglerfish/templates.py` (`_TEMPLATE_SCHEMA`).
4. Wire up the new type in the `src/anglerfish/cli/` package
   (`_main.py`, `deploy.py`, and `prompts.py` as needed for template selection,
   auth mode, target prompts, and deployer instantiation).
5. Add deployer unit tests in `tests/test_<type>_deployer.py`.
6. Add at least one bundled template in `src/anglerfish/templates/<type>/`.

---

## Pull Request Guidelines

- Open an issue first for significant changes (new deployer types, breaking changes).
- Keep PRs focused: one logical change per PR.
- All tests must pass (`pytest`) and linting must be clean (`ruff check src tests`).
- Update `CHANGELOG.md` with a brief description of your change under `[Unreleased]`.
- Do not commit credentials, `.env` files, certificate material (`*.pfx`, `*.pem`,
  `*.key`), or any file matched by `.gitignore`.

---

## Security Reporting

To report a security vulnerability, open a GitHub Security Advisory (private) rather
than a public issue. Do not include exploit details in public issue reports.
