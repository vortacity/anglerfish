# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added

- **Tamper detection**: the monitor now alerts when a canary item is
  deleted, moved, or modified (`HardDelete`, `SoftDelete`,
  `MoveToDeletedItems`, `Move`, `Update`) — anti-forensic cleanup of a
  planted artifact is itself high-confidence attacker behavior. Alerts
  carry a `category` field (`access` or `tamper`) across all channels.
- **Microsoft Teams alert channel** (`--teams-webhook-url` /
  `ANGLERFISH_TEAMS_WEBHOOK_URL`): Adaptive Card notifications via a
  Teams workflow (Power Automate) webhook, with the same hardening as
  the Slack sink (HTTPS only, webhook URL never logged).
- **Generic webhook alert channel** (`--webhook-url` /
  `ANGLERFISH_WEBHOOK_URL`): JSON POST of each alert
  (`schema_version: 1`) for SIEM/SOAR collectors, with optional
  HMAC-SHA256 body signing (`ANGLERFISH_WEBHOOK_HMAC_SECRET` →
  `X-Anglerfish-Signature` header).
- **Machine-readable output**: `--format json` on `list` and `verify`
  emits a JSON array on stdout (no banner or table) for scripting; exit
  codes unchanged.
- **Canary lifecycle plugin API**: `CanaryType`
  (`deployers/base.py`) covers deploy, remove, verify, trigger-access,
  audit content types, and audit-event matching; the CLI, monitor,
  verify, and cleanup paths dispatch through `deployers/registry.py`.
  Adding a canary surface is one class plus one `register()` call.
- Documentation: step-by-step
  [Exchange RBAC scoping guide](docs/scoping-permissions.md) for
  `Mail.ReadWrite`, a
  [production deployment guide](docs/production-deployment.md), a
  [monitor operations reference](docs/monitoring.md) (heartbeat
  contract, state-file semantics, alert-log schema, scale envelope),
  and [privacy and data handling](docs/privacy.md).

### Changed

- Deployment records are written as **schema version 2**: canonical
  `canary_type` key only, `verified` as a JSON boolean, and a
  `schema_version` field. v1 records (legacy `type` alias, string
  booleans) are read transparently and migrate on rewrite; unknown keys
  are preserved round-trip.
- Credentials are passed by value (`AuthConfig`) from prompts to
  authentication; the auth flow and the monitor's token refresh no
  longer write secrets to the process environment.
- Directories Anglerfish creates for records, monitor state, and alert
  logs (including `~/.anglerfish`) now use owner-only (`0700`)
  permissions.
- `--help` output is branded `anglerfish` regardless of invocation style
  (previously `usage: __main__.py` when run as a module).

### Fixed

- A deployment record carrying both the legacy `type` key and
  `canary_type` behaved differently in cleanup (which preferred `type`)
  than in monitor/verify (which preferred `canary_type`); `canary_type`
  now wins everywhere via a single normalizer.
- Monitor state files with `Z`-suffixed timestamps were rejected as
  corrupt on Python 3.10 (`datetime.fromisoformat` accepts the `Z`
  suffix only from 3.11), and the warm-restart watermark parse would
  have crashed the same way.

---

## [2.1.0] — 2026-06-09

### Fixed

- A global `--demo` placed before the `monitor` or `verify` subcommand was
  silently ignored and the command ran in real mode (live auth and API calls).
  All subcommands now respect `--demo` regardless of flag position.
- `monitor --interval` rejects values below 1; `0` or a negative value
  previously produced a sleep-free hot loop against the Management API.
- Monitor downtime longer than 24 hours no longer silently skips audit events.
  The backlog is now ingested in successive ≤24-hour windows (the API maximum
  per request) up to the ~7-day content retention floor, and any range past
  retention is reported as unrecoverable instead of being dropped quietly.
- The monitor heartbeat reports `"degraded"` when a poll cycle could not ingest
  its full window, instead of always claiming `"healthy"` — external watchdogs
  can now detect a blind monitor.
- A transient token-refresh failure (AAD blip, network error) no longer
  terminates the long-running monitor; the loop keeps the current token and
  retries on the next cycle. Token refresh also honors the tenant's actual
  token lifetime (`expires_in` from MSAL) instead of assuming 55 minutes.
- Send-mode deploy: a verification timeout after a successful `sendMail` no
  longer raises and discards the deployment record — which left a live,
  untracked canary in the target mailbox. The record is now written with
  `verified=false` and a `verify_note`, and the CLI prints a warning.
- Send-mode inbox verification requires the candidate message's from-address to
  be the target mailbox, so a same-subject message from another sender can no
  longer be recorded as the canary (and later deleted by cleanup).
- `verify` now confirms the canary message itself in addition to its hidden
  folder; a deleted message inside a surviving folder is reported `GONE`.
- `cleanup` and `demo-access` on records with JSON `null` fields raise clean
  errors instead of `AttributeError` tracebacks, and corrupt monitor state
  files (bad counters, non-list `seen_ids`, invalid `last_poll_end`) produce a
  clean `MonitorError` instead of a raw traceback.
- Unknown `--var` keys are reported with the template's declared variable names
  instead of being silently dropped.
- Monitor no longer advances its poll watermark when an audit-log list or fetch
  fails mid-window, so transient API errors can no longer skip canary access
  events permanently. Re-polling is safe because seen-ID dedup suppresses
  already-dispatched alerts.
- Interactive prompts on a non-interactive stdin (CI, pipe, daemon) now exit
  cleanly with guidance instead of raising an uncaught `EOFError` traceback.
