# Adding a Detector

1. Add a module under `src/ai_dev_tools/detectors/`.
2. Return a `Report` with deterministic keys in `summary`.
3. Avoid network calls and destructive operations.
4. Add unit tests with temporary fixture projects.
5. Wire the detector from `cli.py` only after the report schema is stable.
