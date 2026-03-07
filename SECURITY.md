# Security Policy

## Reporting a Vulnerability

To report a security vulnerability, please open a
[GitHub Security Advisory](https://github.com/vortacity/anglerfish/security/advisories/new)
(private) rather than a public issue.

Do **not** include exploit details, credentials, tenant identifiers, or
proof-of-concept payloads in public issue reports.

## Scope

Anglerfish interacts with Microsoft 365 tenants via the Graph API and the
Office 365 Management Activity API. Security reports are welcome for:

- Authentication credential handling (secret/certificate leakage, insecure storage)
- Graph API permission escalation or unintended scope usage
- Deployment record data exposure (artifact IDs, tenant metadata)
- Template injection or variable substitution bypass
- CLI argument injection or unsafe shell expansion
- Dependency vulnerabilities in runtime packages

## Responsible Disclosure

We aim to acknowledge reports within 72 hours and provide a fix or mitigation
plan within 14 days for confirmed vulnerabilities. We will coordinate public
disclosure timing with the reporter.

## Safe Defaults

Anglerfish is designed with the following safety principles:

- **No auto-retry on write operations** — POST/PUT calls to Graph do not
  automatically retry to prevent duplicate side effects.
- **Confirmation prompts default to No** — interactive deployment requires
  explicit opt-in before any write operation.
- **Atomic file writes** — deployment records and monitor state use
  temp-file + `os.replace` to prevent partial writes.
- **No embedded secrets** — all credentials are supplied via environment
  variables; no secrets are stored in code, templates, or deployment records.