- `monitor` retry/backoff now honors `Retry-After` headers expressed as an
  HTTP-date, matching the Graph client (previously collapsed to 1 second).
- A single malformed YAML file in a custom `ANGLERFISH_TEMPLATES_DIR` no longer
  hides every other template from listing.
- Malformed deployment records skipped during monitoring are now logged so an
  operator can see when a canary drops out of monitoring.
- Templates that reference an undeclared `${placeholder}` are now rejected at
  load time instead of silently leaking the literal text into a deployed canary.
- Record, state, alert-log, and heartbeat writes no longer require `os.fchmod`,
  so they work on platforms (e.g. Windows) that lack it.
- Management Activity API error messages of the `{"Message": "..."}` shape are
  now surfaced verbatim instead of as a generic `Unknown:` string.

### Security

- Server-supplied `Retry-After` throttle delays are capped at 120 seconds in
  both the Graph and Management API clients; a misbehaving server or proxy
  could previously park the CLI (or block monitor shutdown) for an arbitrary
  duration.
- Management API content pagination is guarded against self-referencing
  `NextPageUri` loops and unbounded page counts.
- Alert fields derived from audit events (which an accessing actor can influence,
  e.g. `ClientInfoString`) are now escaped before console rendering, preventing
  Rich console-markup injection / alert spoofing.
- HTTP clients no longer follow redirects; an unexpected 3xx from Graph or the
  Management Activity API is treated as an error instead of being followed to a
  potentially unvalidated host.
- The Slack webhook sink rejects non-`https` URLs and no longer logs the webhook
  URL (a bearer secret) on failure.
- The `pkg://` template loader rejects `.`/`..`/separator path segments,
  closing in-package path traversal.
- The Management Activity API subscription-start `POST` no longer auto-retries,
  so a transient failure cannot double-execute the write.

### Added

- GitHub issue forms, a pull-request checklist template, and Dependabot
  configuration for pip and GitHub Actions.
- Python 3.13 added to the CI matrix and package classifiers.

### Documentation

- `.env.example` now documents the monitor variables
  (`ANGLERFISH_MONITOR_STATE_FILE`, `ANGLERFISH_MONITOR_ALERT_LOG`,
  `ANGLERFISH_SLACK_WEBHOOK_URL`, `ANGLERFISH_MONITOR_NO_CONSOLE`) and
  `ANGLERFISH_TEMPLATES_DIR`.
- CONTRIBUTING.md and AGENTS.md list every CI gate (coverage floor, format
  check, mypy, bandit, CLI smoke) instead of only pytest and ruff, and the
  AGENTS.md dependency list matches `pyproject.toml`.
- README demo caption matches what the recording shows, the Quickstart
  references `scripts/quickstart.sh`, and the draft demo record fixture uses
  the v2 record shape (`canary_id`, ID-suffixed folder name).

### Documentation (pre-release polish)

- Reframed the project as a general open-source tool: removed Black Hat /
  Arsenal / reviewer / booth framing from the README, docs, AUTHORS, and
  CHANGELOG, and removed the conference-specific demo script.
- Corrected drift: AGENTS.md described `alerts.py` as a "Teams" sink (it is
  Slack); the README listed the third template as "IT Compliance Audit" (its
  real name is "IT Compliance Audit Notice", so `--template` now copy-pastes);
  AGENTS.md/CONTRIBUTING.md referenced a non-existent `_TEMPLATE_SCHEMA`.
- Documented the optional `examples/anglerfish-monitor.service` systemd unit.

### Changed

- Monitor now rebuilds its Management API client only when the access token
  actually rotates, preserving the HTTP connection pool across polls.
- Management API pagination header lookup is case-insensitive, and following an
  absolute `NextPageUri`/content URI no longer appends a duplicate
  `PublisherIdentifier` query parameter.
- `.env.example` is now shell-sourceable (all placeholders quoted, all
  user-supplied credentials commented) and no longer advertises the
  effectively-fixed `ANGLERFISH_AUTH_MODE`.
- Pinned the pre-commit `ruff` hook and the dev `ruff` dependency to the same
  0.15.x line CI uses, so local hooks and CI agree.

### Removed

- Dead/unused code and config: the unreachable `ANGLERFISH_GRAPH_DELEGATED_SCOPES`
  setting, the always-`True` `_TokenManager.refreshed` property, an unused
  `cli_var_values` parameter, and the unused `pytest-asyncio` dependency and
  `asyncio_mode` pytest config (the project has no async code).

---

## [2.0.0] — 2026-05-08

### Breaking

- Reset the public MVP around Outlook canaries only. SharePoint deployment,
  OneDrive deployment, batch manifests, and the dashboard are no longer part of
  the supported surface area.

### Changed

- Reset to a breaking Outlook-only release; removed non-Outlook canary surfaces
  from the main product path.
- Added Management Activity API URL host validation.
- Added cleaned-up record lookback for late UAL correlation.
- Added sanitized evidence examples and demo collateral.
- Added `demo-access` to trigger authorized Graph reads for generating audit
  evidence.
- Added per-deployment canary IDs to draft hidden-folder names for stronger
  fallback correlation.
- Require `internetMessageId` in deployment records so primary UAL correlation
  cannot silently degrade.
- Rewrote the README, architecture notes, and demo tenant guide around the
  supported Outlook deploy, list, verify, cleanup, and monitor workflow.
- Demo fixtures now cover the two supported Outlook delivery modes: `draft` and
  `send`.
- Updated demo recording scripts around Outlook deploy and audit-log alerts.

---

## [1.0.0] — 2026-03-11

First public release.

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
