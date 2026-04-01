# Anglerfish MVP Reset Design

**Date:** 2026-04-01
**Status:** Approved during brainstorming
**Project:** Anglerfish

## Context

Anglerfish is currently positioned as a Microsoft 365 canary platform with three deployment surfaces and multiple operational workflows:

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
- the project already has a coherent package layout

The main problem is product breadth. Core user-facing orchestration remains spread across large modules such as `src/anglerfish/cli/deploy.py`, `src/anglerfish/cli/_main.py`, `src/anglerfish/monitor.py`, and `src/anglerfish/dashboard.py`. The project is trying to be a deployer, monitor, dashboard, template system, and multi-surface platform at the same time.

This design intentionally resets Anglerfish to a smaller MVP.

## Goal

Turn Anglerfish into a straightforward open-source MVP for security operators:

- easy to explain
- easy to run
- easy to maintain
- narrow enough that future expansion is a conscious choice

This is not a refactor-only plan. It is a product-scope reduction.

## Shared Decisions

The design discussion resolved the following decisions:

- Product direction: hard MVP reset
- Primary user: security operator
- Core surface: Outlook draft canaries
- Primary entrypoint: interactive wizard
- Detection UX: keep a CLI monitor
- Lifecycle support: keep `cleanup` and `list`
- Batch deployment: remove from MVP
- Dashboard: remove from MVP
- Template model: a few built-in lures, not a full generic system
- Auth scope: client-secret application auth only
- Change strategy: willing to make breaking cuts to reach a sharper product

## Product Boundary

Anglerfish vNext becomes a focused Outlook canary deployer with built-in CLI monitoring.

Supported MVP story:

1. An operator launches the interactive CLI.
2. The operator selects one of a small number of built-in Outlook lure types.
3. The operator enters the target mailbox and confirms the deployment.
4. Anglerfish authenticates with Microsoft Graph using client-secret app auth.
5. Anglerfish creates an Outlook draft canary.
6. Anglerfish writes a local deployment record.
7. The operator can run `list` to see active records.
8. The operator can run `cleanup` to remove a deployed canary.
9. The operator can run `monitor` to correlate `MailItemsAccessed` events to stored deployment records.

Out of scope for the MVP:

- SharePoint deployment
- OneDrive deployment
- Batch manifest deployment
- Dashboard / Textual UI
- Certificate auth
- `verify`
- Generic multi-surface templating as a product feature

## Recommended Internal Shape

The reduced MVP should be organized around a small set of focused units:

- `cli`
  - owns the operator-facing wizard and command dispatch
  - only needs deploy, monitor, cleanup, and list
- `auth`
  - owns one application-auth path using client secret credentials
- `deployers/outlook.py`
  - owns the only supported deployment backend
- `inventory.py`
  - owns deployment record persistence and lookup
- `monitor.py`
  - owns audit-log polling and record correlation

This is a deliberate move away from “one framework that can support everything later.” The code should reflect the current product boundary directly.

## Data Flow

### Deploy

1. CLI wizard collects target mailbox and lure choice.
2. CLI authenticates with Graph using client-secret app auth.
3. Outlook deployer creates the draft canary.
4. Inventory writes a deployment record atomically.
5. CLI prints the result and next-step monitor guidance.

### Monitor

1. Monitor loads active deployment records.
2. Monitor authenticates to the Management Activity API.
3. Monitor polls relevant audit content.
4. Monitor matches `MailItemsAccessed` events to stored deployment identifiers.
5. Monitor emits operator-facing alerts in the terminal.

### Cleanup

1. Cleanup loads a deployment record.
2. Cleanup authenticates with Graph.
3. Outlook cleanup removes the deployed artifact.
4. Inventory updates record status.

## Immediate Improvements

The right order is to scale down first, then harden the reduced system.

### Phase 1: Re-scope the product

- Rewrite the README and CLI help around one core story: Outlook draft deployment plus CLI monitoring
- Remove non-MVP commands from the supported public surface
- Remove SharePoint and OneDrive from docs, examples, and top-level messaging

### Phase 2: Remove non-core subsystems

- Delete dashboard support and the `textual` dependency from the core install path
- Delete batch deployment support
- Remove `verify` from the supported command set
- Remove document-generation dependencies tied to file canaries such as `python-docx` and `openpyxl`

### Phase 3: Simplify branching logic

- Collapse authentication to client-secret application auth
- Replace the broad template model with a few built-in Outlook lure definitions
- Reduce prompt and argument branching to the MVP path first

### Phase 4: Harden the smaller codebase

Apply the already-identified hardening items to the reduced surface:

- validate Management Activity API redirect targets before following them
- create records, state files, and logs with restrictive permissions
- stop retaining secrets in process environment longer than necessary
- keep direct, request-ID-aware error reporting for Graph and audit failures

### Phase 5: Rebuild tests around the actual product

The regression suite should prove the MVP story, not preserve removed scope:

- deploy Outlook draft canary
- list active records
- clean up deployed canary
- monitor and match `MailItemsAccessed`

Delete or rewrite fixtures, docs, and tests that only serve removed surfaces.

## Why This Is Better

This design solves the actual problem observed in the repository:

- It addresses breadth, not just style.
- It gives the project one clear explanation.
- It reduces code paths, dependencies, and docs at the same time.
- It creates a sharper OSS identity.
- It makes future expansion additive instead of inherited complexity.

The result should feel like a small, opinionated operator tool rather than a partially generalized platform.

## Alternatives Considered

### 1. Soft deprecation

Keep the extra commands in place, but redesign docs and defaults around the core workflow.

Why rejected:

- still leaves the repo feeling larger than intended
- preserves maintenance cost for features the product no longer wants to prioritize
- weakens the clarity benefit of the reset

### 2. Full-suite cleanup

Keep the existing broad feature set and focus on refactoring, tests, and UX polish.

Why rejected:

- optimizes the wrong thing
- spends effort preserving scope that the desired MVP does not need
- makes “simple and direct” harder to achieve

## Risks

- Breaking changes will require explicit release notes and updated docs.
- Some users may rely on removed commands and surfaces.
- If the project later needs file canaries again, reintroduction should happen as a deliberate second phase rather than quick backfill.

## Success Criteria

The reset is successful when:

- a new user can explain the product in one sentence
- the README shows a single primary workflow
- installation has fewer non-core dependencies
- the command surface is visibly smaller
- the main regression suite maps directly to the supported operator workflow

## Implementation Planning Note

The next planning step should assume a breaking-change release and treat non-MVP features as removals, not as hidden or deprecated extras unless a later decision explicitly changes that stance.
