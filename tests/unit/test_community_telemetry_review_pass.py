from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_dev_tools.community.builder import (
    build_community_payload,
)
from ai_dev_tools.community.config import (
    CONFIG_FILENAME,
    get_user_config_dir,
    load_community_config,
    save_community_config,
)
from ai_dev_tools.community.queue import (
    enqueue_event,
    list_queued_events,
    queue_size,
)
from ai_dev_tools.community.schema import (
    SELECTION_REASON_CODES,
    validate_community_payload,
)
from ai_dev_tools.community.service import (
    disable_telemetry,
    enable_telemetry,
    preview_telemetry,
    start_background_autoflush,
    wait_for_autoflush,
)
from ai_dev_tools.community.transport import send_event
from ai_dev_tools.models.report import Report
from ai_dev_tools.telemetry import record_usage


@pytest.fixture(autouse=True)
def isolate_telemetry_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / 'config'
    data_dir = tmp_path / 'data'
    monkeypatch.setenv('AI_DEV_COMMUNITY_TELEMETRY_CONFIG_DIR', str(config_dir))
    monkeypatch.setenv('AI_DEV_COMMUNITY_TELEMETRY_DATA_DIR', str(data_dir))
    monkeypatch.delenv('AI_DEV_COMMUNITY_TELEMETRY_ENDPOINT', raising=False)


# 1. Transport must reject invalid payload BEFORE network call
def test_transport_rejects_invalid_payload_without_network() -> None:
    valid = build_community_payload('basic', sample=True)

    payload_extra = dict(valid)
    payload_extra['forbidden_field'] = 'leak'

    payload_bad_enum = dict(valid)
    payload_bad_enum['command_outcome'] = 'exploded'

    payload_missing = dict(valid)
    del payload_missing['os_family']

    with patch('urllib.request.urlopen') as mock_urlopen:
        for bad_payload in (payload_extra, payload_bad_enum, payload_missing):
            result = send_event('http://127.0.0.1:8000/events', bad_payload)
            assert not result.success
            assert result.retryable is False
            assert 'validation failed' in result.message.lower()

        mock_urlopen.assert_not_called()


# 2. Selection reason code closed enum & privacy regression
def test_selection_reason_code_closed_enum_and_privacy_regression(tmp_path: Path) -> None:
    secret_path = 'C:\\Users\\Mateusz\\SecretProject'
    report = Report(command='context build', project_root=tmp_path)
    report.summary = {
        'selected_files': [
            {'path': 'main.py', 'reason_code': secret_path},
            {'path': 'lib.py', 'reason_code': 'CHANGED_FILE'},
            {'path': 'test.py', 'reason_code': 'unknown_code_xyz'},
        ]
    }

    payload = build_community_payload('research', report=report, project_root=tmp_path)
    serialized = json.dumps(payload)

    assert secret_path not in serialized
    assert 'SecretProject' not in serialized
    assert 'unknown_code_xyz' not in serialized

    assert payload['selection_reason_codes'] == ['CHANGED_FILE', 'UNKNOWN']
    for code in payload['selection_reason_codes']:
        assert code in SELECTION_REASON_CODES


# 3. Arbitrary internal report fields never enter payload
def test_internal_report_fields_never_enter_payload(tmp_path: Path) -> None:
    report = Report(command='scan', project_root=tmp_path)
    report.summary = {
        'internal_debug_stack': ['frame1', 'frame2'],
        'secret_token': 'sk-1234567890',
        'user_environment': {'USER': 'john', 'SSH_AUTH_SOCK': '/tmp/ssh.sock'},
    }

    payload_basic = build_community_payload('basic', report=report, project_root=tmp_path)
    payload_research = build_community_payload('research', report=report, project_root=tmp_path)

    for p in (payload_basic, payload_research):
        ser = json.dumps(p)
        assert 'internal_debug_stack' not in ser
        assert 'secret_token' not in ser
        assert 'SSH_AUTH_SOCK' not in ser
        validate_community_payload(p)


# 4. MCP record_usage feeds RESEARCH community telemetry
def test_mcp_record_usage_feeds_research_telemetry(tmp_path: Path) -> None:
    enable_telemetry('research')
    assert queue_size() == 0

    record_usage(
        tmp_path,
        client='claude',
        input_tokens=1500,
        cached_input_tokens=300,
        output_tokens=450,
        reasoning_tokens=120,
        model='claude-3-5-sonnet',
        task_kind='bugfix',
        quality_passed=True,
        duration_seconds=2.4,
        request_id='secret_req_999',
        source_id='secret_src_888',
        phase='secret_phase_777',
        tool_name='secret_tool_666',
    )

    events = list_queued_events()
    assert len(events) == 1
    _, payload = events[0]

    assert payload['event_type'] == 'provider_usage'
    assert payload['telemetry_level'] == 'research'
    assert payload['ai_client'] == 'claude'
    assert payload['model'] == 'claude-3-5-sonnet'
    assert payload['task_kind'] == 'bugfix'
    assert payload['input_tokens'] == 1500
    assert payload['cached_input_tokens'] == 300
    assert payload['output_tokens'] == 450
    assert payload['reasoning_tokens'] == 120
    assert payload['total_tokens'] == 1950
    assert payload['validation_result'] == 'passed'
    assert payload['task_outcome'] == 'success'

    serialized = json.dumps(payload)
    for forbidden in (
        'secret_req_999',
        'secret_src_888',
        'secret_phase_777',
        'secret_tool_666',
    ):
        assert forbidden not in serialized

    for forbidden_key in (
        'request_id',
        'source_id',
        'phase',
        'tool_name',
        'session_id',
        'path',
        'pricing',
    ):
        assert forbidden_key not in payload

    validate_community_payload(payload)


