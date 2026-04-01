# Anglerfish MVP Reset Design

**Date:** 2026-04-01
**Status:** Revised and approved during brainstorming
**Project:** Anglerfish

## Context

Anglerfish is currently positioned as a Microsoft 365 canary platform with several surfaces and workflows:

- Outlook canaries
- SharePoint canaries
- OneDrive canaries
- Interactive deploy
- Non-interactive deploy
- Batch manifests
- Cleanup
- List
- Verify
- Monitor
- Textual dashboard

The codebase is not fundamentally unstable. In the current repository state:

- the git worktree is clean
- the bundled virtualenv passes `424` tests
- the package layout is already reasonably coherent

The main issue is product breadth, not basic breakage. Core orchestration still lives in large user-facing modules such as `src/anglerfish/cli/deploy.py`, `src/anglerfish/cli/_main.py`, `src/anglerfish/monitor.py`, and `src/anglerfish/dashboard.py`. The project is currently trying to be a deployer, monitor, dashboard, batch system, and multi-surface canary platform at the same time.

This design intentionally narrows Anglerfish to a more manageable MVP with a sharper public promise.

## Goal

Turn Anglerfish into a straightforward open-source tool for security operators:

- easy to explain
- easy to demo
- easy to maintain
- narrow enough that future expansion is a deliberate second step

This is a product-scope reduction first and a code simplification second.

## Shared Decisions

The design discussion resolved the following decisions:

- Product direction: sharp MVP reset
- Primary user: security operator
- Core product: deploy Outlook canaries and detect access to Outlook canaries
- Supported delivery modes: `draft` and `send`
- Primary default mode: `draft`
- Primary entrypoint: interactive wizard
- Detection UX: built-in CLI monitor
- Lifecycle support: keep `cleanup` and `list`
- Batch deployment: remove from MVP
- Dashboard: remove from MVP
- Template model: a few built-in Outlook lures
- Auth scope: client-secret application auth only

## Product Boundary

Anglerfish vNext should become an Outlook canary tool, not a general Microsoft 365 canary platform.

Supported MVP story:

1. An operator launches the interactive CLI.
2. The operator chooses Outlook delivery mode: `draft` or `send`.
3. The operator chooses one of a small number of built-in Outlook lure types.
4. The operator enters the target mailbox and confirms the deployment.
5. Anglerfish authenticates with Microsoft Graph using client-secret app auth.
6. Anglerfish deploys the Outlook canary.
7. Anglerfish writes a local deployment record.
8. The operator can run `list` to see active records.
9. The operator can run `cleanup` to remove a deployed canary.
10. The operator can run `monitor` to detect `MailItemsAccessed` events for deployed Outlook canaries.

`draft` and `send` are both in scope, but `draft` is the default, safest, and best-documented path.

Out of scope for the MVP:

- SharePoint deployment
- OneDrive deployment
- Batch manifest deployment
- Dashboard / Textual UI
- `verify`
- Certificate auth
- Generic multi-surface templating as a core product feature

## Recommended Internal Shape

The reduced MVP should be organized around a small set of units that directly reflect the product boundary:

- `cli`
  - interactive-first entrypoint
  - owns deploy, monitor, cleanup, and list
- `auth`
  - owns one application-auth path using client secret credentials
- `deployers/outlook.py`
  - owns the only supported deployment backend
  - handles both `draft` and `send`
- `inventory.py`
  - owns deployment record persistence and lookup
- `monitor.py`
  - owns audit-log polling and Outlook access-event correlation

This is intentionally less generic than the current architecture. The code should stop carrying abstractions for product surfaces that the MVP no longer supports.

## Data Flow

### Deploy

1. CLI wizard collects delivery mode, lure choice, and target mailbox.
2. CLI authenticates with Graph using client-secret app auth.
3. Outlook deployer creates the canary using `draft` or `send`.
4. Inventory writes a deployment record atomically.
5. CLI prints the result and next-step monitor guidance.

