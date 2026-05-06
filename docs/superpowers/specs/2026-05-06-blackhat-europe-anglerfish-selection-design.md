# Anglerfish Black Hat Europe Selection Design

**Date:** 2026-05-06
**Status:** Approved design from brainstorming, revised after adversarial review
**Project:** Anglerfish
**Target:** Black Hat Europe Arsenal / Call for Tools

## Context

Anglerfish was not selected for Black Hat Arsenal USA after being submitted with
an offline `--demo` recording. For the Black Hat Europe submission, the project
should be improved around the selection qualities Black Hat Arsenal emphasizes:
open-source security tooling, live or interactive demonstrations, direct utility
for practitioners, and a clear hands-on story.

The current repository is technically healthy:

- `.venv/bin/pytest -q` passes 424 tests.
- `.venv/bin/ruff check src tests` passes.
- `.venv/bin/bandit -r src -ll` reports no issues.

The main issue is not basic quality. The issue is focus. The README now leads
with one strong claim: Outlook canaries inside Microsoft 365, detected through
Unified Audit Log events, without callback URLs, DNS beacons, or external
listener infrastructure. The implementation and documentation still expose a
broader platform surface: SharePoint canaries, OneDrive canaries, batch
deployment, a Textual dashboard, file canary dependencies, and secondary demo
paths.

That broader surface dilutes the strongest selection story. For Europe, the
tool should be streamlined so reviewers can quickly understand, verify, and
remember it.

## Status as of 2026-05-06

The product-surface narrowing in this design is already implemented on the
`anglerfish-outlook-mvp-reset` worktree (currently 19 commits ahead of main and
2 commits behind main). That work covers most of the original "Implementation Shape":
SharePoint and OneDrive deployers removed, batch and dashboard CLI removed,
`textual`, `python-docx`, and `openpyxl` dropped from `pyproject.toml`, monitor
scoped to Outlook-only events, verify scoped to drafts, application-auth
hardening complete.

Step 0 of execution is therefore: rebase the worktree onto main, resolve
conflicts, and merge. Subsequent work in this spec anchors against the
post-merge state.

Genuinely new work in this spec, not on the worktree:

- audit URL host validation in `src/anglerfish/audit.py`
- cleanup-vs-late-alert lookback window in `src/anglerfish/monitor.py`
- README rewrite around the Europe submission positioning
- permission-framing rewrite in `README.md` and `docs/demo-tenant-setup.md`
- `docs/blackhat-europe-demo-script.md` with Booth Demo Procedure
- comparison table vs. Thinkst Canary, Defender for Office 365, DIY Sentinel
- sanitized real evidence: one draft record, one send record, one UAL event
- sanitization protocol document
- Sentinel KQL snippet
- 2-3 minute reviewer video script and recording

## Goal

Prepare Anglerfish for a stronger Black Hat Europe Arsenal submission by making
it a focused Outlook canary tool with a real Microsoft 365 evidence package.

The reviewer-facing claim should be:

> Anglerfish is a self-hosted, open-source tool that deploys native Outlook
> canaries in Microsoft 365 and detects mailbox access through Unified Audit
> Log correlation: no third-party data plane, no DNS callbacks, no HTTP
> beacons, no external listener infrastructure.

## Product Boundary

Anglerfish should become an Outlook-only Microsoft 365 canary tool for the
Europe submission release.

Keep:

- Outlook draft canaries.
- Outlook send canaries.
- `monitor` for Unified Audit Log `MailItemsAccessed` correlation.
- `list` for deployment records.
- `verify`, primarily for draft canaries.
- `cleanup` for deployed Outlook artifacts.
- custom Outlook YAML templates.
- application authentication with client secret and certificate modes.
- offline `--demo` mode as a clearly labeled convenience and conference
  fallback, not submission proof.

Remove from the main release (already shipped on the worktree, see Status):

- SharePoint canaries.
- OneDrive canaries.
- batch deployment.
- dashboard / Textual UI.
- file canary dependencies such as `python-docx` and `openpyxl`.
- monitor matching for file events.
- docs, examples, and demo fixtures for removed surfaces.

This is a breaking release because supported canary types and commands are
removed.

## Reviewer Demo Package

The Europe submission is built around one real tenant recording, not offline
demo mode.

Required demo flow:

1. State the problem: callback-based canaries require external callback
   infrastructure, while Anglerfish uses Microsoft 365 native audit telemetry
   the tenant already collects.
