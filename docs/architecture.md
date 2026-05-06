# Anglerfish Architecture

## Overview

Anglerfish is an Outlook-only Microsoft 365 canary CLI. It deploys Outlook canaries with Microsoft Graph, stores local deployment records, verifies draft-mode canaries, and monitors the Microsoft 365 Unified Audit Log for `MailItemsAccessed` events.

Current release scope:
- Outlook draft canaries
- Outlook send canaries
- Local record inventory
- Draft-mode verify
- Audit-log monitoring

## Layers

```text
CLI package (cli/_main.py, cli/deploy.py, cli/monitor.py)
  -> Auth (auth.py)
  -> Graph client (graph.py)
  -> Outlook deployer (deployers/outlook.py)
  -> Inventory (inventory.py)
  -> Verify (verify.py)
  -> Monitor (monitor.py, audit.py, alerts.py, state.py)
  -> Templates (templates.py, models.py)
```

## Auth Model

Only application authentication is supported.

Credential types:
- Client secret
- Certificate (PFX or PEM + thumbprint)

Graph operations and Management Activity API polling both use the same client-credentials pattern.

## Graph Client

`GraphClient` wraps `requests.Session` and provides:
- bearer auth headers
- safe retries for `GET` and `DELETE`
- explicit no-default retry for side-effecting writes
- Graph error extraction with request IDs

## Template System

Templates are Outlook-only YAML files loaded from:
1. `ANGLERFISH_TEMPLATES_DIR` if set
2. packaged Outlook templates under `src/anglerfish/templates/outlook`

Model:
- `OutlookTemplate`

Variable substitution uses `string.Template` with `${var}` placeholders.

## Deployment Records

`inventory.py` owns deployment record persistence:
- `write_deployment_record(path, record)`
- `read_deployment_record(path)`
- `update_deployment_status(path, status)`

Record guarantees:
- atomic writes with a temp file and `os.replace`
- required `timestamp`
- required `canary_type` or `type`

Outlook draft records store folder metadata for verify and cleanup. Outlook send records store the inbox message ID used for cleanup and the internet message ID used for monitoring correlation.

## Command Surface

- default command: deploy Outlook canary
- `cleanup <record>`
- `list [--records-dir DIR]`
- `monitor [--once] [--interval N] [--exclude-app-id ID] [--alert-log PATH] [--slack-webhook-url URL]`
- `verify [RECORD] [--records-dir DIR]`

Operational note:
- `verify` is draft-only because send-mode deployments do not leave a hidden folder to query after delivery.
