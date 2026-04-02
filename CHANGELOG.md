# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Breaking

- Reset the public MVP around Outlook canaries only. SharePoint deployment,
  OneDrive deployment, batch manifests, and the dashboard are no longer part of
  the supported surface area.

### Changed

- Rewrote the README, architecture notes, and demo tenant guide around the
  supported Outlook deploy, list, verify, cleanup, and monitor workflow.
- Demo fixtures now cover the two supported Outlook delivery modes: `draft` and
  `send`.

---

## [1.0.0] — 2026-03-11

First public release, prepared for Black Hat Arsenal submission.

### Added

- **`batch` subcommand** — deploy multiple canaries from a YAML manifest with
  a single command. Authenticates once, deploys all entries sequentially, writes
  one deployment record per canary. Supports `--dry-run` and `--demo` modes.

- **`dashboard` subcommand** — full-screen Textual TUI showing canary status,
  live alert feed, and summary statistics. Supports `--demo` mode for offline
  demos, configurable poll and verify intervals, and alert log history.

- **`verify` subcommand** — check that deployed canary artifacts still exist via
  Graph API health checks. Supports single records, directory scans, and `--demo`
  mode. Exit code 1 if any canary is gone or errored.

- **Slack alerting** — `--slack-webhook-url` flag on `monitor` sends Block Kit
  formatted alerts to a Slack incoming webhook when canary access events are
  detected.

- **`--demo` mode** — run any subcommand offline with simulated data. No
  authentication or Graph API calls required. Useful for conference demos,
  local testing, and CI validation.

- **ASCII art banner** — slant-style ASCII art header displayed on CLI launch.

- **Project logo** — added to README header.

---

## [0.2.0] — 2026-03-06

### Added

- **`monitor` subcommand** — continuously poll the Office 365 Management Activity API
  for canary access events. Correlates audit events against deployment records using
  `CanaryIndex` (internet message ID, item ID, filename, folder path). Supports
  `--once` for single-poll mode, `--interval` for custom poll frequency, and
  `--exclude-app-id` to suppress self-access noise.

- **Management Activity API client** (`audit.py`) — subscription management, content
  blob listing with pagination, and event fetching with retry/backoff.

- **Rich file format support (.docx / .xlsx)** — canary files can now be deployed as
  Word documents or Excel spreadsheets in addition to plain text. File format is
  determined by the filename extension. Four new templates added: Board Meeting
  Minutes (.docx), Compensation Analysis (.xlsx), Performance Review Notes (.docx),
  and Investment Portfolio (.xlsx).

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
