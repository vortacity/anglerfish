# AGENTS.md

Operating contract for coding agents working in this repo.

## What this project is

Anglerfish is an Outlook-only Microsoft 365 canary CLI. It deploys canary email artifacts via Microsoft Graph, keeps local deployment records, and detects mailbox access by correlating `MailItemsAccessed` events from the M365 Unified Audit Log against those records. No callbacks, no DNS, no external SIEM — detection runs against the tenant's own audit telemetry.

This is a security tool used by defenders. It is production-stable (v2.0.0) and ships to real users. Treat changes accordingly.

## Stack

- Python 3.10+ (CI targets 3.10/3.11/3.12)
- Build: `hatchling`
- Runtime deps: `msal`, `requests`, `pyyaml`, `questionary`, `rich`
- Dev: `pytest`, `pytest-asyncio`, `pytest-mock`, `responses`, `ruff`, `mypy` (strict), `bandit`, `pip-audit`
- Entry point: `anglerfish = "anglerfish.cli:main"`

## Layout

```
src/anglerfish/
  cli/            # command surface (_main.py, deploy.py, monitor.py, prompts.py)
  deployers/      # BaseDeployer + outlook.py
  templates/      # bundled YAML canary templates (Outlook only)
  auth.py         # MSAL client-credentials only (secret or cert)
  graph.py        # GraphClient: requests.Session wrapper with retries
  audit.py        # Management Activity API polling
  monitor.py      # main monitor loop
  alerts.py       # Teams webhook + alert log sinks
  inventory.py    # atomic deployment-record persistence
  verify.py       # draft-mode verification
  state.py        # monitor state checkpoint
  models.py       # dataclasses (OutlookTemplate, records)
  templates.py    # template loader + schema
tests/            # pytest suite, one file per module
docs/             # architecture.md, threat-model.md, demo scripts, sentinel KQL
```

## Dev workflow

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

pytest                       # full suite
pytest -k <pattern>          # focused
ruff check src tests         # must be clean before merge
ruff format src tests        # apply formatting
mypy                         # strict; uses pyproject config
bandit -r src                # optional security scan
pip-audit                    # optional dep CVE scan
```

All tests must pass and `ruff check` must be clean before a PR can be merged. CI runs the same commands.

## Conventions

- **Auth is application-only.** Client secret OR certificate (PFX/PEM + thumbprint). No interactive / delegated flows. Don't add them without an issue first.
- **No callback infrastructure in the detection path.** Detection is access-based via UAL `MailItemsAccessed` events correlated to local records. Don't add beacons, tracking pixels, link callbacks, or DNS exfil.
- **No hyperlinks in canary `body_html`.** Templates must look like plausible internal email — hyperlinks would change the detection model.
- **Atomic writes for inventory.** Use temp file + `os.replace`; never partial-write a record file.
- **Graph writes don't auto-retry.** Reads (`GET`, `DELETE`) retry safely; side-effecting writes do not — keep it that way unless idempotency is proven.
- **Templates use `string.Template` `${var}` syntax** (not f-strings, not jinja). Variable names must be valid Python identifiers.

## Out of scope (do not add unprompted)

- New canary types (Teams, SharePoint, files). Outlook-only is intentional for v2.
- Real-time streaming detection. UAL has 60–90 minute ingest latency — this is documented in `docs/threat-model.md` and is part of the design, not a bug.
- Background daemons / system services. This is a user-invoked CLI.
- Replacing `requests` with an async HTTP client. The monitor loop is intentionally synchronous.

## Adding a deployer type (when asked)

Not part of the current product, but the extension shape is fixed:
1. `src/anglerfish/deployers/<type>.py` implementing `BaseDeployer`
2. Dataclass in `models.py`
3. Register in `_TEMPLATE_SCHEMA` (`templates.py`)
4. Wire into `cli/_main.py`, `cli/deploy.py`, `cli/prompts.py`
5. Unit tests in `tests/test_<type>_deployer.py`
6. At least one bundled template in `src/anglerfish/templates/<type>/`
7. Update public docs and permissions guidance in the same change

## Things to never commit

- `.env`, credentials, tenant IDs, app secrets
- Certificate material: `*.pfx`, `*.pem`, `*.key`, `*.crt`
- Real audit log captures, mailbox IDs, or message IDs from live tenants
- Anything matched by `.gitignore`

If you find any of the above in a diff you're about to commit, stop and flag it.

## Security reporting

Vulnerabilities go through a GitHub Security Advisory (private), not public issues. Don't include exploit details in public-facing files.

## When you change behavior

- Add or update a test in the matching `tests/test_<module>.py`.
- Update `CHANGELOG.md` under `[Unreleased]`.
- If you change the command surface, update `docs/architecture.md` (Command Surface section) and the relevant section of `README.md`.
- If you change auth or permissions, update `docs/threat-model.md` and the permissions guidance in `README.md`.

## Reference docs in this repo

- `README.md` — user-facing intro, demos, evidence flow
- `CONTRIBUTING.md` — dev setup, template authoring, PR rules
- `docs/architecture.md` — layered overview, command surface
- `docs/threat-model.md` — assumptions, UAL latency, detection model
- `docs/blackhat-europe-demo-script.md` — reviewer evidence script
- `docs/sentinel-kql.md` — KQL for Sentinel-side correlation
