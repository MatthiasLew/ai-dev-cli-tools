from __future__ import annotations

import logging
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ai_dev_tools.community.builder import build_community_payload
from collector.app.models import TelemetryEvent


def test_forbidden_sensitive_fields_rejected_fail_closed(
    client: TestClient,
    test_db_session: sessionmaker[Session],
    caplog: Any,
) -> None:
    base = build_community_payload("research", sample=True)

    sensitive_injections: list[tuple[str, dict[str, Any]]] = [
        ("prompt injection", {**base, "prompt": "Explain this secret algorithm"}),
        ("source code leak", {**base, "source_code": "def secret_login(): return True"}),
        ("repository name leak", {**base, "repository_name": "company-private-repo"}),
        ("file path leak", {**base, "file_path": "/home/user/workspace/secret.py"}),
        ("username leak", {**base, "username": "admin_root"}),
        ("email address leak", {**base, "email": "employee@corporate.com"}),
        ("api key leak", {**base, "api_key": "sk-proj-super-secret-key-123"}),
        ("arbitrary dict metadata", {**base, "metadata": {"repo": "secret"}}),
    ]

    with caplog.at_level(logging.INFO):
        for label, payload in sensitive_injections:
            resp = client.post("/v1/events", json=payload)
            assert resp.status_code == 400, f"Sensitive payload accepted for {label}"
            assert resp.json() == {"status": "rejected", "error": "validation_failed"}

    # Confirm database has ZERO records
    with test_db_session() as session:
        count = len(list(session.scalars(select(TelemetryEvent.event_id)).all()))
        assert count == 0

    # Confirm logs contain NONE of the injected sensitive values
    all_logs = " ".join(record.message for record in caplog.records)
    for forbidden in (
        "Explain this secret algorithm",
        "def secret_login",
        "company-private-repo",
        "/home/user/workspace",
        "employee@corporate.com",
        "sk-proj-super-secret",
    ):
        assert forbidden not in all_logs
