# Safe semantic compression evaluation

The evaluated decision is to support only opt-in, deterministic natural-language deduplication.
Model-based paraphrasing is not enabled: its token savings do not justify the risk of changing code,
commands, locations, hashes, failure details, or final verification evidence.

Use:

```bash
ai-dev context build --compression conservative
```

The conservative mode applies two transformations:

- remove later exact duplicate prose paragraphs in Markdown, reStructuredText, AsciiDoc, and text;
- collapse consecutive identical natural-language `.log` lines into one line with a repeat count.

Fenced Markdown code is copied exactly. Source code, JSON/JSONL, configuration, diffs, patches,
shell scripts, SQL, commands, locations, hashes, changed symbols, current errors, validation plans,
commit history, and verification evidence are excluded. Log lines resembling stack frames, paths
with line numbers, hashes, commands, JSON, or code are also excluded.

Every run fingerprints all protected content before and after compression and fails closed if the
fingerprints differ. Reports list compressed/skipped files, original/final characters, characters
saved, methods, reason codes, preserved categories, and `protected_integrity`. The original remains
available locally at its source path and through normal file evidence expansion.

This is deliberately narrower than learned semantic compression. A future model-based compressor
would need separate correctness benchmarks, source retention, auditable diffs, and explicit user
consent before it could replace this deterministic policy.