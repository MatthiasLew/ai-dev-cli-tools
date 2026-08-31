# Observation lifecycle

`ai-dev feedback` maintains a local, provider-neutral observation lifecycle for long-running agent
sessions. The goal is to keep the evidence needed for the next decision without repeatedly sending
superseded tool output.

## Storage

The current lifecycle manifest is `.ai/cache/observations.json`. When a new, different feedback
observation replaces the previous one, the previous structured observation is stored by content
fingerprint under `.ai/cache/evidence/observation-<id>.json`. These files remain local, are secret
masked before hashing or writing, and contain no timestamps.

The manifest keeps at most 20 compact references. Repeated identical observations increment
`duplicate_observations_suppressed` instead of creating duplicate evidence.

## Retention rules

The current observation remains inline and reports why it was retained:

- `current_failure` keeps the current failure signature, first failure, command, and check result;
- `unresolved_warning` keeps current partial/flaky warning evidence;
- `final_verification` keeps the latest successful verification;
- `current_observation` is the conservative fallback for another status.

A superseded observation is replaced in the session manifest by its stable evidence ID,
SHA-256 fingerprint, original character size, status, failure signatures, reason code, and exact
retrieval command. `referenced_chars_avoided` estimates how much historical observation text does
not need to be repeated in the active session payload.

Expand one referenced observation without replaying every old log:

```bash
ai-dev explain observation:<id> --tail 100 --json
```

The lifecycle complements full logs and normal report artifacts. It does not delete validation
logs, hide the current failure, or treat a partial/flaky result as clean final verification.

## Session delta receipts

The observation archive handles history; the `feedback` session delta handles an identical current
success repeated across agent turns after the client explicitly acknowledges the fingerprint from
the response it consumed. A local fingerprint combines the normalized task scope,
changed-file content hashes, semantic validation results, and context ID. When it matches the prior
session, full validation results, selected context content, and the repeated current observation
become compact receipts with counts and an `ai-dev explain` command. Timing and cache execution
labels do not invalidate the semantic fingerprint. Any changed content, result, failure, warning,
missing acknowledgement, or mismatched fingerprint fails closed to the full payload. CLI clients
pass `--ack-state <fingerprint>` and MCP clients pass `acknowledged_state`; use `--no-delta` or MCP
`delta=false` to opt out explicitly.
