<div align="center">
  <img src="docs/images/logo.png" alt="Anglerfish" width="400">
</div>

[![CI](https://github.com/vortacity/anglerfish/actions/workflows/ci.yml/badge.svg)](https://github.com/vortacity/anglerfish/actions/workflows/ci.yml)

Deploy M365 canary tokens and detect unauthorized access — no callback URLs, no DNS beacons, no external infrastructure.

Anglerfish is a Python CLI that provisions deceptive artifacts (Outlook draft emails, SharePoint documents, OneDrive files) in Microsoft 365 tenants via the Graph API. When an attacker accesses a canary artifact, the M365 Unified Audit Log generates an event (`MailItemsAccessed`, `FileAccessed`) that your SIEM can alert on. Detection is entirely access-based — the canary never phones home.

## How It Works

```text
1. Deploy     anglerfish → Graph API → canary artifact lands in M365
2. Trigger    attacker reads email / opens file → UAL audit event fires
3. Detect     SIEM queries UAL for artifact IDs from deployment record → alert
```

No HTTP callbacks, no DNS beacons, no embedded tracking pixels. The canary is a normal M365 object; detection relies on Microsoft's built-in audit pipeline.

## Key Features

- **Outlook canaries** — draft messages in hidden folders or sent to Inbox
- **SharePoint canaries** — deceptive files (.txt, .docx, .xlsx) uploaded to document libraries
- **OneDrive canaries** — deceptive files (.txt, .docx, .xlsx) uploaded to personal OneDrive for Business storage
- **Interactive + scripted CLI** — guided deployment or `--non-interactive` for CI/automation
- **YAML template system** — 16 bundled templates, custom template directories supported
- **Dry-run mode** — validate and authenticate without writing anything
- **Cleanup subcommand** — deterministic removal using deployment records
- **Monitor subcommand** — poll the M365 Management Activity API for canary access events
- **Detect subcommand** — generate KQL, Splunk, or OData detection queries from deployment records
- **Verify subcommand** — confirm deployed canaries still exist via Graph API health checks
- **Graph API retry safety** — GET/DELETE retry on transient errors; POST/PUT do not auto-retry
- **Offline demo mode** — `--demo` flag for conference presentations without live tenant

## Differentiator

Unlike [Canarytokens.org](https://canarytokens.org/) (DNS/HTTP beacons) or [Thinkst Canary](https://canary.tools/) (appliance-based), Anglerfish uses no callback infrastructure. Canary artifacts are native M365 objects. Detection is powered by the Unified Audit Log that enterprises already collect — no additional infrastructure, no network egress, no token-serving endpoints.

## Supported Canary Types

| Type | Delivery | Auth | Detection event |
|------|----------|------|-----------------|
| Outlook | Draft in hidden folder, or send to Inbox | Application | `MailItemsAccessed` |
| SharePoint | File upload to an existing site folder | Application | `FileAccessed`, `FileDownloaded` |
| OneDrive | File upload to personal OneDrive for Business | Application | `FileAccessed`, `FileDownloaded` |

## Scope Warning

> **`Mail.ReadWrite` is an application-level permission that grants access to ALL mailboxes in the tenant.** Grant this permission only in dedicated security/canary tenants or ensure your organization's security team has reviewed and approved the scope. Use least-privilege: grant only the permissions required for the canary types you intend to deploy.

---

## Installation

### Prerequisites

- Python 3.10+
- Microsoft 365 tenant with E3/E5 (or equivalent with audit logging enabled)
- Azure AD (Entra ID) app registration with appropriate Graph API permissions

### Quickstart

```bash
bash scripts/quickstart.sh
```

### Manual Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

### Azure AD App Registration

See [Demo Tenant Setup Guide](docs/demo-tenant-setup.md) for step-by-step instructions including app registration, permission grants, and admin consent.

### Required Graph Permissions

| Canary type | Permission | Type |
|-------------|-----------|------|
| Outlook (draft) | `Mail.ReadWrite` | Application |
| Outlook (send) | `Mail.ReadWrite`, `Mail.Send` | Application |
| SharePoint | `Sites.ReadWrite.All`, `Files.ReadWrite.All` | Application |
| OneDrive | `Files.ReadWrite.All` | Application |
| Monitor | `ActivityFeed.Read` | Application (Office 365 Management APIs) |

### Environment Variables

```bash
export ANGLERFISH_CLIENT_ID="<your-application-client-id>"
export ANGLERFISH_TENANT_ID="<your-tenant-id-guid>"
export ANGLERFISH_APP_CREDENTIAL_MODE="secret"
export ANGLERFISH_CLIENT_SECRET="<your-client-secret>"
```

Certificate mode is also supported (`ANGLERFISH_APP_CREDENTIAL_MODE=certificate`). See `.env.example` for all options.

### Verify Installation

```bash
anglerfish --version
anglerfish --dry-run --non-interactive --canary-type outlook \
  --template "Fake Password Reset" --target test@example.com --delivery-mode draft
```

---

## Usage

### Interactive Deployment

```bash
anglerfish
```

The CLI walks through canary type selection, template choice, target configuration, and confirmation before deploying.

### Non-Interactive / Scripted Deployment

```bash
anglerfish \
  --non-interactive \
  --canary-type outlook \
  --template "Fake Wire Transfer" \
  --target victim@contoso.com \
  --delivery-mode draft \
  --output-json ./deployment-record.json

anglerfish \
  --non-interactive \
  --canary-type sharepoint \
  --template "Employee Salary Bands" \
  --target HRSite \
  --folder-path "Compensation/Restricted" \
  --filename "2026_Salary_Bands_Engineering.txt" \
  --output-json ./deployment-record.json

anglerfish \
  --non-interactive \
  --canary-type onedrive \
  --template "VPN Credentials Backup" \
  --target j.smith@contoso.com \
  --folder-path "IT/Backups" \
  --filename "VPN_Config_GlobalProtect_Backup.txt" \
  --output-json ./deployment-record.json
```

### Batch Deployment

Deploy multiple canaries from a YAML manifest:

```bash
anglerfish batch manifest.yaml --output-dir ./records/
```

Manifest format:

```yaml
defaults:
  vars:
    company_name: "Contoso Ltd"

canaries:
  - canary_type: outlook
    template: "Fake Password Reset"
    target: cfo@contoso.com
    delivery_mode: draft
    vars:
      target_name: "Jane Chen"

  - canary_type: sharepoint
    template: "Employee Salary Bands"
    target: HRSite
    folder_path: "Compensation/Restricted"
    filename: "2026_Salary_Bands_Engineering.txt"

  - canary_type: onedrive
    template: "VPN Credentials Backup"
    target: j.smith@contoso.com
    folder_path: "IT/Backups"
    filename: "VPN_Config_GlobalProtect_Backup.txt"
```

Authenticates once, deploys all entries sequentially, writes one deployment record per canary to `--output-dir`. Failures are logged and skipped — remaining canaries still deploy.

Dry run: `anglerfish batch manifest.yaml --dry-run`

Demo: `anglerfish batch manifest.yaml --demo`

### Dry Run

Validate configuration and authenticate without performing any writes:

```bash
anglerfish \
  --non-interactive \
  --dry-run \
  --canary-type sharepoint \
  --template "Employee Salary Bands" \
  --target HRSite \
  --folder-path "Compensation/Restricted" \
  --filename "2026_Salary_Bands_Engineering.txt"
```

### Listing Deployments

```bash
anglerfish list
anglerfish list --records-dir ~/.anglerfish/records
```

### Cleanup / Rollback

Use the deployment record from `--output-json`:

```bash
anglerfish cleanup ./deployment-record.json
```

Non-interactive cleanup:

```bash
anglerfish cleanup --non-interactive ./deployment-record.json
```

Deletion behavior:

| Canary type | Deletion endpoint | Result |
|-------------|-------------------|--------|
| Outlook draft | `DELETE /users/{upn}/mailFolders/{folder_id}` | Permanent (folder + draft message) |
| Outlook send | `DELETE /users/{upn}/mailFolders/inbox/messages/{id}` | Moves to Deleted Items |
| SharePoint | `DELETE /sites/{site_id}/drive/items/{item_id}` | Recycle bin behavior |
| OneDrive | `DELETE /users/{upn}/drive/items/{item_id}` | Recycle bin behavior |

### Demo Mode (Offline)

Run the CLI without a live M365 tenant — useful for conference demos or local testing:

```bash
# List pre-staged fixture records
anglerfish --demo list --records-dir examples/demo-records/

# Simulated interactive deployment (no auth, no writes)
anglerfish --demo

# Simulated cleanup
anglerfish --demo cleanup examples/demo-records/outlook-draft-record.json

# Simulated monitoring alert
anglerfish monitor --demo

# Generate detection queries from demo records
anglerfish detect examples/demo-records/outlook-draft-record.json
anglerfish detect examples/demo-records/sharepoint-upload-record.json --format splunk
```

### Monitoring

Poll the Office 365 Management Activity API for canary access events:

```bash
# Continuous monitoring (polls every 5 minutes)
anglerfish monitor --records-dir ~/.anglerfish/records

# Single poll
anglerfish monitor --records-dir ~/.anglerfish/records --once

# Custom interval, exclude your own app ID
anglerfish monitor --records-dir ~/.anglerfish/records \
  --interval 60 \
  --exclude-app-id "your-app-client-id"

# With Slack alerting
anglerfish monitor --records-dir ~/.anglerfish/records \
  --slack-webhook-url https://hooks.slack.com/services/T.../B.../xxx
```

### Detection Queries

Generate SIEM detection queries from deployment records:

```bash
# KQL (default, for Microsoft Sentinel)
anglerfish detect ./deployment-record.json

# Splunk SPL
anglerfish detect ./deployment-record.json --format splunk

# OData filter (for Management Activity API)
anglerfish detect ./deployment-record.json --format odata
```

### Canary Health Check

Verify that deployed canaries still exist:

```bash
# Check a single record
anglerfish verify ./deployment-record.json

# Check all records in default directory
anglerfish verify

# Check all records in a specific directory
anglerfish verify --records-dir ~/.anglerfish/records/

# Demo mode (simulated output)
anglerfish verify --demo
```

Exit code 0 if all canaries are OK, 1 if any are GONE or ERROR.

### Detection Setup

After deploying canaries, configure your SIEM to query the M365 Unified Audit Log for the artifact IDs stored in each deployment record. For Outlook canaries, filter on `MailItemsAccessed` events matching the `message_id` or `folder_id`. For SharePoint and OneDrive canaries, filter on `FileAccessed` events matching the `item_id`. Use `anglerfish detect` to auto-generate queries. See [threat-model.md](docs/threat-model.md) for details on audit events, latency, and filtering guidance.

### Custom Templates

Built-in templates are loaded from package data. Custom templates directory:

```bash
export ANGLERFISH_TEMPLATES_DIR="/absolute/path/to/templates"
```

Expected layout:

```text
<custom-dir>/
├── outlook/
│   └── *.yaml
├── sharepoint/
│   └── *.yaml
└── onedrive/
    └── *.yaml
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for template schema documentation.

## CLI Reference

| Flag | Description |
|------|-------------|
| `--non-interactive` | Skip prompts |
| `--canary-type` | `outlook`, `sharepoint`, or `onedrive` |
| `--template` | Template name (case-insensitive) |
| `--target` | Mailbox UPN/email (Outlook), site name (SharePoint), or UPN (OneDrive) |
| `--delivery-mode` | `draft` or `send` (Outlook only) |
| `--folder-path` | SharePoint or OneDrive destination folder path |
| `--filename` | SharePoint or OneDrive filename |
| `--var KEY=VALUE` | Template variable override (repeatable) |
| `--dry-run` | Authenticate and validate without write calls |
| `--output-json` | Write deployment record JSON |
| `--demo` | Run in offline demo mode (no auth, no API calls) |
| `monitor` | Subcommand: poll audit logs for canary access events |
| `monitor --once` | Poll once and exit |
| `monitor --interval N` | Set poll interval in seconds (default: 300) |
| `monitor --exclude-app-id ID` | Exclude app IDs from matching (repeatable) |
| `monitor --slack-webhook-url URL` | Slack incoming webhook URL for alert notifications |
| `detect <record>` | Subcommand: generate SIEM query from deployment record |
| `detect --format FMT` | Query format: `kql`, `splunk`, or `odata` (default: kql) |
| `batch <manifest>` | Subcommand: deploy multiple canaries from a YAML manifest |
| `batch --output-dir DIR` | Output directory for deployment records (default: `~/.anglerfish/records`) |
| `batch --dry-run` | Validate manifest and authenticate without deploying |
| `verify [RECORD]` | Subcommand: check deployed canaries still exist via Graph API |
| `verify --records-dir DIR` | Directory of records to verify (default: `~/.anglerfish/records`) |

## Reliability Notes

- Graph retries are side-effect-safe by default:
  - `GET` and `DELETE` retry on transient network errors, `429`, and `5xx`.
  - `POST` and `PUT` do not auto-retry unless explicitly marked safe in code.
- Deployment record writes (`--output-json`) are atomic (temp file + replace) to reduce partial-write risk.
- Deployment record reads require a JSON object with `timestamp` and `canary_type` (or legacy `type`).

## Safety Checklist

- [ ] Written authorization obtained from asset owner before deploying to production
- [ ] SOC / detection team notified of canary type, template, and target
- [ ] App registration created with least-privilege permissions
- [ ] `--output-json` path specified so the record is saved for later cleanup
- [ ] Cleanup plan documented (who, when, `anglerfish cleanup <record>`)
- [ ] Test in a non-production tenant first
- [ ] Do not commit secrets, certs, or tokens

See [threat-model.md](docs/threat-model.md) for the full deployment checklist and permissions reference.

## Validation

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
```

## License

MIT — see [LICENSE](LICENSE).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