# 5. MCP record_usage under BASIC and OFF produces zero community events
def test_mcp_record_usage_under_basic_and_off_produces_zero_events(tmp_path: Path) -> None:
    enable_telemetry('basic')
    assert queue_size() == 0

    record_usage(
        tmp_path,
        client='cursor',
        input_tokens=500,
        output_tokens=200,
        model='gpt-4o',
    )
    assert queue_size() == 0

    disable_telemetry()
    record_usage(
        tmp_path,
        client='gemini',
        input_tokens=800,
        output_tokens=300,
        model='gemini-2.0-flash',
    )
    assert queue_size() == 0


# 6. Preview: actual repository data vs --sample
def test_preview_semantics_actual_vs_sample(tmp_path: Path) -> None:
    actual_report = preview_telemetry(level='research', project_root=tmp_path, sample=False)
    assert actual_report.summary['mode'] == 'ACTUAL REPOSITORY PREVIEW'
    actual_payload = actual_report.summary['payload']

    assert actual_payload['input_tokens'] is None
    assert actual_payload['output_tokens'] is None
    assert actual_payload['ai_client'] == 'unknown'
    assert actual_payload['model'] == 'unknown'
    assert actual_payload['task_kind'] == 'unknown'
    assert actual_payload['context_candidate_tokens'] is None
    assert actual_payload['tool_call_count'] is None
    assert queue_size() == 0

    sample_report = preview_telemetry(level='research', project_root=tmp_path, sample=True)
    assert sample_report.summary['mode'] == 'SAMPLE / EXAMPLE — NOT QUEUED, NOT SENT'
    sample_payload = sample_report.summary['payload']

    assert sample_payload['input_tokens'] == 1500
    assert sample_payload['model'] == 'claude-3-5-sonnet'
    assert queue_size() == 0


# 7. Endpoint precedence and migration handling
def test_endpoint_migration_and_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = get_user_config_dir() / CONFIG_FILENAME
    config_file.parent.mkdir(parents=True, exist_ok=True)

    config_file.write_text(
        json.dumps({'telemetry_level': 'research', 'endpoint': ''}),
        encoding='utf-8',
    )

    simulated_default = 'https://telemetry.future-production.org/v1/ingest'
    cfg = load_community_config(default_endpoint=simulated_default)
    assert cfg.endpoint == simulated_default
    assert cfg.endpoint_override is None

    save_community_config('research', endpoint='https://user-custom.endpoint.com/events')
    cfg_user = load_community_config(default_endpoint=simulated_default)
    assert cfg_user.endpoint == 'https://user-custom.endpoint.com/events'
    assert cfg_user.endpoint_override == 'https://user-custom.endpoint.com/events'

    monkeypatch.setenv(
        'AI_DEV_COMMUNITY_TELEMETRY_ENDPOINT', 'https://env-override.endpoint.com/events'
    )
    cfg_env = load_community_config(default_endpoint=simulated_default)
    assert cfg_env.endpoint == 'https://env-override.endpoint.com/events'


# 8. Disabling telemetry clears queue immediately
def test_disabling_telemetry_clears_queue() -> None:
    enable_telemetry('basic')
    for _ in range(3):
        payload = build_community_payload('basic', sample=True)
        enqueue_event(payload)

    assert queue_size() == 3
    disable_telemetry()
    assert queue_size() == 0


# 9. Background autoflush lifecycle
def test_background_autoflush_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    enable_telemetry('basic')
    save_community_config('basic', endpoint='http://127.0.0.1:8000/events')

    payload = build_community_payload('basic', sample=True)
    enqueue_event(payload)
    assert queue_size() == 1

    with patch('ai_dev_tools.community.service.send_event') as mock_send:
        from ai_dev_tools.community.transport import UploadResult

        mock_send.return_value = UploadResult(success=True, status_code=200)

        t = start_background_autoflush()
        assert t is not None
        wait_for_autoflush(timeout=1.0)
        assert not t.is_alive()
        assert queue_size() == 0
        mock_send.assert_called_once()
