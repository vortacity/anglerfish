<div align="center">
  <img src="docs/images/logo.png" alt="Anglerfish" width="400">
  <h1>Anglerfish</h1>
</div>

[![CI](https://github.com/vortacity/anglerfish/actions/workflows/ci.yml/badge.svg)](https://github.com/vortacity/anglerfish/actions/workflows/ci.yml)

Deploy Outlook canaries and detect Outlook access events in Microsoft 365.

Anglerfish is a Python CLI for planting deceptive Outlook messages with Microsoft Graph and detecting `MailItemsAccessed` events from the Microsoft 365 Unified Audit Log. It supports hidden-folder draft canaries, inbox send canaries, local deployment records, health checks for draft deployments, and access monitoring without external callback infrastructure.

## Demo

**Interactive deployment** (`anglerfish`):

![Interactive deployment](docs/images/interactive-deploy.gif)

**Alert detection** (`anglerfish monitor`):

![Monitor alert](docs/images/monitor-alert.gif)

## Documentation

- [Demo tenant setup guide](docs/demo-tenant-setup.md)
- [Architecture notes](docs/architecture.md)
- [Threat model](docs/threat-model.md)

> [!WARNING]
> This tool is for authorized security testing and defensive canary deployments only. Use a non-production tenant unless your organization has explicitly approved the permissions and mailbox scope involved.

## How It Works

```text
1. Deploy     anglerfish -> Microsoft Graph -> Outlook draft or inbox canary
2. Access     mailbox activity -> Microsoft 365 Unified Audit Log -> MailItemsAccessed
3. Detect     anglerfish monitor -> correlates audit event to deployment record -> alert
```

Anglerfish is intentionally narrow in this release: Outlook only, application authentication only, and one primary workflow built around deploy, list, verify, cleanup, and monitor.

## Supported Surface

| Command | Purpose |
| --- | --- |
| `anglerfish` | Interactive Outlook canary deploy |
| `anglerfish list` | List deployment records |
| `anglerfish verify` | Check active draft-mode Outlook canaries |
| `anglerfish cleanup <record>` | Remove a deployed Outlook canary |
| `anglerfish monitor` | Poll for Outlook access alerts |

Notes:
- `draft` is the default and best-supported operator path.
- `send` is supported for deploy, cleanup, list, and monitor.
- `verify` is draft-only because send-mode records do not keep a hidden folder to inspect.

## Quickstart

```bash
git clone https://github.com/vortacity/anglerfish.git
cd anglerfish
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

Anglerfish reads credentials from the process environment. It does not auto-load `.env`, so export values directly or source a file yourself before running commands.

```bash
export ANGLERFISH_TENANT_ID="..."
export ANGLERFISH_CLIENT_ID="..."
export ANGLERFISH_APP_CREDENTIAL_MODE="secret"
export ANGLERFISH_CLIENT_SECRET="..."
```

Dry-run the default Outlook workflow:

```bash
anglerfish --dry-run --non-interactive \
  --canary-type outlook \
  --template "Fake Password Reset" \
  --target adele.vance@contoso.com \
  --delivery-mode draft
```

Deploy a real canary and write a local record:

```bash
anglerfish --non-interactive \
  --canary-type outlook \
  --template "Fake Password Reset" \
  --target adele.vance@contoso.com \
  --delivery-mode draft \
  --output-json ~/.anglerfish/records/adele-password-reset.json
```

Try the product offline:

```bash
anglerfish --demo
anglerfish monitor --demo --count 2
```

For a complete Entra app registration walkthrough, see [Demo tenant setup guide](docs/demo-tenant-setup.md).

## Authentication

Application authentication is the only supported auth model in this release.

Credential selection:
- `--credential-mode secret` or `ANGLERFISH_APP_CREDENTIAL_MODE=secret`
- `--credential-mode certificate` or `ANGLERFISH_APP_CREDENTIAL_MODE=certificate`
- `auto` is also accepted and chooses whichever single credential type is configured

Secret mode:

```bash
export ANGLERFISH_TENANT_ID="<tenant-guid>"
export ANGLERFISH_CLIENT_ID="<app-client-id>"
export ANGLERFISH_APP_CREDENTIAL_MODE="secret"
export ANGLERFISH_CLIENT_SECRET="<client-secret>"
```

Certificate mode:

```bash
export ANGLERFISH_TENANT_ID="<tenant-guid>"
export ANGLERFISH_CLIENT_ID="<app-client-id>"
export ANGLERFISH_APP_CREDENTIAL_MODE="certificate"
export ANGLERFISH_CLIENT_CERT_PFX_PATH="/path/to/app-cert.pfx"
export ANGLERFISH_CLIENT_CERT_PASSPHRASE="<optional-passphrase>"
```

PEM certificate configuration is also supported. See `.env.example` for the full variable set.

## Required Permissions

| Workflow | Permission | API |
| --- | --- | --- |
| Draft deploy, cleanup, verify | `Mail.ReadWrite` | Microsoft Graph |
| Send deploy | `Mail.ReadWrite`, `Mail.Send` | Microsoft Graph |
| Monitor | `ActivityFeed.Read` | Office 365 Management Activity API |

Grant admin consent after adding the permissions. `Mail.ReadWrite` is tenant-wide mailbox access, so do not grant it casually in production.

## Templates

Bundled Outlook templates:

- `Fake Password Reset`
- `Fake Wire Transfer`
- `IT Compliance Audit`
- `Payroll Direct Deposit Update`

Custom Outlook YAML templates are supported through `ANGLERFISH_TEMPLATES_DIR`:

```bash
export ANGLERFISH_TEMPLATES_DIR="$PWD/custom-templates"
anglerfish --non-interactive \
  --canary-type outlook \
  --template "Fake Password Reset" \
  --target adele.vance@contoso.com \
  --delivery-mode draft \
  --var company_name="Contoso"
```

`--template` names are case-insensitive. Repeat `--var KEY=VALUE` to fill template variables.

## Usage

Interactive deploy:

```bash
anglerfish
```

Non-interactive draft deploy:

```bash
anglerfish --non-interactive \
  --canary-type outlook \
  --template "Fake Password Reset" \
  --target adele.vance@contoso.com \
  --delivery-mode draft \
  --output-json ~/.anglerfish/records/adele-draft.json
```

Non-interactive send deploy:

```bash
anglerfish --non-interactive \
  --canary-type outlook \
  --template "Fake Wire Transfer" \
  --target adele.vance@contoso.com \
  --delivery-mode send \
  --output-json ~/.anglerfish/records/adele-send.json
```

List records:

```bash
anglerfish list --records-dir ~/.anglerfish/records
```

Verify draft-mode records:

```bash
anglerfish verify --records-dir ~/.anglerfish/records
anglerfish verify ~/.anglerfish/records/adele-draft.json
```

Cleanup:

```bash
anglerfish cleanup --non-interactive ~/.anglerfish/records/adele-draft.json
anglerfish cleanup --non-interactive ~/.anglerfish/records/adele-send.json
```

Monitor for access:

```bash
anglerfish monitor --records-dir ~/.anglerfish/records
anglerfish monitor --once --records-dir ~/.anglerfish/records
anglerfish monitor --records-dir ~/.anglerfish/records \
  --alert-log ~/.anglerfish/alerts.jsonl \
  --slack-webhook-url https://hooks.slack.com/services/...
```

Demo mode:

```bash
anglerfish list --records-dir examples/demo-records
anglerfish cleanup --demo --non-interactive examples/demo-records/outlook-draft-record.json
anglerfish cleanup --demo --non-interactive examples/demo-records/outlook-send-record.json
anglerfish verify --demo
anglerfish monitor --demo --count 2
```

## CLI Help

```bash
anglerfish --help
anglerfish verify --help
anglerfish monitor --help
```

Those help screens are the source of truth for the current command surface. This release only supports Outlook deploy/detect workflows.