2. Deploy an Outlook draft canary to a test mailbox.
3. Show the deployment record fields used for correlation:
   `timestamp`, `target_user`, `folder_id`, `message_id`, and
   `internet_message_id`.
4. Trigger authorized mailbox access in the demo tenant. For draft mode, use
   an approved Graph or Exchange read path that touches the hidden
   folder/message. For a human Outlook-on-the-Web interaction, use send mode
   or a visible test artifact.
5. Show a real `MailItemsAccessed` Unified Audit Log event after ingestion.
6. Run `anglerfish monitor --once` and show that it matches the event to the
   deployment record, including the actor identity (UPN or app ID).
7. State the limitations plainly: UAL latency, audit and licensing dependency,
   app-level `Mail.ReadWrite`, false-positive surface from other tenant tools,
   and authorized use only.
8. Run or describe cleanup.

### Booth Demo Procedure

Unified Audit Log surfacing latency for `MailItemsAccessed` has no guaranteed
SLA. Microsoft documents that core service audit events are typically available
in about 60-90 minutes, with anomalies possible. A booth visitor cannot watch a
click-and-wait cycle. The booth procedure is therefore:

1. During booth hours, the presenter keeps a pre-staged demo tenant active.
   For the primary draft path, a controlled Graph or Exchange read touches the
   hidden canary message on a rolling cadence. If the booth flow needs a manual
   Outlook-on-the-Web action, use send mode or a visible test artifact.
2. When a visitor walks up, the presenter runs `anglerfish monitor --once` and
   shows the most recent match between a real UAL event and a deployment
   record.
3. The presenter explicitly states the latency framing in one sentence:

   > "What you're seeing is a real `MailItemsAccessed` audit event from this
   > tenant. UAL has no delivery SLA and core service events are typically
   > available in about 60-90 minutes, so I'm running access on a rolling
   > rotation in the background. Anglerfish is matching that audit
   > event to the deployment record we created earlier."

The `--demo` simulated mode remains available as a fallback if the conference
network or the demo tenant is unreachable, but it is not the booth's primary
path and the presenter does not present it as real telemetry.

### Submission Collateral

- README top section rewritten around the live proof path and the
  self-hosted / open-source / native-telemetry positioning.
- `docs/blackhat-europe-demo-script.md` covering deploy, monitor, the Booth
  Demo Procedure, and cleanup.
- 2-3 minute reviewer video script.
- one sanitized Outlook draft deployment record under `docs/examples/`.
- one sanitized Outlook send deployment record under `docs/examples/`.
- one sanitized real `MailItemsAccessed` UAL event under `docs/examples/`.
- sanitization protocol document at `docs/examples/sanitization.md`.
- Sentinel KQL snippet for direct operator validation.
- comparison table (see Submission Positioning).
- Limitations section (see Limitations).

### Sanitization Protocol

Before committing any real-tenant artifact to the public repo, replace the
following fields with documented placeholder values:

- `OrganizationId`, `OrganizationName`
- `MailboxOwnerUPN`, `MailboxOwnerSid`, `MailboxGuid`
- `UserId`, `UserKey`, `UserType`
- `AppId`, `ClientAppId`
- `ClientIP`, `ClientIPAddress`, `ClientInfoString`
- `SessionId`, `ConnectionId`, `OriginatingServer`
- record-level `Id` GUID
- `InternetMessageId` (preserve the canary stem, replace any tenant suffix)
- folder identifiers that encode tenant-internal paths

Never commit raw real-tenant artifacts, even temporarily. Export or copy the
artifact outside the repo, sanitize it there, and only add the sanitized output
to git.

Replace with stable example values (`contoso.onmicrosoft.com`,
`00000000-0000-0000-0000-000000000001`, `203.0.113.42`) so the artifact stays
diffable and recognizably synthetic. Run a one-pass `git diff` review before
each artifact commit. The reproducible procedure lives at
`docs/examples/sanitization.md`; a short helper script at
`docs/examples/sanitize.py` is acceptable but not required.

## Implementation Shape

The code should match the submission story. Surface narrowing already shipped
on the `anglerfish-outlook-mvp-reset` worktree (see Status). Remaining code
work in this spec is small and bounded.

### Remaining code changes

- `src/anglerfish/audit.py`
  - validate Management Activity API `contentUri` and pagination URLs are on
    the configured Management Activity API host before following them. For the
    default commercial endpoint, this means `manage.office.com`; government
    cloud endpoints must be allowed only when configured through the audit
    client's `base_url`. Reject any other host. Use structured URL parsing
    rather than prefix string matching. This closes a SSRF surface if the
    Management API ever returns an unexpected URL or if a malicious response is
    injected into pagination state.
