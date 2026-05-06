# Black Hat Europe Demo Script: Outlook Canary UAL Correlation

Use this script for Black Hat Europe Arsenal reviewer recordings and booth demos. Keep the claim narrow: Anglerfish is a self-hosted Outlook canary tool that deploys artifacts inside Microsoft 365 and detects mailbox access through Microsoft 365 Unified Audit Log correlation.

## Reviewer Claim

Anglerfish deploys Outlook canaries inside Microsoft 365 and detects mailbox access through `MailItemsAccessed` events from the Unified Audit Log. It is open source and self-hosted, with no third-party data plane in the detection path and no DNS callback, HTTP beacon, webhook receiver, or external listener required for detection.

## Prerequisites

- Dedicated demo tenant or approved security tenant with Exchange Online and audit logging available.
- Entra app registration using application auth with `Mail.ReadWrite` and Office 365 Management APIs `ActivityFeed.Read`.
- `Mail.Send` only if the recording or booth fallback uses send mode.
- Anglerfish installed and environment variables exported for the demo app.
- Test mailbox UPN and an approved plan for generating mailbox access in that tenant.
- Verified `MailItemsAccessed` availability for the target mailbox license and mailbox auditing posture. Microsoft documents `MailItemsAccessed` as part of Audit (Standard) and Exchange mailbox auditing, enabled by default for Office 365 E3/E5 or Microsoft 365 E3/E5 users. See [Microsoft's MailItemsAccessed guidance](https://learn.microsoft.com/en-us/purview/audit-log-investigate-accounts).
- Local records directory, such as `$HOME/.anglerfish/records`.
- Optional: `jq` for showing selected record fields.

Use sanitized reference artifacts from `docs/examples/` when you need to explain record or event shape without showing raw tenant data:

- `docs/examples/outlook-draft-record.json`
- `docs/examples/outlook-send-record.json`
- `docs/examples/ual-mailitemsaccessed-event.json`

## 2-3 Minute Recording Flow

### 0:00 - State The Claim

Show the README headline and say:

> Anglerfish deploys Outlook canaries inside Microsoft 365 and detects mailbox access with native `MailItemsAccessed` audit telemetry. There is no callback server or third-party data plane in the detection path.

Keep the recording on the current release surface: Outlook deploy, list, verify, cleanup, and monitor.

### 0:20 - Deploy An Outlook Canary

Draft mode is the default operator path:

```bash
export TARGET="adele.vance@yourtenant.onmicrosoft.com"
export RECORD="$HOME/.anglerfish/records/blackhat-europe-draft.json"

anglerfish --non-interactive \
  --canary-type outlook \
  --template "Fake Password Reset" \
  --target "$TARGET" \
  --delivery-mode draft \
  --output-json "$RECORD"
```

Show the correlation fields:

```bash
jq '{timestamp, canary_type, delivery_mode, target_user, internet_message_id, folder_id, message_id}' "$RECORD"
```

If `jq` is unavailable, open the JSON record and show the same fields.

### 0:50 - Trigger Authorized Mailbox Access

For draft mode, trigger access with an approved Graph or Exchange read path because the canary lives in a hidden folder. For manual Outlook-on-the-Web interaction, use send mode or a visible test artifact.

If the same app registration triggers the access event, explain that actor attribution in the recording. Do not exclude that app from monitor matching, because excluded app or user IDs are suppressed and can hide the demo alert.

### 1:20 - Poll Unified Audit Log

Microsoft does not guarantee a specific return time for audit records. For core services, records are typically available after 60 to 90 minutes, but tenant conditions can take longer. See [Microsoft audit search guidance](https://learn.microsoft.com/en-us/purview/audit-search).

For a short recording, pre-stage and confirm the authorized access event well before recording, preferably 60 to 90+ minutes ahead, and keep sanitized fallback evidence from `docs/examples/` ready. Show both the deployment timestamp and access timestamp.

```bash
anglerfish monitor \
  --records-dir "$HOME/.anglerfish/records" \
  --once
```

Only use `--exclude-app-id` for unrelated known-good actors, such as backup, DLP, or eDiscovery tools. Never exclude the actor or app used to generate demo evidence.

The monitor alert should show:

- `Operation`: `MailItemsAccessed`
- Actor app or user where present in the audit event
- Source IP where present in the audit event
- Matched Outlook artifact, preferably `internet_message_id`
- Deployment record path

### 2:20 - Close With Boundaries

Say the limitations plainly:

> This release is Outlook-only. It depends on Microsoft 365 audit availability and ingestion latency, and audit record timing is not guaranteed. Draft canaries require application `Mail.ReadWrite`; production use requires approval and scoping decisions. Sanitized examples are included for review, but live tenant evidence should come from an authorized demo or security tenant.

## Booth Demo Procedure

1. Start with the README claim and the supported command table.
2. Run `anglerfish --demo` if the booth network or tenant access is unavailable.
3. For a live tenant, deploy a draft canary and show the local JSON record.
4. Trigger access through an approved Graph or Exchange read path for draft mode.
5. For a human interaction demo in Outlook-on-the-Web, deploy send mode instead:

```bash
export TARGET="adele.vance@yourtenant.onmicrosoft.com"
export RECORD="$HOME/.anglerfish/records/blackhat-europe-send.json"

anglerfish --non-interactive \
  --canary-type outlook \
  --template "Fake Wire Transfer" \
  --target "$TARGET" \
  --delivery-mode send \
  --output-json "$RECORD"
```

6. Poll with `anglerfish monitor --records-dir "$HOME/.anglerfish/records" --once`.
7. If unrelated known-good tenant tools create expected mailbox access, add `--exclude-app-id "<known-good-app-id>"`. Never exclude the actor or app used to generate the demo event.
8. Keep sanitized examples from `docs/examples/` ready to explain the JSON fields without exposing raw tenant data.

## Evidence Checklist

- README claim is visible.
- Deployment command is visible.
- Local deployment JSON record is visible.
- `internet_message_id`, `folder_id`, or `message_id` match key is visible.
- Trigger timestamp and authorized actor are documented.
- `MailItemsAccessed` event timestamp is visible in the monitor output or sanitized example.
- `anglerfish monitor` alert references the deployment record.
- Any `--exclude-app-id` use is explained as known-good actor filtering.
- No actor or app used to generate demo evidence is excluded.
- No DNS zone, webhook receiver, HTTP listener, or third-party callback service is shown as part of detection.

## Limitations Script

Use this wording when asked about scope:

> Anglerfish is not an immediate detection stream. It correlates against Microsoft 365 Unified Audit Log events, so latency depends on the tenant and audit ingestion. Microsoft does not guarantee audit record timing. The current release is Outlook-only. Draft mode stores the canary in a hidden folder, so manual Outlook-on-the-Web browsing is not a valid draft trigger; use an approved Graph or Exchange read path, send mode, or a visible test artifact for human interaction. `Mail.ReadWrite` is powerful and must be approved and scoped for production. The repository includes sanitized examples, not raw tenant evidence.

## Cleanup

Remove live demo artifacts after the recording or booth session:

```bash
anglerfish cleanup --non-interactive "$RECORD"
```

If both draft and send records were used, clean up each record path:

```bash
anglerfish cleanup --non-interactive "$HOME/.anglerfish/records/blackhat-europe-draft.json"
anglerfish cleanup --non-interactive "$HOME/.anglerfish/records/blackhat-europe-send.json"
```

Review the app registration after the demo and remove temporary credentials or test-only permissions that are no longer needed.
