# Security Policy

## Supported versions

Security fixes are provided for the latest stable release only. Users should upgrade to the
latest patch version before reporting an issue that may already be fixed. Pre-releases and source
checkouts are supported only for reproducing a report against the current `main` branch.

| Version | Supported |
| --- | --- |
| 1.3.x latest patch | Yes |
| Earlier releases | No |

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private vulnerability
reporting form in the repository Security tab when available, or contact the repository owner
privately through the address associated with the published package.

Include the affected version or commit, operating system, minimal reproduction, expected security
property, observed impact, and whether the report contains secrets. Do not include real
credentials, private source code, or customer data. Use synthetic evidence wherever possible.

The maintainer aims to acknowledge a report within 7 days and provide an initial assessment within
14 days. Timelines for a fix and coordinated disclosure depend on severity and reproducibility.

## Security boundaries

`ai-dev` analyzes repositories and runs explicitly selected local development commands. Reports,
caches, local logs, and MCP communication remain strictly local by default (`telemetry_level = "off"`).
The project intentionally does not commit, push, merge, deploy, transmit source code to remote models,
install global tools, or kill unrelated processes.

### Community Telemetry boundary

Community Telemetry is strictly voluntary, privacy-preserving, and **OFF by default**:
- **Explicit Opt-in**: Telemetry is never transmitted unless a user explicitly enables it via `ai-dev telemetry sharing enable basic` or `ai-dev telemetry sharing enable research`.
- **Strict Allowlist Schema**: Only predefined scalar metrics are permitted. Source code, file names, directory paths, repository names, prompts, model completions, user identifiers, machine IDs, and environment secrets are never collected or transmitted.
- **Privacy-Preserving Edge & Storage**: Ingested events are deduplicated by random UUIDv4 (`event_id`). Client IP addresses are never recorded in the telemetry database and are discarded from reverse proxy access logs for `/v1/events` (transient IP is used solely in-memory for bounded sliding-window rate limiting).
- **User Control & Transparency**: Users can preview queued events with `ai-dev telemetry sharing preview`, flush them manually, or disable sharing at any time with `ai-dev telemetry sharing disable`, which purges any spooled local events immediately.

Secret masking is a defense-in-depth control, not permission to process arbitrary secrets. Review
generated reports before sharing them, keep `.ai/` state private, and use least-privilege execution
policies for MCP clients and CI.