- `src/anglerfish/monitor.py`
  - extend record loading to include `cleaned_up` records within a
    configurable lookback window (default 24h) so late-arriving UAL events
    still match recently-cleaned canaries. Add `status_updated_at` when record
    status changes, use that timestamp for the lookback decision, and skip
    cleaned-up records outside the window. This is the level-1 fix for the
    cleanup-vs-latency race; deeper redesign is out of scope.

### Remaining test changes

- audit URL host validation: rejects `evil.com`, accepts the configured
  Management Activity API host, accepts valid pagination URLs for that host,
  rejects schemeless input, and does not allow prefix tricks such as
  `https://manage.office.com.evil.example/`.
- cleanup-window lookback: a `cleaned_up` record within the window matches;
  the same record outside the window does not.

### Remaining docs and example changes

- rewrite the permission-framing in `README.md` and
  `docs/demo-tenant-setup.md` away from "demo tenant only / never grant in
  production" toward standard tenant-scoped security-tool posture, citing
  peer tools (mailbox backup, CASB, eDiscovery, DLP) and pointing to RBAC
  for Applications as a least-privilege option for production deployments.
- consolidate `docs/arsenal-demo-script.md` into a new
  `docs/blackhat-europe-demo-script.md` covering deploy, monitor, the Booth
  Demo Procedure, and cleanup.
- add a sanitization protocol document at `docs/examples/sanitization.md`
  and three sanitized artifacts under `docs/examples/`.
- document the existing `monitor.py` `exclude_app_ids` allowlist as a config
  knob in the README's monitor section. No code change required; the hook
  already exists at `src/anglerfish/monitor.py:98-101`.

## Submission Positioning

The Black Hat Europe submission should not pitch Anglerfish as a general
Microsoft 365 deception platform. It should pitch Anglerfish as a focused tool
for one under-served defensive workflow:

- plant native Outlook canaries;
- use the audit telemetry defenders already collect;
- avoid third-party data planes, egress, callback services, DNS zones, and
  webhook infrastructure;
- correlate access back to a deployment record;
- give operators a cleanup path.

Suggested abstract:

> Anglerfish is a self-hosted, open-source CLI that deploys Outlook canaries
> inside Microsoft 365 and detects mailbox access against telemetry the tenant
> already collects, with no third-party data plane in the alert path. The demo
> shows a hidden Outlook draft canary deployed through Microsoft Graph, the
> resulting deployment record, a real `MailItemsAccessed` audit event, and
> Anglerfish matching that event back to the canary using only Unified Audit
> Log polling: no DNS callbacks, HTTP beacons, tracking pixels, or external
> listener services.

### Comparison

| Tool | Open-source | Self-hosted | Third-party data plane | Tenant-native telemetry |
|---|---|---|---|---|
| Anglerfish | yes (MIT) | yes | no | yes (UAL) |
| Managed Canarytokens / Canarytools | no | no (SaaS) | yes (Thinkst) | n/a (vendor pattern) |
| Self-hosted Canarytokens | yes | yes | operator-controlled | n/a (callback pattern) |
| Defender for Office 365 anomalous mailbox detection | no | n/a (Microsoft-hosted) | n/a | yes (UAL) |
| DIY Sentinel KQL on `MailItemsAccessed` | yes (operator-built) | yes | no | yes (UAL) |

Anglerfish's distinct space is Outlook-canary deployment as open-source
self-hosted code, paired with detection that runs on telemetry the tenant
already collects and no vendor in the alert path. DIY Sentinel rules share the
telemetry quadrant but offer no deployment side. Managed Canarytokens-style
services offer deployment but route alerts through a vendor data plane.
Self-hosted Canarytokens avoids the SaaS data plane but still relies on callback
patterns rather than tenant-native `MailItemsAccessed` telemetry. Defender XDR
is closed-source and Microsoft-hosted.

Do not overclaim:

- Do not call it real-time detection; UAL latency is expected.
- Do not imply full-tenant coverage; canaries cover deployed artifacts.
- Do not hide `Mail.ReadWrite`; explain the standard security-tool posture
  and the RBAC-for-Applications scoping option.
- Do not lead with offline demo mode.
- Do not lead with removed surfaces.
- Do not call `monitor` "passive"; it polls the Management Activity API.
  The accurate claim is that the canary itself has no outbound callout and
  the detection signal is telemetry the tenant already collects.

## Limitations

These are documented honestly in the README and surfaced in the booth
conversation.

