# Roadmap

This is the maintainer's current view of where Anglerfish is going. It is a
statement of intent, not a schedule. Items marked **help wanted** are good
places for outside contributions — open a
[Discussion](https://github.com/vortacity/anglerfish/discussions) before
starting anything large so we can agree on the approach.

## Near term

- Batch deploy mode for seeding many mailboxes (the JSON-output half of
  machine-readable automation shipped; see Done).
- Canary lifecycle management (expiry, rotation) — next from the list
  below.

### Done

- ~~More alert channels~~ — Microsoft Teams (Adaptive Card workflow
  webhook) and a generic HMAC-signed JSON webhook. syslog/CEF output
  remains open (help wanted).
- ~~Tamper detection~~ — delete/move/update of a canary item now raises
  a `tamper`-category alert.
- ~~Machine-readable output~~ — `--format json` on `list` and `verify`.
- ~~Exchange RBAC scoping guide~~ — [docs/scoping-permissions.md](docs/scoping-permissions.md).
- ~~Privacy and data-handling documentation~~ — [docs/privacy.md](docs/privacy.md).
- ~~Production deployment guide~~ — [docs/production-deployment.md](docs/production-deployment.md),
  plus a [monitor operations reference](docs/monitoring.md) with the
  documented scale envelope.
- ~~Real deployer abstraction~~ — `CanaryType` lifecycle protocol +
  `deployers/registry.py`; a new canary surface is one class plus one
  `register()` call.
- ~~Typed, versioned deployment records~~ — `DeploymentRecord` dataclass,
  schema v2, one normalizer for all legacy shapes.
- ~~Credentials as values~~ — `AuthConfig` carries credentials; the auth
  flow never writes to `os.environ`.

## Planned features

In rough order of priority:

- **syslog/CEF alert output** (help wanted) — for legacy SIEM pipelines,
  alongside the console, JSONL, Slack, Teams, and webhook sinks.
- **Batch deploy** (help wanted) — seed many mailboxes from a targets
  file, one record per mailbox.
- **Canary lifecycle management** — deploy-time expiry, age surfaced in
  `list`, and a `rotate` command that replaces a canary atomically.
- **More canary surfaces** — SharePoint/OneDrive decoy files and
  calendar-invite canaries using the same audit-log correlation pattern.
  Blocked on the deployer abstraction work above.
- **Sentinel detection content** — export active canary IDs as a Sentinel
  watchlist and ship a parameterized analytic rule, replacing the
  copy-paste KQL snippet.
- **Profiles** — named credential profiles (`--profile`) so consultants and
  MSSPs can work across tenants without juggling environment variables.

## Deferred

- **Packaged distribution** (PyPI, container images) — deliberately
  deferred. `git clone` + `pip install -e .` is the supported install path
  for now.
- **Multi-tenant monitoring in a single process** — profiles come first.

## Not planned

- Real-time detection. Anglerfish correlates Unified Audit Log events,
  which land 60–90 minutes after access. That latency is a property of the
  platform, not the tool; see the
  [threat model](docs/threat-model.md#ual-ingest-latency).
- Callback/beacon infrastructure (tracking pixels, external listeners).
  Operating entirely inside the tenant's own telemetry is the point.
