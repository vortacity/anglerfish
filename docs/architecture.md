# Anglerfish: Architecture

## Overview

Anglerfish is a Python CLI that provisions Microsoft 365 canary artifacts via Microsoft Graph.

Current release scope:
- Outlook canaries
- SharePoint canaries
- OneDrive canaries

## Layers

```text
CLI (cli.py)
  -> Auth (auth.py)
  -> Graph client (graph.py)
  -> Deployer (deployers/outlook.py, deployers/sharepoint.py, deployers/onedrive.py)
  -> Batch orchestrator (batch.py)
  -> Monitor (monitor.py, audit.py, alerts.py, state.py)
  -> Verify (verify.py)
  -> Dashboard (dashboard.py)
```

## Auth Model

Both supported canary types use **application authentication** via MSAL `ConfidentialClientApplication`.

Credential types:
- Client secret
- Certificate (PFX or PEM + thumbprint)

## Graph Client

`GraphClient` wraps `requests.Session` and provides:
- Bearer auth headers
- side-effect-safe retries by default:
  - `GET`/`DELETE`: retries on network errors, `429`, and `5xx`
  - `POST`/`PUT`: no automatic retries unless explicitly marked safe
- Graph error extraction (including request IDs)

## Template System

Templates are YAML files loaded from:
1. `ANGLERFISH_TEMPLATES_DIR` (if set)
2. packaged templates (`src/anglerfish/templates/...`)

Template models:
- `OutlookTemplate`
- `SharePointTemplate`
- `OneDriveTemplate`

Variable substitution uses `string.Template` (`${var}`).

## Deployment Records

`inventory.py` handles record files:
- `write_deployment_record(path, record)`
- `read_deployment_record(path)`
- `update_deployment_status(path, status)`

Record guarantees:
- writes are atomic (temp file + `os.replace`)
- reads enforce required schema keys (`timestamp` and `canary_type` or `type`)

Records are used by:
- `cleanup` (deterministic removal)
- `list` (inventory view)
- `verify` (health check against Graph API)

## CLI Subcommands

- default command: deploy
- `cleanup <record>`
- `list [--records-dir DIR]`
- `monitor [--once] [--interval N] [--exclude-app-id ID] [--slack-webhook-url URL]` (poll audit logs for canary access events)
- `batch <manifest> [--output-dir DIR] [--dry-run]` (deploy multiple canaries from a YAML manifest)
- `verify [RECORD] [--records-dir DIR]` (health check deployed canaries via Graph API)
- `dashboard [--demo] [--poll-interval N] [--verify-interval N]` (live TUI, Textual app)
