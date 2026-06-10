# Troubleshooting

This page collects common symptoms and fixes when running Anglerfish
against a Microsoft 365 demo tenant.

> **Tip:** UAL typically takes 60–90 minutes to show activity,
> and up to 12 hours for a brand-new subscription.

---

## Monitor shows nothing after demo-access

**Likely cause:** UAL ingestion latency.

| Situation | Typical delay |
|---|---|
| Existing subscription | 60–90 minutes |
| Brand-new subscription | Up to 12 hours |
| First poll after monitor starts | May return empty — normal |

**Fix:** Wait the expected time then re-run `monitor`.

---

## Auth succeeds but deploy returns 403

**Symptom:** `GraphApiError: 403 Forbidden`

**Likely cause:** Missing Graph admin consent.

**Fix:** Re-check permissions for your selected workflow, then
grant admin consent again in the Azure portal.

---

## Authentication errors

### `AuthenticationError: AADSTS7000215`

**Likely cause:** Invalid client secret.

**Fix:** Regenerate the secret in Azure and update
`ANGLERFISH_CLIENT_SECRET`.

---

### `AuthenticationError: No application credential configured`

**Likely cause:** Secret or certificate environment variables missing.

**Fix:** Set `ANGLERFISH_APP_CREDENTIAL_MODE` correctly.

---

## Mailbox not found

**Symptom:** `GraphApiError: 404 Not Found` on mailbox

**Likely cause:** Wrong UPN or mailbox not licensed.

**Fix:** Verify the user exists and has an Exchange Online license.

---

## Monitor fails to authenticate

**Symptom:** `monitor` fails to authenticate

**Likely cause:** `ActivityFeed.Read` permission not granted.

**Fix:** Add the Office 365 Management API permission and grant
admin consent in the Azure portal.

---

## verify returns an error for a send record

**Likely cause:** Expected behavior.

**Note:** `verify` only supports draft-mode Outlook records.

---

## Still stuck?

- Re-read [Demo Tenant Setup](demo-tenant-setup.md)
- Check all environment variables in `.env.example` are set
- Open an issue with the exact error message
