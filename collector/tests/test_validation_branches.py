from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ai_dev_tools.community.builder import build_community_payload
from collector.app.validation import ValidationError, validate_ingest_payload


def test_main_readiness_probe(client: TestClient) -> None:
    # Ready 200
    res = client.get("/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ready", "database": "connected"}

    # Ready 503 on database failure
    with patch("collector.app.main.check_db_health", return_value=False):
        res_fail = client.get("/ready")
        assert res_fail.status_code == 503
        assert res_fail.json() == {"status": "degraded", "error": "database_unavailable"}


def test_main_non_integer_content_length(client: TestClient) -> None:
    res = client.post(
        "/v1/events",
        content=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": "invalid-length"},
    )
    assert res.status_code == 400
    assert res.json() == {"status": "rejected", "error": "validation_failed"}


def test_main_non_dict_json_payload(client: TestClient) -> None:
    res = client.post(
        "/v1/events",
        json=[1, 2, 3],
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 400
    assert res.json() == {"status": "rejected", "error": "validation_failed"}


def test_main_storage_failure_returns_500(client: TestClient) -> None:
    payload = build_community_payload("basic", sample=True)
    with patch(
        "collector.app.main.insert_telemetry_event", side_effect=RuntimeError("Disk failure")
    ):
        res = client.post("/v1/events", json=payload)
        assert res.status_code == 500
        assert res.json() == {"status": "error", "error": "storage_failed"}


def test_main_storage_returns_false_returns_400(client: TestClient) -> None:
    payload = build_community_payload("basic", sample=True)
    with patch("collector.app.main.insert_telemetry_event", return_value=(False, False)):
        res = client.post("/v1/events", json=payload)
        assert res.status_code == 400


def test_validation_various_enums_and_invariants() -> None:
    base = build_community_payload("research", sample=True)

    # 1. Invalid telemetry_level
    with pytest.raises(ValidationError, match="Invalid telemetry_level"):
        validate_ingest_payload({**base, "telemetry_level": "super_admin"})

    # 2. Invalid non-dict
    with pytest.raises(ValidationError, match="Payload must be a JSON object"):
        validate_ingest_payload("string")

    # 3. Invalid enums
    enums_to_test = [
        ("task_kind", "hack"),
        ("validation_result", "maybe"),
        ("task_outcome", "pending"),
        ("repo_files_bucket", "huge"),
        ("repo_size_bucket", "gigabytes"),
        ("ai_client", "unknown_vendor"),
        ("model", "proprietary_closed_v99"),
        ("command_name", "rm_rf"),
        ("command_category", "destruction"),
        ("command_outcome", "exploded"),
        ("reason_code", "unknown_reason_xyz"),
        ("retrieval_reason_code", "quantum_lookup"),
    ]
    for key, bad_val in enums_to_test:
        with pytest.raises(ValidationError):
            validate_ingest_payload({**base, key: bad_val})

    # 4. Selection reason codes & language families
    with pytest.raises(ValidationError, match="selection_reason_codes must be a list"):
        validate_ingest_payload({**base, "selection_reason_codes": "single_code"})

    with pytest.raises(ValidationError, match="Invalid selection_reason_code"):
        validate_ingest_payload({**base, "selection_reason_codes": ["invalid_code_xyz"]})

    with pytest.raises(ValidationError, match="language_families must be a list"):
        validate_ingest_payload({**base, "language_families": "python"})

    with pytest.raises(ValidationError, match="Invalid language family"):
        validate_ingest_payload({**base, "language_families": ["klingon"]})

    # 5. Token consistency bounds
    with pytest.raises(ValidationError, match="cached_input_tokens .* cannot exceed input_tokens"):
        validate_ingest_payload({**base, "input_tokens": 100, "cached_input_tokens": 200})

    with pytest.raises(ValidationError, match="total_tokens .* cannot be less than input_tokens"):
        validate_ingest_payload(
            {**base, "input_tokens": 500, "cached_input_tokens": 0, "total_tokens": 400}
        )

    with pytest.raises(ValidationError, match="total_tokens .* cannot be less than output_tokens"):
        validate_ingest_payload(
            {
                **base,
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 500,
                "total_tokens": 400,
            }
        )

    with pytest.raises(
        ValidationError, match="total_tokens .* cannot be less than input \\+ output"
    ):
        validate_ingest_payload(
            {
                **base,
                "input_tokens": 300,
                "cached_input_tokens": 0,
                "output_tokens": 300,
                "total_tokens": 500,
            }
        )

    # 6. Numeric limits & bounds
    with pytest.raises(ValidationError, match="must be an integer"):
        validate_ingest_payload({**base, "input_tokens": "1000"})

    with pytest.raises(ValidationError, match="must be between 0 and"):
        validate_ingest_payload({**base, "input_tokens": -5})

    with pytest.raises(ValidationError, match="must be between 0 and"):
        validate_ingest_payload({**base, "input_tokens": 200_000_000})

    with pytest.raises(ValidationError, match="must be a finite number between 0.0 and 1.0"):
        validate_ingest_payload({**base, "cache_hit_ratio": 1.5})

    with pytest.raises(ValidationError, match="must be a finite number between 0.0 and 1.0"):
        validate_ingest_payload({**base, "cache_hit_ratio": -0.1})

    with pytest.raises(ValidationError, match="must be a number or None"):
        validate_ingest_payload({**base, "cache_hit_ratio": True})

    with pytest.raises(ValidationError, match="must be a finite number"):
        validate_ingest_payload({**base, "duration_seconds": -5.0})

    with pytest.raises(ValidationError, match="must be a finite number"):
        validate_ingest_payload({**base, "duration_seconds": 1_000_000.0})
