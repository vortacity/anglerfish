# Anglerfish — Threat Model

## What Anglerfish Detects

Anglerfish detects **unauthorized Outlook mailbox access** by planting
canary messages that generate audit events when read or opened. Detection is
entirely access-based — no network callbacks, DNS beacons, or URL tokens are used.

Threat scenarios detected:

| Scenario | Canary type | Audit event |
|----------|-------------|-------------|
| Attacker reads a compromised user's email | Outlook (draft) | `MailItemsAccessed` |
| Anglerfish sends a visible canary into the mailbox; later access to that canary is interpreted using UAL actor context to distinguish demo, authorized, or attacker activity | Outlook (send) | `MailItemsAccessed` |

### UAL Event Details

- **`MailItemsAccessed`** — fires when mail items are accessed via Graph API,
  Exchange ActiveSync, or OWA. Requires Microsoft 365 E3/E5 or equivalent
  for mailbox audit logging to be enabled.

## What Anglerfish Does NOT Detect

Anglerfish is not a general-purpose intrusion detection system. It does not
detect:

- **Network-based attacks** — port scans, lateral movement, network reconnaissance
- **Password spraying or brute force** — no authentication monitoring
- **Malware execution** — no endpoint telemetry
- **Data exfiltration** — canaries fire on access, not on download or copy
- **Access to resources where no canary was planted** — coverage is limited to
  deployed artifacts
- **Benign operator or service access without context** — expected mailbox
  access from approved tools can look like any other access unless the actor
  is understood and documented
- **Accesses below UAL ingest latency** — see Known Limitations below

## Authorization Requirements

Anglerfish requires explicit authorization before deployment. Operators must:

1. **Obtain written authorization** from the asset owner and information security
   leadership before deploying canaries in a production environment.
2. **Review applicable laws and policies** — unauthorized computer access laws
   may apply even within your own organization depending on jurisdiction.
3. **Coordinate with the SOC** so that canary alerts are properly triaged and
   not treated as real incidents requiring immediate response.
4. **Document the deployment** using `--output-json` for audit trail and cleanup
   tracking.

### Deployment Checklist

- [ ] Written authorization obtained from asset owner
- [ ] SOC / detection team notified of canary type, template, and target
- [ ] App registration created with least-privilege permissions (see below)
- [ ] `--output-json` path specified so the record is saved for later cleanup
- [ ] Cleanup plan documented (who, when, `anglerfish cleanup <record>`)

### Minimum Required Graph API Permissions

| Workflow | Permission | Type |
|----------|-----------|------|
| Outlook draft deploy, cleanup, verify, demo access | `Mail.ReadWrite` | Microsoft Graph application |
| Outlook send deploy, cleanup | `Mail.ReadWrite`, `Mail.Send` | Microsoft Graph application |
| Monitor audit-log events | `ActivityFeed.Read` | Office 365 Management APIs application |

Grant only the permissions required for the Outlook workflows you intend to run.

## Known Limitations

### UAL Ingest Latency

Microsoft does not guarantee a specific return time for Unified Audit Log
records. For core services, audit records are typically available after 60 to
90 minutes, but tenant conditions can take longer. Treat Anglerfish monitoring
as delayed audit-log correlation, not an immediate stream. See
[Microsoft audit search guidance](https://learn.microsoft.com/en-us/purview/audit-search).

For a new Office 365 Management Activity API subscription, first content blobs
can take up to 12 hours to become available. Confirm monitor setup before a
time-sensitive demo or exercise. See
[Microsoft's Management Activity API guidance](https://learn.microsoft.com/en-us/office/office-365-management-api/office-365-management-activity-api-reference).

### Shared Mailboxes May Require Additional Permissions

For Outlook canaries targeting shared mailboxes, the app registration may
require the `FullAccess` Exchange permission in addition to the Graph
`Mail.ReadWrite` application permission, depending on tenant configuration.
Test with a dedicated canary mailbox first.

### Known-Good Actor Filtering Can Hide Evidence

`--exclude-app-id` is a static allowlist for unrelated known-good actors such
as backup, DLP, or eDiscovery tooling. Never exclude the app or user used to
generate demo evidence, because excluded app and user IDs are suppressed before
alert matching.

### Coverage is Point-in-Time

Canaries cover specific Outlook messages deployed at a specific time. They do not
provide blanket coverage of all M365 resources. Rotate canaries periodically
and after suspected compromise to maintain coverage.
