# Privacy and Data Handling

Anglerfish detects mailbox access by correlating audit events that
identify *who* touched a canary. That makes its alert data **workplace
monitoring data** in many jurisdictions. This page enumerates exactly what
is collected, where it flows, and what an operator is responsible for.

## What Anglerfish collects

**Alert data** (only when an audit event matches a deployed canary):

| Data | Source | Personal data? |
| --- | --- | --- |
| Accessing user (UPN or UserKey) | UAL event `UserId`/`UserKey` | Yes |
| Source IP address | UAL event `ClientIP` | Yes |
| Client/user-agent string | UAL event `ClientInfoString` | Potentially |
| Event timestamp and operation | UAL event | No |
| Matched canary template, artifact ID, record path | Local record | No |

**Deployment records** contain the target mailbox UPN, artifact IDs, and
folder names for every planted canary.

**Monitor state and heartbeat** contain timestamps, counters, and audit
event IDs — no user identities.

Anglerfish does **not** read mailbox content during monitoring; the
Management Activity API feed it consumes is audit metadata. The only
mailbox content it ever writes or reads is the canary message itself.

## Where the data flows

All flows are operator-configured; there is no telemetry, no vendor
backend, and nothing leaves your control unless you send it somewhere:

1. **Console output** — alert details rendered to the terminal (suppress
   with `--no-console`).
2. **Alert log** (`--alert-log`) — JSONL on local disk, written `0600`
   inside a `0700` directory. Schema in the
   [monitor reference](monitoring.md#alert-log).
3. **Slack / Microsoft Teams webhooks** (`--slack-webhook-url`,
   `--teams-webhook-url`) — the full alert, including the accessing
   user's UPN and IP, is POSTed to the chat tool. Sending
   employee-identifying data into a chat channel may itself require
   privacy review in your organization.
4. **Generic webhook** (`--webhook-url`) — the full alert as JSON to an
   endpoint you control (SIEM/SOAR collector). Sign bodies with
   `ANGLERFISH_WEBHOOK_HMAC_SECRET` so the receiver can authenticate
   them.

That self-contained design is deliberate: compared to SaaS canary
platforms, no third party ever sees who accessed what in your tenant.

## Operator responsibilities

- **Legal basis.** Recording which employee account accessed a mailbox is
  employee monitoring under GDPR and similar regimes, and may require
  works-council consultation, a DPIA, or policy disclosure depending on
  jurisdiction. Obtain legal/HR sign-off as part of the authorization the
  [threat model](threat-model.md#authorization-requirements) already
  requires. Note that the accessing identity may also be an *attacker
  using* an employee's account — treat alert data with incident-response
  confidentiality either way.
- **Retention.** Anglerfish never deletes alert data. Set a retention
  period consistent with your monitoring policy and rotate/prune the
  alert log accordingly (one self-contained JSON object per line).
- **Access control.** Alert logs and deployment records live under
  `~/.anglerfish` with owner-only permissions. Keep them on an
  access-controlled host (see
  [operator workstation](threat-model.md#operator-workstation-and-local-artifacts))
  and include them in your data-subject-request and deletion procedures
  if your policies require it.
- **Microsoft's processing.** The underlying audit events exist in the
  Unified Audit Log regardless of Anglerfish; Anglerfish adds no new
  collection in the tenant, it correlates what mailbox auditing already
  records.
