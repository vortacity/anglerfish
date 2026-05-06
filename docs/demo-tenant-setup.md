# Demo Tenant Setup Guide

This guide walks through setting up a safe Microsoft 365 test environment for Anglerfish demos and development. The primary demo path is Outlook draft deployment plus `MailItemsAccessed` correlation from the Unified Audit Log.

---

## 1. Get a Microsoft 365 Developer Tenant

If you don't already have a test tenant:

1. Go to the [Microsoft 365 Developer Program](https://developer.microsoft.com/en-us/microsoft-365/dev-program)
2. Sign up (free) and provision a developer sandbox tenant
3. The sandbox includes 25 E5 licenses, sufficient for all Anglerfish features
4. Note your tenant domain (e.g., `yourtenant.onmicrosoft.com`)

If you have an existing test/dev tenant with E3 or E5 licenses, that works too. **Never use a production tenant for demos.**

---

## 2. Create an Azure AD (Entra ID) App Registration

1. Sign in to the [Azure Portal](https://portal.azure.com) with your test tenant admin account
2. Navigate to **Microsoft Entra ID** > **App registrations** > **New registration**
3. Settings:
   - **Name:** `Anglerfish Demo`
   - **Supported account types:** Accounts in this organizational directory only (single tenant)
   - **Redirect URI:** leave blank (not needed for application auth)
4. Click **Register**
5. Note the **Application (client) ID** and **Directory (tenant) ID** from the Overview page

---

## 3. Create a Client Secret

1. In your app registration, go to **Certificates & secrets** > **Client secrets** > **New client secret**
2. Description: `anglerfish-demo`
3. Expiry: 6 months (or shorter for conference-only use)
4. Click **Add** and **copy the secret value immediately** (it won't be shown again)

---

## 4. Grant API Permissions

1. In your app registration, go to **API permissions** > **Add a permission**.
2. Add the following permissions based on the demo path you need:

### Primary Outlook Draft Demo

Under **Microsoft Graph** > **Application permissions**:

| Permission | Required for |
|-----------|-------------|
| `Mail.ReadWrite` | Create and verify hidden-folder draft canaries |

Under **Office 365 Management APIs** > **Application permissions**:

| Permission | Required for |
|-----------|-------------|
| `ActivityFeed.Read` | Poll Unified Audit Log events with `anglerfish monitor` |

### Optional Outlook Send Mode

| Permission | Required for |
|-----------|-------------|
| `Mail.Send` | Send mode only |

### Optional File Canaries

| Permission | Required for |
|-----------|-------------|
| `Sites.ReadWrite.All` | SharePoint site discovery and file upload |
| `Files.ReadWrite.All` | SharePoint or OneDrive file upload |

3. Click **Add permissions**

### Scope Warning

> **`Mail.ReadWrite` is an application-level permission that grants read/write access to ALL mailboxes in the tenant.** This is acceptable in a dedicated demo tenant but requires careful review in any shared environment. Never grant this in a production tenant without explicit security team approval.

---

## 5. Grant Admin Consent

1. Still on the **API permissions** page, click **Grant admin consent for [your tenant]**
2. Confirm by clicking **Yes**
3. Verify all permissions show a green checkmark under "Status"

Admin consent requires the Global Administrator role. In a developer sandbox, your account already has this role.

---

## 6. Set Up Test Mailbox

### Test Mailbox

Your developer tenant includes pre-provisioned user accounts. Pick one as your canary target:

1. Go to [Microsoft 365 Admin Center](https://admin.microsoft.com) > **Users** > **Active users**
2. Note a user's UPN (e.g., `adele.vance@yourtenant.onmicrosoft.com`)
3. Ensure the user has an Exchange Online license assigned (included in E5)

### Optional SharePoint Site

This is not needed for the primary Outlook demo. If you also want to exercise the secondary file-canary path:

1. Go to [SharePoint Admin Center](https://yourtenant-admin.sharepoint.com)
2. Create a new team site (or use an existing one):
   - **Site name:** `DemoCanaryFiles`
   - **Privacy:** Private
3. Create a document library folder for canary files (e.g., `HR/Restricted`)

---

## 7. Configure Environment Variables

```bash
export ANGLERFISH_CLIENT_ID="<application-client-id-from-step-2>"
export ANGLERFISH_TENANT_ID="<directory-tenant-id-from-step-2>"
export ANGLERFISH_APP_CREDENTIAL_MODE="secret"
export ANGLERFISH_CLIENT_SECRET="<client-secret-from-step-3>"
```

Or copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
# Edit .env with your values
# Then source it:
set -a; source .env; set +a
```

---

## 8. Verify the Setup

```bash
# Check version
anglerfish --version

# Dry run: authenticates and validates without writing
anglerfish --dry-run --non-interactive \
  --canary-type outlook \
  --template "Fake Password Reset" \
  --target adele.vance@yourtenant.onmicrosoft.com \
  --delivery-mode draft
```

If the dry run succeeds, your app registration, permissions, and credentials are all configured correctly.

---

## 9. First Outlook Draft Canary Deployment

```bash
anglerfish --non-interactive \
  --canary-type outlook \
  --template "Fake Password Reset" \
  --target adele.vance@yourtenant.onmicrosoft.com \
  --delivery-mode draft \
  --output-json ~/.anglerfish/records/first-test.json
```

Verify the deployment:

```bash
anglerfish list
```

For draft-mode canaries, you can also verify that the hidden folder and draft still exist:

```bash
anglerfish verify ~/.anglerfish/records/first-test.json
```

---

## 10. Live Audit-Log Correlation Demo

This is the reviewer-facing evidence path:

1. Record the deployment timestamp and `internet_message_id` from `~/.anglerfish/records/first-test.json`.
2. Trigger an authorized read of the deployed Outlook message from the target mailbox. For draft mode, use an approved Graph or Exchange read path that touches the hidden folder/message; the folder is intentionally hidden from normal Outlook navigation.
3. Wait for Unified Audit Log ingestion. This commonly takes 15-60 minutes.
4. Poll for correlation:

```bash
anglerfish monitor \
  --records-dir ~/.anglerfish/records \
  --once \
  --exclude-app-id "$ANGLERFISH_CLIENT_ID"
```

The evidence to capture in a 2-3 minute demo video:

- Deployment command and saved record path
- Deployment timestamp and Outlook `internet_message_id`
- Trigger/access timestamp
- `MailItemsAccessed` event timestamp from UAL
- Anglerfish alert showing the record match

Clean up when done:

```bash
anglerfish cleanup ~/.anglerfish/records/first-test.json
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `AuthenticationError: AADSTS7000215` | Invalid client secret | Regenerate secret in Azure Portal |
| `AuthenticationError: AADSTS700016` | Wrong client ID | Verify app registration client ID |
| `GraphApiError: 403 Forbidden` | Missing admin consent | Grant admin consent in API permissions |
| `GraphApiError: 404 Not Found` on mailbox | User doesn't exist or no Exchange license | Verify UPN and license assignment |
| `monitor` cannot list audit content | Missing `ActivityFeed.Read` or inactive audit subscription | Add Office 365 Management APIs permission, grant admin consent, then rerun monitor |
| `GraphApiError: 403` on SharePoint | Missing `Sites.ReadWrite.All` | Add permission and re-grant admin consent |

---

## Cleanup After Demo

1. Remove deployed canaries: `anglerfish cleanup <record.json>` for each record
2. Optionally delete the app registration in Azure Portal
3. Rotate or delete the client secret
4. Developer sandbox tenants auto-renew; no action needed unless you want to deprovision