- **UAL latency.** `MailItemsAccessed` events surface in Unified Audit Log
  without a guaranteed delivery SLA. Core service events are typically
  available in about 60-90 minutes, and anomalies can take longer. Anglerfish
  is access-based detection, not real-time. The Booth Demo Procedure triggers
  access on a rolling cadence to keep recent events available.
- **Audit and licensing dependency.** UAL must be enabled and the tenant must
  carry a SKU that covers `MailItemsAccessed` (E3/E5 or audit add-on).
- **Permission scope.** `Mail.ReadWrite` at the application scope grants
  read/write access to all mailboxes in the tenant by default. Production use
  is viable only with formal approval and explicit scoping decisions. This is
  a tenant-scoped security-tool posture comparable to permissions used by
  mailbox backup, CASB, eDiscovery, and DLP integrations, but the risk should
  not be softened: unscoped `Mail.ReadWrite` is tenant-wide mailbox write
  access. Operators who want least-privilege scoping can constrain the app to
  specific mailboxes via Exchange Online RBAC for Applications, while ensuring
  unscoped Microsoft Entra grants do not remain in place and broaden effective
  access.
- **False-positive surface.** Anglerfish surfaces every `MailItemsAccessed`
  match against a deployed canary by actor identity and does not filter. In
  tenants running mailbox backup, DLP, eDiscovery, Defender XDR mail scans,
  or Outlook desktop search indexing, expect routine matches from those
  actors. Filter at the downstream alerting tier (Sentinel, custom script).
  An `exclude_app_ids` static-allowlist config knob is available in
  `monitor.py` for known-good actors.
- **Cleanup-vs-latency window.** Monitor matches `cleaned_up` records within
  a 24h lookback from `status_updated_at` so late-arriving UAL events still
  correlate. Beyond the lookback, late events are silently dropped.
- **Authorized use only.** Anglerfish is a defensive tool. Deploy only in
  tenants you administer or are explicitly authorized to test.

## Quality Bar

Before submission:

- A new visitor can understand the tool in one sentence from the README.
- `pip install -e .` installs only dependencies needed for the Outlook
  workflow.
- `anglerfish --help` does not advertise removed surfaces.
- The demo script can be executed in a real tenant and produces real UAL
  evidence, with the Booth Demo Procedure as the live presentation path.
- Offline `--demo` exists only as a clearly labeled simulated mode and
  conference fallback.
- The repo passes tests, lint, format check, Bandit, and dependency audit.
- The Limitations section is reflected in the README in plain language.
- The submission abstract describes self-hosted access-based canary
  detection, not real-time detection or full Microsoft 365 deception.
- A reviewer can verify the core detection path from sanitized artifacts:
  deployment record -> `internet_message_id` -> UAL `MailItemsAccessed` ->
  Anglerfish alert.

## Acceptance Criteria

The work is ready for Black Hat Europe submission when:

1. The CLI product surface is Outlook-only.
2. Removed surfaces are absent from README, CLI help, examples, and demo
   mode.
3. The `anglerfish-outlook-mvp-reset` worktree has been merged into main.
4. The audit URL host validation and the cleanup-window lookback are
   implemented and covered by tests.
5. The primary demo script uses a real Microsoft 365 tenant and real UAL
   correlation, with a documented Booth Demo Procedure for live
   presentation.
6. The repo includes sanitized evidence artifacts (one draft record, one
   send record, one real UAL event) plus a sanitization protocol document.
7. The Limitations section is present in the README and accurately
   describes UAL latency, audit licensing, permission posture, false-positive
   surface, and the cleanup-vs-latency window.
8. The submission abstract leads with self-hosted / open-source /
   native-telemetry positioning, not "no callbacks/beacons/listeners."
9. The comparison table is published in the README and the demo script.
10. Tests and quality checks pass from a contributor install.
11. The submission collateral can be read in under five minutes and still
    makes the core value obvious.

## Official Reference Context

- Black Hat describes Arsenal as a place for developers to showcase
  open-source security tools through interactive, conversational
  demonstrations:
  https://blackhat.com/html/arsenal.html
- Black Hat's Call for Tools page describes Arsenal submissions and presenter
  expectations:
  https://www.blackhat.com/html/arsenal-call-for-tools.html
- Black Hat's CFP FAQ distinguishes Arsenal from Briefings by noting that
  tool demos are best suited for Arsenal:
  https://www.blackhat.com/call-for-papers.html

Confirm the current Black Hat Europe 2026 Arsenal dates from the official
Black Hat site immediately before submission.
