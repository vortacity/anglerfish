# Monitor Operations Reference

This page documents the contracts an operator (or an external watchdog)
can rely on when running `anglerfish monitor` unattended: the heartbeat
file, the state file, the alert log, the polling mechanics, and the scale
characteristics. For first-time setup see the
[setup guide](demo-tenant-setup.md); for running it as a service see the
[production deployment guide](production-deployment.md).

## Poll mechanics

Each cycle (default `--interval 300` seconds) the monitor:

1. Lists available Unified Audit Log content blobs for every subscribed
   content type (`Audit.Exchange` for Outlook canaries) between the
   persisted watermark and now, in **windows of at most 24 hours** (the
   Management Activity API maximum per request).
2. Fetches each blob and matches every event against the deployed canary
   records (internet message ID first, then folder ID / folder name).
   `MailItemsAccessed` events produce *access* alerts; `HardDelete`,
   `SoftDelete`, `MoveToDeletedItems`, `Move`, and `Update` against a
   canary item produce *tamper* alerts.
3. Dispatches alerts for matches, deduplicating on audit event IDs it has
   already seen.
4. Advances the watermark — **only past windows that were ingested
   completely**. If any list or fetch call fails mid-window, the watermark
   stays put and the window is re-polled next cycle; seen-ID dedup keeps
   re-polling from re-alerting.

Two latency facts shape everything above (see the
[threat model](threat-model.md#ual-ingest-latency)): UAL records typically
land 60–90 minutes after the access, and the API retains content for
roughly **7 days**. Monitor downtime longer than a day is recovered by
walking the backlog in 24-hour windows; downtime longer than the retention
window is reported as unrecoverable rather than silently skipped.

## Heartbeat file

Written after every poll cycle (best-effort) to
`~/.anglerfish/monitor-heartbeat.json` by default:

```json
{
  "last_poll": "2026-06-10T14:05:03.812345+00:00",
  "status": "healthy",
  "canaries": 4,
  "alerts_this_session": 0
}
```

- `status` is `"healthy"` when the last cycle ingested its full window, and
  `"degraded"` when any part of the window could not be ingested (API
  errors, throttling, interrupt). A degraded monitor is a **blind**
  monitor for the affected range — the range will be re-polled, but a
  watchdog should alert if `degraded` persists across cycles.
- A watchdog should also alert when `last_poll` is older than roughly
  twice the poll interval: the process is hung, dead, or unable to write.

Example check:

```bash
jq -e --arg now "$(date -u +%s)" \
  '.status == "healthy" and (($now | tonumber) - (.last_poll | sub("\\.[0-9]+"; "") | fromdate)) < 900' \
  ~/.anglerfish/monitor-heartbeat.json
```

## State file

`~/.anglerfish/monitor-state.json` by default (`--state-file` /
`ANGLERFISH_MONITOR_STATE_FILE` to override). It persists:

- `last_poll_end` — the watermark. Resuming the monitor continues from
  here, which is how restarts avoid losing events.
- `seen_ids` — audit event IDs already processed (bounded at 50,000,
  oldest evicted first), used to suppress duplicate alerts when a window
  is re-polled.
- `total_polls` / `total_alerts` / `started_at` — counters.

**Safe to delete?** Yes, with two consequences: the watermark resets (a
fresh start looks back 1 hour, so older un-ingested events are skipped)
and the dedup set resets (events re-served by the API within the retention
window can alert again). Delete it when you deliberately want a clean
slate, not to "fix" a stuck monitor — a stuck watermark means ingestion is
failing, and the cause is in the console/heartbeat output.

## Alert log

With `--alert-log` (or `ANGLERFISH_MONITOR_ALERT_LOG`) each alert is
appended as one JSON object per line, `0600` permissions:

| Field | Meaning |
| --- | --- |
| `category` | `access` (canary read) or `tamper` (canary deleted/moved/modified) |
| `canary_type` | Record type that matched (`outlook`) |
| `template_name` | Template of the matched canary |
| `artifact_label` | What matched: `internet_message_id: …`, `folder_id: …`, or `folder: …` |
| `accessed_by` | UPN (or UserKey) of the accessing principal, from the audit event |
| `source_ip` | Client IP from the audit event |
| `timestamp` | Audit event creation time |
| `operation` | UAL operation (`MailItemsAccessed`) |
| `client_info` | Client/user-agent string from the audit event |
| `record_path` | Local deployment record that matched |

`accessed_by`, `source_ip`, and `client_info` are personal data — see
[privacy and data handling](privacy.md). The log grows without bound;
rotate or prune it on your own schedule (each line is self-contained, so
`logrotate` with `copytruncate` works).

## Alert channels

Every alert fans out to all configured channels independently (one failing
channel never blocks another):

| Channel | Configuration | Notes |
| --- | --- | --- |
| Console | default; suppress with `--no-console` | Rich panel, actor-influenced fields escaped |
| JSONL file | `--alert-log` / `ANGLERFISH_MONITOR_ALERT_LOG` | Schema above, `0600` |
| Slack | `--slack-webhook-url` / `ANGLERFISH_SLACK_WEBHOOK_URL` | Block Kit; HTTPS required |
| Microsoft Teams | `--teams-webhook-url` / `ANGLERFISH_TEAMS_WEBHOOK_URL` | Adaptive Card to a Teams workflow (Power Automate) webhook; HTTPS required |
| Generic webhook | `--webhook-url` / `ANGLERFISH_WEBHOOK_URL` | JSON POST of the alert (`schema_version: 1`); HTTPS required |

The generic webhook body can be authenticated: set
`ANGLERFISH_WEBHOOK_HMAC_SECRET` and each request carries
`X-Anglerfish-Signature: sha256=<hex>` — the HMAC-SHA256 of the raw body
under that secret. Receivers should verify it before trusting the alert.
Webhook URLs are bearer secrets; Anglerfish never logs them, and neither
should your shell history (prefer the environment variables).

## Scale characteristics

Be aware of what the Management Activity API does and does not offer:

- **There is no server-side mailbox or operation filter.** The monitor
  subscribes to the tenant-wide `Audit.Exchange` feed and downloads every
  Exchange audit blob in the window, then filters locally. Per-cycle work
  is proportional to your tenant's total Exchange audit volume, not to
  your canary count.
- Blob contents for a window are held in memory while they are matched.
  In small and mid-size tenants (up to a few thousand active mailboxes)
  this is unremarkable; in large tenants expect the monitor to use
  noticeably more memory and time during backlog catch-up, when it walks
  up to 7 days of feed in 24-hour windows.
- The seen-ID dedup set is capped at 50,000 events. In tenants whose
  audit volume exceeds that within the API retention window, a re-polled
  window can re-alert on events older than the cap. Treat duplicate
  alerts after an outage as possible in high-volume tenants.

If you operate at a scale where this matters, run the monitor with a
short interval (small windows), give it headroom during catch-up, and
validate against your tenant's real volume before relying on it. Reports
of real-world envelopes are welcome —
[open a discussion](https://github.com/vortacity/anglerfish/discussions).

## Service deployment

`examples/anglerfish-monitor.service` is a systemd unit template pairing
`--no-console` with the alert log and heartbeat. See the
[production deployment guide](production-deployment.md) for credential
handling and watchdog wiring.
