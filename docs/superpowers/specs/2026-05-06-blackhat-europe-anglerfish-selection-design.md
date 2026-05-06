# Anglerfish Black Hat Europe Selection Design

**Date:** 2026-05-06
**Status:** Approved design from brainstorming
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

## Goal

Prepare Anglerfish for a stronger Black Hat Europe Arsenal submission by making
it a focused Outlook canary tool with a real Microsoft 365 evidence package.

The reviewer-facing claim should be:

> Anglerfish deploys native Outlook canaries in Microsoft 365 and detects
> mailbox access through Unified Audit Log correlation, without DNS callbacks,
> HTTP beacons, or external listener infrastructure.

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
- offline `--demo` mode as a clearly labeled convenience, not submission proof.

Remove from the main release:

- SharePoint canaries.
- OneDrive canaries.
- batch deployment.
- dashboard / Textual UI.
- file canary dependencies such as `python-docx` and `openpyxl`.
- monitor matching for file events.
- docs, examples, and demo fixtures for removed surfaces.

This should be treated as a breaking release because supported canary types and
commands are removed.

## Reviewer Demo Package

The Europe submission should be built around one real tenant recording, not
offline demo mode.

Required demo flow:

1. State the problem: callback-based canaries require external callback
   infrastructure, while Anglerfish uses Microsoft 365 native audit telemetry.
2. Deploy an Outlook draft canary to a test mailbox.
3. Show the deployment record fields used for correlation:
   `timestamp`, `target_user`, `folder_id`, `message_id`, and
   `internet_message_id`.
4. Trigger authorized mailbox access in the demo tenant.
5. Show a real `MailItemsAccessed` Unified Audit Log event after ingestion.
6. Run `anglerfish monitor --once` and show that it matches the event to the
   deployment record.
7. State the limitations plainly: UAL latency, audit and licensing dependency,
   app-level `Mail.ReadWrite`, and authorized use only.
8. Run or describe cleanup.

Submission collateral:

- README top section rewritten around the live proof path.
- `docs/blackhat-europe-demo-script.md`.
- 2-3 minute reviewer video script.
- one sanitized Outlook draft deployment record.
- one sanitized Outlook send deployment record.
- one sanitized real `MailItemsAccessed` UAL event.
- Sentinel KQL snippet for direct operator validation.
- concise comparison table versus callback-token tools.
- honest limitations section that avoids overclaiming real-time detection or
  full Microsoft 365 deception coverage.

Demo mode should remain useful for local evaluation, tests, and conference
fallbacks, but the submission package should make clear that the selection proof
is real UAL evidence from a Microsoft 365 tenant.

## Implementation Shape

The code should match the submission story.

Core changes:

- `pyproject.toml`
  - remove `textual`, `textual[dev]`, `python-docx`, and `openpyxl`.
- `src/anglerfish/cli/_main.py`
  - remove `batch` and `dashboard` subcommands.
  - restrict `--canary-type` choices to `outlook`.
- `src/anglerfish/cli/deploy.py`
  - remove SharePoint and OneDrive deploy, cleanup, list, and verify branches.
- `src/anglerfish/deployers/outlook.py`
  - keep as the only deployer.
- `src/anglerfish/templates.py` and `src/anglerfish/models.py`
  - keep Outlook-only template discovery, validation, and rendering.
- `src/anglerfish/monitor.py`
  - remove file-event indexes and matchers.
  - match only `MailItemsAccessed` events against Outlook artifact identifiers.
- `src/anglerfish/audit.py`
  - keep the audit content needed for Outlook correlation, likely
    `Audit.Exchange`.
  - validate Management Activity API `contentUri` and pagination URLs before
    following them.
- `src/anglerfish/verify.py`
  - enforce and document draft-first behavior.
- tests
  - delete or rewrite tests for removed surfaces.
  - strengthen tests for Outlook deploy, monitor, verify, cleanup, demo fixtures,
    and audit URL validation.
- docs and examples
  - remove SharePoint and OneDrive examples.
  - add sanitized Outlook draft/send records and a sanitized real UAL sample.

## Submission Positioning

The Black Hat Europe submission should not pitch Anglerfish as a general
Microsoft 365 deception platform. It should pitch Anglerfish as a focused tool
for one under-served defensive workflow:

- plant native Outlook canaries;
- use the audit telemetry defenders already collect;
- avoid egress, callback services, DNS zones, and webhook infrastructure;
- correlate access back to a deployment record;
- give operators a cleanup path.

Suggested abstract:

> Anglerfish is an open-source CLI for deploying Outlook canaries inside
> Microsoft 365 and detecting mailbox access through Unified Audit Log
> correlation. Unlike callback-token workflows, Anglerfish does not require DNS,
> HTTP beacons, tracking pixels, or external listener infrastructure. The demo
> shows a hidden Outlook draft canary deployed through Microsoft Graph, the
> resulting deployment record, a real `MailItemsAccessed` audit event, and
> Anglerfish matching that event back to the canary.

Do not overclaim:

- Do not call it real-time detection; UAL latency is expected.
- Do not imply full-tenant coverage; canaries cover deployed artifacts.
- Do not hide `Mail.ReadWrite`; explain why a demo/security tenant or formal
  approval is required.
- Do not lead with offline demo mode.
- Do not lead with removed surfaces.

## Quality Bar

Before submission:

- A new visitor can understand the tool in one sentence from the README.
- `pip install -e .` installs only dependencies needed for the Outlook workflow.
- `anglerfish --help` does not advertise removed surfaces.
- The demo script can be executed in a real tenant and produces real UAL
  evidence.
- Offline `--demo` exists only as a clearly labeled simulated mode.
- The repo passes tests, lint, format check, Bandit, and dependency audit.
- The README documents limitations plainly: UAL latency, audit/licensing
  dependency, `Mail.ReadWrite`, and authorized use.
- The submission abstract describes access-based canary detection, not
  real-time detection or full Microsoft 365 deception.
- A reviewer can verify the core detection path from sanitized artifacts:
  deployment record -> `internet_message_id` -> UAL `MailItemsAccessed` ->
  Anglerfish alert.

## Acceptance Criteria

The work is ready for Black Hat Europe submission when:

1. The CLI product surface is Outlook-only.
2. Removed surfaces are absent from README, CLI help, examples, and demo mode.
3. The primary demo script uses a real Microsoft 365 tenant and real UAL
   correlation.
4. The repo includes sanitized evidence artifacts for reviewer trust.
5. Tests and quality checks pass from a contributor install.
6. The submission collateral can be read in under five minutes and still makes
   the core value obvious.

## Official Reference Context

- Black Hat describes Arsenal as a place for developers to showcase open-source
  security tools through interactive, conversational demonstrations:
  https://blackhat.com/html/arsenal.html
- Black Hat's Call for Tools page describes Arsenal submissions and presenter
  expectations:
  https://www.blackhat.com/html/arsenal-call-for-tools.html
- Black Hat's CFP FAQ distinguishes Arsenal from Briefings by noting that tool
  demos are best suited for Arsenal:
  https://www.blackhat.com/call-for-papers.html

Confirm the current Black Hat Europe 2026 Arsenal dates from the official
Black Hat site immediately before submission.
