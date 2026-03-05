# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added

- **OneDrive canary deployment** — upload deceptive files to personal OneDrive for
  Business storage to detect unauthorized file browsing. Uses
  `Files.ReadWrite.All` application permission (already required for SharePoint).
  Three bundled templates: Executive Travel Itinerary, Personal Tax Documents,
  and VPN Credentials Backup.

---

## [0.1.0] — 2026-02-23

### Added

- **Outlook canary deployment** — deploy draft messages into hidden mailbox folders or
  send directly to target inboxes via Microsoft Graph `Mail.ReadWrite` / `Mail.Send`
  application permissions.

- **SharePoint canary deployment** — upload deceptive text files to SharePoint site
  document libraries with configurable folder paths and filenames via
  `Sites.ReadWrite.All` / `Files.ReadWrite.All`.

- **Interactive CLI** — step-by-step guided deployment with questionary prompts,
  rich console output, and deployment confirmation gate.

- **YAML template system** — 9 bundled canary templates across Outlook (4) and
  SharePoint (5). Custom template directories supported via
  `ANGLERFISH_TEMPLATES_DIR`.

- **Certificate and secret authentication** — Microsoft Entra application credentials
  via MSAL `ConfidentialClientApplication` (PFX or PEM + thumbprint) or client secret.

- **Environment variable configuration** — full configuration via `ANGLERFISH_*`
  environment variables with CLI flag overrides.

- **`--non-interactive` mode** — run deployments from scripts, CI pipelines, or
  automated demos without prompts. Pair with `--template`, `--target`,
  `--delivery-mode`, `--folder-path`, `--filename`, and `--var KEY=VALUE`.

- **`--dry-run` flag** — validate configuration and authenticate against Microsoft
  Graph without performing any write operations. Useful for pre-deployment validation.

- **`--output-json <path>` flag** — write deployment metadata (artifact IDs,
  timestamps, canary type, template name) to a JSON file for inventory tracking.

- **SharePoint site creation** — create a new Microsoft 365 Group-backed SharePoint
  site from the CLI if no suitable site exists.

- **Graph API retry logic** — automatic retry with exponential backoff on 429
  (rate limit) and 5xx responses.

- **GitHub Actions CI** — Python 3.10 / 3.12 matrix with pytest, ruff lint, ruff
  format check, and pip-audit on every push and pull request.
