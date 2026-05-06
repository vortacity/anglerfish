# Demo Tenant Setup Guide

This guide sets up a safe Microsoft 365 tenant for Anglerfish's Outlook-only MVP.

## 1. Provision a Test Tenant

1. Join the [Microsoft 365 Developer Program](https://developer.microsoft.com/en-us/microsoft-365/dev-program) or use an existing non-production tenant.
2. Confirm you have Exchange Online and audit logging available.
3. Record the tenant domain, such as `contoso.onmicrosoft.com`.

Production use requires formal approval and explicit scoping decisions for mailbox access.

## 2. Create an Entra App Registration

1. Open the [Azure Portal](https://portal.azure.com).
2. Go to **Microsoft Entra ID** -> **App registrations** -> **New registration**.
3. Use a single-tenant app and leave redirect URIs blank.
4. Record the **Application (client) ID** and **Directory (tenant) ID**.

Anglerfish only supports application auth in this release. Delegated or device-code flows are out of scope.

## 3. Add a Credential

Choose one credential type.

Client secret:
1. Go to **Certificates & secrets** -> **Client secrets**.
2. Create a new secret.
3. Copy the secret value immediately.

Certificate:
1. Upload a certificate under **Certificates & secrets** -> **Certificates**.
2. Keep the PFX or PEM material available on the machine where Anglerfish will run.
3. Record the thumbprint if you are using PEM files.

## 4. Grant Permissions

Add the following application permissions.

Microsoft Graph:

| Permission | Required for |
| --- | --- |
| `Mail.ReadWrite` | Draft deploy, cleanup, verify, and send deploy |
| `Mail.Send` | Send deploy only |

Office 365 Management APIs:

| Permission | Required for |
| --- | --- |
| `ActivityFeed.Read` | `anglerfish monitor` |

After adding permissions, grant admin consent.

Scope warning:

> `Mail.ReadWrite` application permission grants tenant-wide mailbox write access by default. Production use requires formal approval and explicit scoping decisions. Operators can use Exchange Online RBAC for Applications to scope access to selected mailboxes, but must ensure unscoped Microsoft Entra grants do not remain in place.

## 5. Pick a Test Mailbox

1. Open the [Microsoft 365 Admin Center](https://admin.microsoft.com).
2. Go to **Users** -> **Active users**.
3. Choose a mailbox-enabled user and note the UPN.
4. Confirm the user has an Exchange Online license.
5. Verify the target mailbox license and mailbox auditing posture support `MailItemsAccessed`.

Microsoft documents `MailItemsAccessed` as part of Audit (Standard) and Exchange mailbox auditing, enabled by default for users assigned Office 365 E3/E5 or Microsoft 365 E3/E5. Do not assume the same posture for every license; verify the target mailbox before using it for a demo. See [Microsoft's MailItemsAccessed guidance](https://learn.microsoft.com/en-us/purview/audit-log-investigate-accounts).

Draft mode creates a hidden folder in that mailbox. Send mode delivers directly to the Inbox.

## 6. Export Environment Variables

Secret mode:

```bash
export ANGLERFISH_TENANT_ID="<tenant-guid>"
export ANGLERFISH_CLIENT_ID="<app-client-id>"
export ANGLERFISH_APP_CREDENTIAL_MODE="secret"
export ANGLERFISH_CLIENT_SECRET="<client-secret>"
```

Certificate mode with a PFX:

```bash
export ANGLERFISH_TENANT_ID="<tenant-guid>"
export ANGLERFISH_CLIENT_ID="<app-client-id>"
export ANGLERFISH_APP_CREDENTIAL_MODE="certificate"
export ANGLERFISH_CLIENT_CERT_PFX_PATH="/path/to/app-cert.pfx"
export ANGLERFISH_CLIENT_CERT_PASSPHRASE="<optional-passphrase>"
```

Anglerfish does not auto-load `.env`. Export variables directly or source a file yourself.

## 7. Verify the Setup

Check the CLI first:

```bash
anglerfish --version
anglerfish --help
```

Then run a dry-run draft deployment:

```bash
anglerfish --dry-run --non-interactive \
  --canary-type outlook \
  --template "Fake Password Reset" \
  --target adele.vance@contoso.com \
  --delivery-mode draft
```

If that succeeds, the CLI configuration and authentication flow are valid. A real deploy verifies mailbox write access.

## 8. Deploy Your First Canary

Draft mode:

```bash
anglerfish --non-interactive \
  --canary-type outlook \
  --template "Fake Password Reset" \
  --target adele.vance@contoso.com \
  --delivery-mode draft \
  --output-json ~/.anglerfish/records/adele-draft.json
```

Send mode:

```bash
anglerfish --non-interactive \
  --canary-type outlook \
  --template "Fake Wire Transfer" \
  --target adele.vance@contoso.com \
  --delivery-mode send \
  --output-json ~/.anglerfish/records/adele-send.json
```

Review the local record inventory:

```bash
anglerfish list --records-dir ~/.anglerfish/records
```

## 9. Validate the Operator Loop

Verify draft-mode deployments:

```bash
anglerfish verify ~/.anglerfish/records/adele-draft.json
```

Run the monitor:

```bash
anglerfish monitor --records-dir ~/.anglerfish/records
```

For a new Office 365 Management Activity API subscription, run and confirm monitor setup well before the demo, preferably the day before. Microsoft notes that first content blobs for a new subscription can take up to 12 hours to become available. See [Microsoft's Management Activity API guidance](https://learn.microsoft.com/en-us/office/office-365-management-api/office-365-management-activity-api-reference).

If the tenant has known-good mailbox access from backup, DLP, or eDiscovery tooling, exclude those app principals from matches:

```bash
anglerfish monitor --exclude-app-id "<known-good-app-id>"
```

`--exclude-app-id` is a static allowlist. Use it only for unrelated actors whose mailbox access is expected and approved for the demo tenant. Never exclude the actor or app used to generate demo evidence.

Clean up when done:

```bash
anglerfish cleanup --non-interactive ~/.anglerfish/records/adele-draft.json
anglerfish cleanup --non-interactive ~/.anglerfish/records/adele-send.json
```

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `AuthenticationError: AADSTS7000215` | Invalid client secret | Regenerate the secret and update `ANGLERFISH_CLIENT_SECRET` |
| `AuthenticationError: No application credential configured` | Secret or certificate env vars missing | Export one supported credential set and set `ANGLERFISH_APP_CREDENTIAL_MODE` correctly |
| `GraphApiError: 403 Forbidden` | Missing Graph admin consent | Re-check `Mail.ReadWrite` and `Mail.Send`, then grant consent again |
| `GraphApiError: 404 Not Found` on mailbox | Wrong UPN or mailbox not licensed | Verify the user and Exchange Online license |
| `monitor` fails to authenticate | `ActivityFeed.Read` not granted | Add the Office 365 Management API permission and grant consent |
| `verify` returns an error for a send record | Expected behavior | `verify` only supports draft-mode Outlook records |
