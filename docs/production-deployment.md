# Production Deployment Guide

The [demo tenant setup guide](demo-tenant-setup.md) gets a first canary
deployed in a safe tenant. This guide covers what changes when the target
is a production tenant: authorization, permission scoping, credential
handling, host hardening, and running the monitor as a service.

## 1. Authorization before anything else

Work through the
[threat model's authorization requirements](threat-model.md#authorization-requirements)
and deployment checklist first: written authorization from the asset
owner, SOC coordination so canary alerts are triaged correctly, and a
documented cleanup plan. Because alert data identifies the accessing
user, also obtain privacy/legal sign-off — see
[privacy and data handling](privacy.md).

## 2. App registration

Follow the same registration steps as the
[demo guide](demo-tenant-setup.md#2-create-an-entra-app-registration),
with production choices:

- **Single-tenant** app, no redirect URIs, no delegated permissions.
- **Certificate credential, not a client secret.** Anglerfish supports
  both, but a certificate cannot be replayed from a leaked environment
  file the way a secret string can, supports shorter practical rotation,
  and is what Microsoft recommends for unattended app-only auth. Keep the
  private key readable only by the monitor's service account
  (`chmod 600`).
- A dedicated app registration for Anglerfish — do not piggyback on an
  existing app's grants, or scoping (next step) becomes impossible to
  reason about.

## 3. Scope the mailbox permission

The default `Mail.ReadWrite` application grant is tenant-wide. In
production, scope it to the canary mailboxes with Exchange RBAC for
Applications — the full walkthrough, including the critical step of
removing the unscoped Entra grant, is in
[scoping-permissions.md](scoping-permissions.md).

The end state: a leaked Anglerfish credential exposes the canary
mailboxes, not the tenant.

## 4. Credential handling on the host

Configuration is environment-variable driven (see `.env.example`). In
production:

- If you keep credentials in an environment file, make it `chmod 600`
  and owned by the service account (`/etc/anglerfish/env` in the systemd
  example). Anglerfish itself never writes credentials to the
  environment, to disk, or to any cache — interactively prompted values
  are passed in memory only.
- Prefer the certificate variables
  (`ANGLERFISH_CLIENT_CERT_PFX_PATH` + passphrase, or PEM key +
  thumbprint) over `ANGLERFISH_CLIENT_SECRET`.
- Anglerfish does not auto-load `.env` files; whatever supervises the
  process (systemd `EnvironmentFile=`, a container runtime, your shell)
  is responsible for injecting variables, which keeps secret delivery in
  one auditable place.

## 5. Protect the operator host

The host running Anglerfish holds a map of every planted canary
(deployment records) and the identities of everyone who triggered one
(alert log). The
[threat model](threat-model.md#operator-workstation-and-local-artifacts)
covers why this matters; concretely:

- Run deployment and monitoring from an access-controlled analyst host
  or dedicated service VM, not a shared jump box.
- Anglerfish creates its directories (`~/.anglerfish`, records, state,
  logs) with owner-only permissions; keep them that way, and use full
  disk encryption on analyst laptops.
- Never commit deployment records to source control; treat them like
  detection content, because an attacker who reads them can locate and
  avoid every canary.
- Back up the records directory if you back up anything — without
  records, deployed canaries become unmonitorable and uncleanable.

## 6. Run the monitor as a service

Start from `examples/anglerfish-monitor.service`:

```ini
[Service]
User=anglerfish
EnvironmentFile=/etc/anglerfish/env
ExecStart=/usr/local/bin/anglerfish monitor \
  --records-dir /var/lib/anglerfish/records \
  --state-file /var/lib/anglerfish/monitor-state.json \
  --alert-log /var/log/anglerfish/alerts.jsonl \
  --no-console
Restart=on-failure
```

Operational notes:

- Use a dedicated unprivileged user; the paths above keep records,
  state, and logs out of any human's home directory.
- Wire a watchdog to the heartbeat file — path, schema, and the
  `healthy`/`degraded` contract are documented in the
  [monitor reference](monitoring.md#heartbeat-file). Alert on stale
  `last_poll` or persistent `degraded`.
- Token refresh is automatic for the life of the process; a restart
  re-authenticates and resumes from the persisted watermark, so
  `Restart=on-failure` loses nothing (see
  [state file semantics](monitoring.md#state-file)).
- Plan for audit-log latency in your runbook: a canary alert describes
  access that happened 60–90+ minutes ago, and a brand-new Management
  API subscription can take up to 12 hours to serve content.
- If known-good tooling (backup, DLP, eDiscovery) reads mailboxes,
  exclude those principals with `--exclude-app-id` — and never the
  principal you use for authorized testing evidence.

## 7. Operate the canary fleet

- Deploy every canary with `--output-json` into the monitored records
  directory; an unrecorded canary is unmonitored by definition.
- Re-`verify` draft canaries on a schedule; a `GONE` canary stopped
  providing coverage (and its disappearance is itself worth
  investigating — see the threat model).
- Rotate canaries periodically and after any suspected compromise, per
  the [threat model](threat-model.md#coverage-is-point-in-time):
  deploy the replacement, confirm it verifies, then `cleanup` the old
  record.
- Exercise the full alert path quarterly with `demo-access` against a
  designated test canary, so the SOC sees a real end-to-end alert.
