from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from ai_dev_tools.community.builder import build_community_payload
from collector.app.main import app
from collector.app.storage import check_db_health


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _valid_basic_payload() -> dict[str, Any]:
    return dict(build_community_payload("basic", sample=True))


def test_unexpected_field_does_not_leak_raw_key_or_path(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    payload = _valid_basic_payload()
    secret_key = "C:\\Users\\Mateusz\\SecretRepo"
    payload[secret_key] = "secret_value"

    resp = client.post("/v1/events", json=payload)
    assert resp.status_code == 400
    assert resp.json() == {"status": "rejected", "error": "validation_failed"}

    # Assert raw sensitive strings are NEVER logged
    assert "SecretRepo" not in caplog.text
    assert "Mateusz" not in caplog.text
    assert "Users" not in caplog.text
    assert "secret_value" not in caplog.text

    # Assert controlled error category IS logged
    assert "Rejected telemetry event: unexpected_keys" in caplog.text


def test_invalid_model_does_not_leak_raw_model_name(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    payload = build_community_payload("research", sample=True)
    secret_model = "private-customer-model-secret"
    payload["model"] = secret_model

    resp = client.post("/v1/events", json=payload)
    assert resp.status_code == 400
    assert resp.json() == {"status": "rejected", "error": "validation_failed"}

    # Assert raw model string is NEVER logged
    assert secret_model not in caplog.text
    assert "Rejected telemetry event: invalid_model" in caplog.text


def test_invalid_telemetry_level_does_not_leak_email_or_user_string(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    payload = _valid_basic_payload()
    secret_email = "john.doe@confidential-corp.example.com"
    payload["telemetry_level"] = secret_email

    resp = client.post("/v1/events", json=payload)
    assert resp.status_code == 400
    assert resp.json() == {"status": "rejected", "error": "validation_failed"}

    # Assert raw string is NEVER logged
    assert secret_email not in caplog.text
    assert "confidential-corp" not in caplog.text
    assert "Rejected telemetry event: invalid_telemetry_level" in caplog.text


def test_malformed_json_does_not_leak_payload_content(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    secret_token = "sk-proj-VERY_CONFIDENTIAL_TOKEN_982734"
    malformed_body = f'{{"key": "{secret_token}", unclosed'

    resp = client.post(
        "/v1/events",
        content=malformed_body.encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json() == {"status": "rejected", "error": "validation_failed"}

    # Assert secret token is NEVER logged
    assert secret_token not in caplog.text
    assert "Rejected telemetry event: malformed_json" in caplog.text


def test_non_dict_payload_does_not_leak_raw_content(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    secret_string = "SUPER_SECRET_ARRAY_ENTRY_48291"
    raw_body = json.dumps([secret_string, "item2"])

    resp = client.post(
        "/v1/events",
        content=raw_body.encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json() == {"status": "rejected", "error": "validation_failed"}

    assert secret_string not in caplog.text
    assert "Rejected telemetry event: payload_not_dict" in caplog.text


def test_db_insert_exception_does_not_leak_sql_or_credentials(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR)
    payload = _valid_basic_payload()
    secret_credential = "POSTGRES_PASSWORD_TOP_SECRET_981273"

    class CustomDBException(Exception):
        pass

    with patch(
        "collector.app.main.insert_telemetry_event",
        side_effect=CustomDBException(f"Failed to connect to db with pass={secret_credential}"),
    ):
        resp = client.post("/v1/events", json=payload)
        assert resp.status_code == 500
        assert resp.json() == {"status": "error", "error": "storage_failed"}

    # Assert sensitive exception message/credentials are NEVER logged
    assert secret_credential not in caplog.text
    assert "CustomDBException" in caplog.text
    assert "Telemetry storage failure: CustomDBException" in caplog.text


def test_db_readiness_exception_does_not_leak_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    secret_db_info = "postgresql+psycopg://telemetry_user:SUPER_SECRET_PASS_99182@db:5432"

    class MockEngine:
        def connect(self) -> Any:
            raise RuntimeError(f"Connection failed to {secret_db_info}")

    is_healthy = check_db_health(target_engine=MockEngine())
    assert is_healthy is False

    # Assert credentials are NEVER logged
    assert secret_db_info not in caplog.text
    assert "SUPER_SECRET_PASS_99182" not in caplog.text
    assert "Database readiness check failed: RuntimeError" in caplog.text