### Monitor

1. Monitor loads active Outlook deployment records.
2. Monitor authenticates to the Management Activity API.
3. Monitor polls relevant audit content.
4. Monitor matches `MailItemsAccessed` events to stored Outlook artifact identifiers.
5. Monitor emits alerts in the terminal.

### Cleanup

1. Cleanup loads a deployment record.
2. Cleanup authenticates with Graph.
3. Outlook cleanup removes the deployed artifact.
4. Inventory updates record status.

### List

1. List reads deployment records from the records directory.
2. List presents active and cleaned-up Outlook canaries in a simple operator-facing view.

## Immediate Improvements

The right order is to scale down first, then harden the reduced system.

### Phase 1: Reframe the product

- Rewrite the README and CLI help around one core story: deploy Outlook canaries and detect access to them
- Remove SharePoint and OneDrive from top-level messaging, examples, and architecture explanations
- Make `draft` the default path in docs and prompts while keeping `send` supported

### Phase 2: Remove non-core surfaces

- Remove SharePoint and OneDrive from the supported command surface
- Delete dashboard support and the `textual` dependency from the core install path
- Delete batch deployment support
- Remove `verify` from the supported product surface
- Remove file-canary dependencies such as `python-docx` and `openpyxl`

### Phase 3: Simplify branching logic

- Collapse authentication to client-secret application auth
- Replace the broad template system with a few built-in Outlook lure definitions
- Reduce prompt and argument branching to the Outlook-only MVP path
- Keep both `draft` and `send`, but optimize defaults, tests, and docs around `draft`

### Phase 4: Harden the smaller codebase

Apply the already-identified hardening items to the reduced surface:

- validate Management Activity API redirect targets before following them
- create records, state files, and logs with restrictive permissions
- stop retaining secrets in process environment longer than necessary
- keep direct, request-ID-aware error reporting for Graph and audit failures

### Phase 5: Rebuild tests around the actual product

The regression suite should prove the supported Outlook story:

- deploy draft canary
- deploy send canary
- list active records
- clean up deployed canary
- monitor and match `MailItemsAccessed`

Delete or rewrite fixtures, docs, and tests that only serve removed surfaces.

## Why This Is Better

This design addresses the actual problem in the repository:

- It reduces breadth rather than merely restyling it.
- It gives the project one crisp explanation.
- It preserves the strongest idea in the repo.
- It reduces code paths, dependencies, docs, and operator choices together.
- It creates a smaller and more defensible OSS identity.

The result should feel like a focused Outlook canary operator tool rather than a partially generalized platform.

## Alternatives Considered

### 1. Core-first soft deprecation

Recenter the docs and defaults around Outlook deploy/detect, but leave the extra features in place for now.

Why rejected:

- still leaves the sprawl visible
- preserves maintenance cost for features the MVP no longer wants
- weakens the clarity benefit of the reset

### 2. Full-suite cleanup

Keep the existing broad feature set and focus on refactoring, tests, and UX polish.

Why rejected:

- optimizes the wrong thing
- spends effort preserving scope that the desired MVP does not need
- makes “straightforward and direct” harder to achieve

## Risks

- Breaking changes will require explicit release notes and updated docs.
- Some users may rely on removed commands and surfaces.
- `send` adds extra operational sensitivity and permission requirements even in the reduced product.
- If the project later needs other canary surfaces again, reintroduction should happen as a deliberate next phase rather than quick backfill.

## Success Criteria

The reset is successful when:

- a new user can explain the product in one sentence
- the README shows a single primary Outlook workflow
- installation has fewer non-core dependencies
- the command surface is visibly smaller
- both `draft` and `send` are supported, with `draft` clearly treated as the default path
- the main regression suite maps directly to the supported operator workflow

## Implementation Planning Note

The next planning step should assume a breaking-change release and treat removed surfaces as actual removals, not hidden or semi-supported extras.
