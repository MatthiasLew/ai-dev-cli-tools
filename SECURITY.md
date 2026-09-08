# Security Policy

## Supported versions

Security fixes are provided for the latest stable release only. Users should upgrade to the
latest patch version before reporting an issue that may already be fixed. Pre-releases and source
checkouts are supported only for reproducing a report against the current `main` branch.

| Version | Supported |
| --- | --- |
| 1.2.x latest patch | Yes |
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
caches, telemetry, and MCP communication remain local by default. The project intentionally does
not commit, push, merge, deploy, transmit source to a remote model, install global tools, or kill
unrelated processes.

Secret masking is a defense-in-depth control, not permission to process arbitrary secrets. Review
generated reports before sharing them, keep `.ai/` state private, and use least-privilege execution
policies for MCP clients and CI.
