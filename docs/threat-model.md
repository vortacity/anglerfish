# Anglerfish — Threat Model

## What Anglerfish Detects

Anglerfish detects **unauthorized Outlook mailbox access** by planting
canary messages that generate audit events when read or opened. Detection is
entirely access-based — no network callbacks, DNS beacons, or URL tokens are used.

Threat scenarios detected:

| Scenario | Canary type | Audit event |
|----------|-------------|-------------|
| Attacker reads a compromised user's email | Outlook (draft) | `MailItemsAccessed` |
| Attacker sends canary email to victim, victim opens it | Outlook (send) | `MailItemsAccessed` |

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
- **Access by the deploying service account itself** — the operator's own Graph
  API calls may appear in the same audit log
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
| Outlook draft deploy, cleanup, verify | `Mail.ReadWrite` | Microsoft Graph application |
| Outlook send deploy, cleanup | `Mail.ReadWrite`, `Mail.Send` | Microsoft Graph application |
| Monitor audit-log events | `ActivityFeed.Read` | Office 365 Management APIs application |

Grant only the permissions required for the Outlook workflows you intend to run.

## Known Limitations

### UAL Ingest Latency (~15 minutes)

Microsoft 365 Unified Audit Log events are typically available within 15–60
minutes of the triggering action, but Microsoft does not guarantee a specific
SLA. Do not expect real-time detection. Configure your SIEM to query the UAL
on a schedule (e.g., every 15–30 minutes) and alert on canary artifact IDs.

### Shared Mailboxes May Require Additional Permissions

For Outlook canaries targeting shared mailboxes, the app registration may
require the `FullAccess` Exchange permission in addition to the Graph
`Mail.ReadWrite` application permission, depending on tenant configuration.
Test with a dedicated canary mailbox first.

### No Detection of Access by the Deploying Principal

The service account or delegated user used to deploy canaries may generate its
own `MailItemsAccessed` events during
deployment. Filter these out in your detection logic by excluding the deploying
principal's UPN or app registration object ID from canary alert rules.

### Coverage is Point-in-Time

Canaries cover specific Outlook messages deployed at a specific time. They do not
provide blanket coverage of all M365 resources. Rotate canaries periodically
and after suspected compromise to maintain coverage.
