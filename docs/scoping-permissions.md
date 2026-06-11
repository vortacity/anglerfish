# Scoping Mail.ReadWrite to Canary Mailboxes

`Mail.ReadWrite` application permission grants **tenant-wide** mailbox
read/write access by default. For a canary tool that only ever touches a
handful of mailboxes, that default is far more access than the job needs —
and it is the first thing a security review of your deployment will flag.

This guide scopes the Anglerfish app registration down to only the
mailboxes that host canaries, using
[Exchange Online RBAC for Applications](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac).

> [!IMPORTANT]
> Exchange RBAC grants are **additive** to Microsoft Entra grants — the
> effective permission is the *union* of both. A resource-scoped
> `Application Mail.ReadWrite` assignment in Exchange does nothing while an
> unscoped `Mail.ReadWrite` grant remains in Entra ID. Step 6 (removing the
> Entra grant) is what makes the scoping real. Do not skip it.

## What can and cannot be scoped

| Permission | API | Scopable? |
| --- | --- | --- |
| `Mail.ReadWrite` | Microsoft Graph | Yes — `Application Mail.ReadWrite` role |
| `Mail.Send` (send mode only) | Microsoft Graph | Yes — `Application Mail.Send` role |
| `ActivityFeed.Read` | Office 365 Management APIs | **No** — the audit feed is tenant-level by design |

The monitor's `ActivityFeed.Read` permission reads audit *metadata* for the
whole tenant; there is no per-mailbox scoping mechanism for it. The
mailbox-content permissions are where scoping matters, and they scope fully.

## Prerequisites

- The [ExchangeOnlineManagement](https://learn.microsoft.com/en-us/powershell/exchange/exchange-online-powershell-v2)
  PowerShell module (`Install-Module ExchangeOnlineManagement`).
- Membership in the **Organization Management** role group (or the Exchange
  Administrator Entra role) to create role assignments.
- The Anglerfish app registration from the
  [setup guide](demo-tenant-setup.md), with admin consent already granted.

Connect first:

```powershell
Connect-ExchangeOnline
```

## 1. Mark the canary mailboxes

Pick a recipient property to identify canary mailboxes. A custom attribute
is the simplest and avoids coupling to group membership:

```powershell
Set-Mailbox adele.vance@contoso.com -CustomAttribute10 "anglerfish-canary"
Set-Mailbox megan.bowen@contoso.com -CustomAttribute10 "anglerfish-canary"
```

A mail-enabled security group works too (use the group's *distinguished
name* with a `MemberOfGroup` filter; nested membership is **not** honored).

## 2. Create a management scope

```powershell
New-ManagementScope -Name "Anglerfish Canary Mailboxes" `
  -RecipientRestrictionFilter "CustomAttribute10 -eq 'anglerfish-canary'"
```

## 3. Register the service principal pointer in Exchange

Exchange needs a pointer to the app's Entra service principal. Take the IDs
from **Entra ID → Enterprise applications** (NOT App registrations — the
Object ID shown there is a different object):

```powershell
New-ServicePrincipal `
  -AppId  "<Application ID from Enterprise applications>" `
  -ObjectId "<Object ID from Enterprise applications>" `
  -DisplayName "Anglerfish"
```

If you prefer PowerShell, `Get-MgServicePrincipal -Filter "appId eq
'<client-id>'"` returns the right `Id`.

## 4. Assign the scoped roles

Draft-mode deployments need `Application Mail.ReadWrite`:

```powershell
New-ManagementRoleAssignment `
  -App "<Object ID from step 3>" `
  -Role "Application Mail.ReadWrite" `
  -CustomResourceScope "Anglerfish Canary Mailboxes"
```

Send-mode deployments also need `Application Mail.Send`:

```powershell
New-ManagementRoleAssignment `
  -App "<Object ID from step 3>" `
  -Role "Application Mail.Send" `
  -CustomResourceScope "Anglerfish Canary Mailboxes"
```

## 5. Test the assignment

```powershell
Test-ServicePrincipalAuthorization -Identity "Anglerfish" `
  -Resource adele.vance@contoso.com | Format-Table
```

`InScope` should be `True` for a canary mailbox and `False` for any other
mailbox you test. The test cmdlet bypasses the permission cache, so it
reflects the assignment immediately.

## 6. Remove the unscoped Entra grants

This is the step that actually constrains the app. In
**Entra ID → App registrations → your app → API permissions**, remove the
Microsoft Graph `Mail.ReadWrite` (and `Mail.Send`) application permissions,
or revoke their admin consent. Leave `ActivityFeed.Read` (Office 365
Management APIs) in place — the monitor still needs it and it cannot be
scoped.

Without this step the union rule applies: unscoped Entra grant ∪ scoped
Exchange grant = unscoped access.

## 7. Verify end to end

Permission changes propagate to Graph within roughly 30 minutes to 2 hours
(the test cmdlet in step 5 bypasses this cache; live API calls do not).
After waiting:

```bash
# Should succeed against a canary mailbox:
anglerfish --dry-run --non-interactive --canary-type outlook \
  --template "Fake Password Reset" --target adele.vance@contoso.com \
  --delivery-mode draft

# Should fail with 403 against a non-canary mailbox:
anglerfish --dry-run --non-interactive --canary-type outlook \
  --template "Fake Password Reset" --target someone.else@contoso.com \
  --delivery-mode draft
```

A 403 on the second command is the desired outcome — it proves the blast
radius of a leaked Anglerfish credential is now the canary mailboxes, not
the tenant.

## Ongoing operations

- New canary mailboxes only need the marker attribute from step 1; the
  scope filter picks them up automatically.
- Audit the assignment periodically:
  `Get-ManagementRoleAssignment -RoleAssignee "Anglerfish"` and re-run
  step 5 against a non-canary mailbox.
- If you rotate to a new app registration, repeat steps 3–6 for the new
  service principal and remove the old one
  (`Remove-ServicePrincipal -Identity "Anglerfish"`).
