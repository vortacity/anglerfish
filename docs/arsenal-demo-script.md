# Arsenal Demo Script: Outlook Draft Canary

Use this script for SecTor 2026 Arsenal and Black Hat Europe reviewer recordings. The goal is to prove live Microsoft 365 audit-log correlation, not only offline simulation.

## Reviewer Claim

Anglerfish deploys Outlook canaries inside Microsoft 365 and detects mailbox access through Unified Audit Log events, without DNS callbacks, HTTP beacons, or external listener infrastructure.

## Prerequisites

- Dedicated Microsoft 365 demo tenant with audit logging enabled
- App registration with `Mail.ReadWrite` and Office 365 Management APIs `ActivityFeed.Read`
- Test mailbox UPN
- Anglerfish installed and environment variables exported
- Authorization to generate and show audit events in the demo tenant

## Two-Minute Flow

### 0:00 - State The Problem

Show the README headline and say the narrow claim:

> Outlook canaries, native M365 audit telemetry, no callback infrastructure.

Keep the recording focused on the current Outlook-only release surface: deploy, list, verify, cleanup, and monitor.

### 0:20 - Deploy Outlook Draft Canary

```bash
export TARGET="adele.vance@yourtenant.onmicrosoft.com"
export RECORD="$HOME/.anglerfish/records/arsenal-outlook-draft.json"

anglerfish --non-interactive \
  --canary-type outlook \
  --template "Fake Password Reset" \
  --target "$TARGET" \
  --delivery-mode draft \
  --output-json "$RECORD"
```

Show the record fields that will be used for correlation:

```bash
jq '{timestamp, canary_type, delivery_mode, target_user, internet_message_id, folder_id, message_id}' "$RECORD"
```

If `jq` is not installed, open the JSON record and show the same fields.

### 0:50 - Trigger Authorized Mailbox Access

Trigger a controlled read of the deployed Outlook message from the target mailbox. For draft mode, use an approved Graph or Exchange read path that touches the hidden folder/message because the folder is intentionally hidden from normal Outlook navigation.

Capture the trigger timestamp and actor. If you use the same app registration for the trigger, mention that the app ID must be filtered or the actor attribution will reflect that application.

### 1:20 - Poll Unified Audit Log

Unified Audit Log ingestion is not immediate. If the recording needs to stay under three minutes, pre-stage the access event 15-60 minutes before recording and show the deployment/access timestamps clearly.

```bash
anglerfish monitor \
  --records-dir "$HOME/.anglerfish/records" \
  --once \
  --exclude-app-id "$ANGLERFISH_CLIENT_ID"
```

The alert should show:

- `Operation`: `MailItemsAccessed`
- Accessed user or app principal
- Source IP if present in the event
- Matched Outlook artifact, preferably `internet_message_id`
- Deployment record path

### 2:00 - Close With Limitations

State these plainly:

- Unified Audit Log latency is usually 15-60 minutes.
- Live detection depends on M365 audit availability, tenant licensing, and `ActivityFeed.Read`.
- Outlook draft deployment requires broad application-level `Mail.ReadWrite`; use a dedicated demo tenant or approved security tenant.
- Anglerfish is for authorized defensive testing and canary deployments only.

## Evidence Checklist

- Deployment command is visible.
- Deployment JSON record is visible.
- `internet_message_id` or folder match key is visible.
- Trigger/access timestamp is visible.
- `MailItemsAccessed` event timestamp is visible.
- `anglerfish monitor` alert is visible and references the deployment record.
- No external listener, webhook receiver, DNS zone, or callback server is shown because none is required for detection.

## Cleanup

```bash
anglerfish cleanup --non-interactive "$RECORD"
```
