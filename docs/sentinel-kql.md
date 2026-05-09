# Sentinel KQL Validation

Use this query as a reviewer or operator cross-check when Microsoft 365 audit logs are connected to Microsoft Sentinel.

Replace the example `internetMessageId` values with values from Anglerfish deployment records.

```kusto
let AnglerfishMessageIds = dynamic([
  "<canary-fake-password-reset-001@contoso.onmicrosoft.com>",
  "<canary-fake-password-reset-002@contoso.onmicrosoft.com>"
]);
OfficeActivity
| where OfficeWorkload == "Exchange"
| where Operation == "MailItemsAccessed"
| extend FoldersDynamic = todynamic(Folders)
| mv-expand Folder = FoldersDynamic
| mv-expand Item = todynamic(Folder.FolderItems)
| extend InternetMessageId = tostring(Item.InternetMessageId)
| where InternetMessageId in (AnglerfishMessageIds)
| project TimeGenerated, UserId, ClientIP, ClientInfoString, InternetMessageId, FolderPath=tostring(Folder.Path), Id
| order by TimeGenerated desc
```

If your connector stores raw audit events in a custom table, keep the same matching logic: filter to `Operation == "MailItemsAccessed"`, expand `Folders[].FolderItems[]`, and match `InternetMessageId` against the values in Anglerfish records.
