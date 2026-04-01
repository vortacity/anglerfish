# Anglerfish MVP Reset Design

**Date:** 2026-04-01
**Status:** Revised after brainstorming and adversarial review
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
- Lifecycle support: keep `cleanup`, `list`, and a draft-first `verify`
- Batch deployment: remove from MVP
- Dashboard: remove from MVP
- Template model: Outlook-only YAML templates with custom template support
- Auth scope: application auth only (client secret and certificate credential modes)

## Product Boundary

Anglerfish vNext should become an Outlook canary tool, not a general Microsoft 365 canary platform.

Supported MVP story:

1. An operator launches the interactive CLI.
2. The operator chooses Outlook delivery mode: `draft` or `send`.
3. The operator chooses a built-in Outlook lure or an Outlook-only custom YAML template.
4. The operator enters the target mailbox and confirms the deployment.
5. Anglerfish authenticates with Microsoft Graph using application auth.
6. Anglerfish deploys the Outlook canary.
7. Anglerfish writes a local deployment record.
8. The operator can run `list` to see active records.
9. The operator can run `verify` to confirm a deployed draft-mode canary still exists in the target mailbox.
10. The operator can run `cleanup` to remove a deployed canary.
11. The operator can run `monitor` to detect `MailItemsAccessed` events for deployed Outlook canaries.

`draft` and `send` are both in scope, but `draft` is the default, safest, and best-documented path.

Out of scope for the MVP:

- SharePoint deployment
- OneDrive deployment
- Batch manifest deployment
- Dashboard / Textual UI
- Delegated (device code) auth
- Generic multi-surface templating as a core product feature

## Recommended Internal Shape

The reduced MVP should be organized around a small set of units that directly reflect the product boundary:

- `cli`
  - interactive-first entrypoint
  - owns deploy, monitor, verify, cleanup, and list
- `auth`
  - owns application-auth using client secret or certificate credentials
- `deployers/outlook.py`
  - owns the only supported deployment backend
  - handles both `draft` and `send`
- `inventory.py`
  - owns deployment record persistence and lookup
- `templates.py`
  - owns Outlook-only YAML template discovery, loading, and variable rendering
  - supports built-in packaged templates and custom templates via `ANGLERFISH_TEMPLATES_DIR`
- `verify.py`
  - owns deployment health-check for draft-mode Outlook canaries via Graph API
- `monitor.py`
  - owns audit-log polling and Outlook access-event correlation

This is intentionally less generic than the current architecture. The code should stop carrying abstractions for product surfaces that the MVP no longer supports.

## Data Flow

### Deploy

1. CLI wizard collects delivery mode, template choice, and target mailbox.
2. CLI authenticates with Graph using application auth.
3. Outlook deployer creates the canary using `draft` or `send`.
4. Inventory writes a deployment record atomically.
5. CLI prints the result and next-step monitor guidance.

### Monitor

1. Monitor loads active Outlook deployment records.
2. Monitor authenticates to the Management Activity API.
3. Monitor polls relevant audit content.
4. Monitor matches `MailItemsAccessed` events to stored Outlook artifact identifiers.
5. Monitor emits alerts in the terminal.

### Verify

1. Verify loads active draft-mode Outlook deployment records.
2. Verify authenticates with Graph.
3. Verify checks each record's hidden mail folder still exists via a single GET call.
4. Verify reports status: OK (found), GONE (404), or ERROR (other failure).

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

### Phase 1: Remove non-core surfaces

- Remove SharePoint and OneDrive deployers, templates, and tests
- Delete dashboard support and the `textual` dependency from the core install path
- Delete batch deployment support while retaining `pyyaml` for Outlook template loading
- Remove file-canary dependencies such as `python-docx` and `openpyxl`
- Strip SharePoint/OneDrive branches from monitor event matching, verify, and CLI routing

### Phase 2: Reframe the product

- Rewrite the README and CLI help around one core story: deploy Outlook canaries and detect access to them
- Remove SharePoint and OneDrive from top-level messaging, examples, and architecture explanations
- Make `draft` the default path in docs and prompts while keeping `send` supported
- Document `verify` as a draft-first support command in the operator workflow

### Phase 3: Simplify branching logic

- Remove delegated (device code) auth; keep application auth with both client-secret and certificate credential modes
- Trim the template system to Outlook-only YAML; keep `ANGLERFISH_TEMPLATES_DIR` for custom lures and variable substitution
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
- verify deployed draft canary still exists
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

## Adversarial Review Amendments

The following changes were introduced during adversarial review and reconciled against the current design constraints.

### 1. Certificate auth retained

**Original:** Auth scope was client-secret application auth only.

**Revised:** Application auth with both client-secret and certificate credential modes.

**Rationale:** The certificate auth implementation in `auth.py` is correct, well covered by tests, and materially isolated from the core deploy/monitor/template flows. It does add some prompt and configuration branching in the auth layer, so it is not free complexity, but that complexity is bounded and localized. Certificate auth is common in enterprise security environments, aligns with the expectations of the target audience, and may be required by policy in exactly the tenants where this tool is most useful. Keeping it preserves operator viability without reopening broader product sprawl.

### 2. Verify retained

**Original:** Verify was listed as out of scope for the MVP.

**Revised:** Verify is retained as a draft-first support command alongside deploy, list, cleanup, and monitor.

**Rationale:** Verify fills a real operator gap: `list` reads local records but cannot confirm artifacts still exist in the target mailbox, and `monitor` does not answer "is my canary still there?" The current Outlook verify path is small and useful, but it maps cleanly to draft-mode canaries because it checks hidden-folder existence by `folder_id`. The MVP spec therefore retains `verify` honestly as a draft-first support command rather than overstating it as a full check across both Outlook delivery modes.

### 3. YAML template system retained

**Original:** Replace the broad template system with a few built-in Outlook lure definitions.

**Revised:** Trim the template system to Outlook-only YAML. Keep built-in packaged templates, custom template directory (`ANGLERFISH_TEMPLATES_DIR`), and variable substitution.

**Rationale:** The built-in Outlook lures are a good starting point but intentionally generic. In real use, operators may need lures tailored to a target organization's names, processes, and internal style. After removing SharePoint and OneDrive template types, retaining Outlook-only YAML templates plus `ANGLERFISH_TEMPLATES_DIR` preserves the main customization point without keeping the broader multi-surface template model. This keeps the MVP practical without reopening the larger platform design.

### 4. Phase ordering revised

**Original:** Phase 1 reframes the product (docs/README), Phase 2 removes non-core surfaces (code).

**Revised:** Phase 1 removes non-core surfaces (code), Phase 2 reframes the product (docs/README).

**Rationale:** Since all phases land in a single release, the ordering is about development workflow. Removing code first means docs are written against the actual final surface rather than speculatively. Docs written after code removal are accurate by construction and do not need a second editing pass to reconcile with reality. The original ordering risked writing README text twice — once anticipating removals, once adjusting after they happened.

## Implementation Planning Note

The next planning step should assume a breaking-change release and treat removed surfaces as actual removals, not hidden or semi-supported extras.
