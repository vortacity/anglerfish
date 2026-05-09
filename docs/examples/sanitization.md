# Evidence Sanitization Protocol

Never commit raw real-tenant artifacts.

1. Export the deployment record or UAL event outside the repository.
2. Replace tenant identifiers, UPNs, SIDs, mailbox GUIDs, app IDs, client IPs, session IDs, connection IDs, server names, and message IDs with stable placeholders.
3. Preserve the shape of the event and the correlation fields, including `canary_id`, `folder_id`, `message_id`, `inbox_message_id`, and `internet_message_id`.
4. Run `git diff` before committing.

Use these placeholders:

- tenant: `contoso.onmicrosoft.com`
- GUID: `00000000-0000-0000-0000-000000000001`
- source IP: `203.0.113.42`
- user: `adele.vance@contoso.onmicrosoft.com`
- actor: `attacker@contoso.onmicrosoft.com`
- canary ID: `af-demo-001`
