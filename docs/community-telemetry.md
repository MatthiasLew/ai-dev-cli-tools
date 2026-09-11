# Community Telemetry in ai-dev

Community Telemetry is an explicit, opt-in, privacy-preserving telemetry layer designed to gather real-world benchmark and workflow performance metrics from `ai-dev` users ahead of **Agent Benchmark V2**.

---

## Key Principles & Guarantees

1. **Default OFF**: Community Telemetry is completely disabled by default. Installing or running `ai-dev` never enables it automatically.
2. **Explicit Opt-in**: The user consciously chooses whether to enable telemetry (`basic` or `research`) or leave it disabled (`off`).
3. **No Dark Patterns & No Nagging**: The CLI never prompts or nags you during installation, first run, or daily usage.
4. **No Persistent User Tracking**:
   - Zero `user_id` or persistent `installation_id`.
   - Zero machine fingerprints, hashed hostnames, hashed repository names, or MAC addresses.
   - Each event contains only a randomly generated `event_id` (UUIDv4) used exclusively for de-duplication.
5. **Allowlist Construction, Not Redaction**:
   - Payloads are constructed from scratch using strictly allowlisted scalar metrics (enums, bucketed counts, rounded durations).
   - We do not rely on heuristic text filtering or regex redaction of arbitrary user content.
6. **Decoupled from Local Telemetry**:
   - Existing local telemetry and token-efficiency features remain strictly local in `.ai/token-efficiency/`.
   - Turning Community Telemetry off never disables local token-efficiency accounting, reports, or benchmarks.
7. **Non-Blocking Network & Bounded Shutdown**:
   - Network uploads are not part of the command's critical execution path.
   - Background upload requests run in a daemon thread; on CLI command or MCP server termination, waiting for an opportunistic background flush is strictly bounded to 50 ms (`wait_for_autoflush(0.05)`).
   - If an upload takes longer or fails due to network/collector issues, the daemon thread is detached upon timeout and the command exits immediately.
   - Network errors, timeouts, or collector outages **never** affect command status or exit codes.

---

## What is NEVER Collected

Community Telemetry strictly forbids and never includes:
- Source code, file contents, diffs, or patch contents
- Prompts (user, developer, or system prompts)
- Model responses, completions, or reasoning text
- Test outputs, compiler diagnostics, or logs
- Stack traces containing local paths
- Repository names, repository URLs, git remotes, branch names, or commit messages
- File names, relative paths, absolute paths, or current working directory (`cwd`)
- Hostnames, usernames, or email addresses
- API keys, authentication tokens, credentials, or environment variables
- IP addresses in payload fields
- Raw CLI arguments or task prompt text
- Issue, PR, or project titles
- Arbitrary metadata from plugins, tools, or providers

---

## Telemetry Levels

### 1. OFF (Default)
- No events are generated, queued, or sent.
- Zero network requests are made.
- Zero local queue files are written.
- Local reports and `.ai/` files function normally.

### 2. BASIC
Minimal operational metrics concerning `ai-dev` execution itself.

#### Schema (`schema_version = 1`):
| Field | Type | Description |
|---|---|---|
| `schema_version` | integer | Always `1` |
| `event_id` | string (UUIDv4) | Random UUID generated per event for deduplication |
| `event_type` | string | Closed enum: `"command_run"` or `"provider_usage"` |
| `telemetry_level` | string | `"basic"` |
| `ai_dev_version` | string | Package version (e.g. `"1.2.2"`) |
| `os_family` | string | Closed enum: `"windows"`, `"linux"`, `"macos"`, `"other"` |
| `python_version` | string | Major.minor (e.g. `"3.12"`) |
| `command_name` | string | Closed enum: `"check"`, `"scan"`, `"context"`, `"mcp"`, etc. |
| `command_category` | string | Closed enum: `"analysis"`, `"execution"`, `"quality"`, `"context"`, `"benchmark"`, `"telemetry"`, `"agent"`, `"runtime"`, `"other"` |
| `command_outcome` | string | Closed enum: `"success"`, `"partial"`, `"failure"` |
| `reason_code` | string or null | Controlled error reason code if available (e.g. `"NONE"`, `"TIMEOUT"`, `"TOKEN_BUDGET_EXCEEDED"`) |
| `duration_bucket` | string | Coarse bucket: `"<100ms"`, `"100ms-500ms"`, `"500ms-1s"`, `"1s-5s"`, `"5s-30s"`, `"30s-120s"`, `"120s+"` |
| `duration_seconds` | float or null | Bounded float rounded to 3 decimal places |
| `cache_hit` | boolean or null | Cache hit status if applicable |
| `timestamp_hour` | string (ISO 8601) | Coarse UTC hour bucket (e.g. `"2026-09-11T12:00:00Z"`) |

### 3. RESEARCH
Includes all **BASIC** fields plus aggregated efficiency and workflow metrics to evaluate agent performance on real-world coding tasks.

#### Additional Fields in RESEARCH:
| Field | Type | Description |
|---|---|---|
| `ai_client` | string | Closed enum: `"codex"`, `"claude"`, `"cursor"`, `"gemini"`, `"other"`, `"unknown"` |
| `model` | string | Public model family (`"gpt-4o"`, `"claude-3-5-sonnet"`, `"gemini-1.5-pro"`) or `"other"`, `"local"`, `"unknown"` |
| `task_kind` | string | Closed enum: `"bugfix"`, `"feature"`, `"refactor"`, `"test"`, `"documentation"`, `"performance"`, `"security"`, `"investigation"`, `"other"`, `"unknown"` |
| `language_families` | list of strings | Standardized language categories present (e.g. `["python", "typescript"]`). Never file names or paths. |
| `repo_files_bucket` | string | Coarse bucket: `"1-50"`, `"51-200"`, `"201-1000"`, `"1001-5000"`, `"5000+"` |
| `repo_size_bucket` | string | Coarse bucket: `"<1MB"`, `"1-10MB"`, `"10-50MB"`, `"50-250MB"`, `"250MB+"` |
| `context_candidate_tokens` | integer or null | Number of tokens considered by context engine |
| `context_delivered_tokens` | integer or null | Number of tokens actually included in context |
| `context_budget` | integer or null | Token budget configured for the run |
| `input_tokens` | integer or null | Total input tokens reported by provider |
| `cached_input_tokens` | integer or null | Cached input tokens reported by provider |
| `output_tokens` | integer or null | Output tokens reported by provider |
| `reasoning_tokens` | integer or null | Reasoning tokens reported by provider |
| `total_tokens` | integer or null | Sum of input and output tokens |
| `tool_call_count` | integer or null | Number of tool calls observed |
| `files_considered` | integer or null | Number of candidate files examined |
| `files_selected` | integer or null | Number of files included in context |
| `files_omitted` | integer or null | Number of files filtered out or omitted |
| `cache_hit_ratio` | float or null | Hit ratio rounded to 2 decimals |
| `semantic_cache_reuse` | float or null | Semantic cache reuse ratio |
| `local_overhead_seconds` | float or null | Internal execution overhead rounded to 3 decimals |
| `total_wall_time_seconds` | float or null | Overall wall time rounded to 3 decimals |
| `validation_result` | string | Closed enum: `"passed"`, `"failed"`, `"unknown"` |
| `task_outcome` | string | Closed enum: `"success"`, `"failure"`, `"unknown"` |
| `retrieval_reason_code` | string or null | Controlled retrieval strategy code |
| `selection_reason_codes` | list of strings or null | Safe strategy codes from closed enum (e.g. `["CHANGED_FILE", "USER_INCLUDE"]`) |
| `origin` | string or null | Controlled origin enum for provider events: `"mcp"`, `"import"`, `"unknown"`, or `null` for commands |

#### Provider Usage Events (`event_type: "provider_usage"`)
When `RESEARCH` telemetry is active, local provider metrics recorded via MCP tools (`record_usage`) or CLI import (`ai-dev telemetry import`) generate an additional `provider_usage` event.

- **Trigger Sources**:
  - MCP `record_usage` tool invocation: records origin `"mcp"`, `command_name="mcp"`.
  - CLI `ai-dev telemetry import`: records origin `"import"`, `command_name="telemetry"`.
- **Fields Included**:
  - `event_id` (UUIDv4), `schema_version=1`, `telemetry_level="research"`, `event_type="provider_usage"`
  - `ai_client`, `model` (sanitized public or "local"/"other"/"unknown"), `task_kind`
  - Token counts (`input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_tokens`, `total_tokens`)
  - `duration_seconds` and `total_wall_time_seconds` (if measured)
  - `validation_result` and `task_outcome`
  - `origin` (`"mcp"` or `"import"`)
- **Strictly Excluded (NEVER collected or sent)**:
  - `request_id`
  - `source_id`
  - `session_id`
  - `phase`
  - `tool_name`
  - `prompt` content or queries
  - `response` text or completions
  - File paths, file names, or code snippets
  - Raw source strings (e.g. `"import:openai"` is mapped strictly to `"import"`)
- **Telemetry Level Guard**:
  - In `OFF`: 0 events generated, 0 queued, 0 sent.
  - In `BASIC`: 0 `provider_usage` events are ever generated or queued (BASIC only records minimal CLI command execution metrics).
  - In `RESEARCH`: events are queued locally and delivered via non-blocking background transport if an endpoint is configured.

---

## Strict Fail-Closed Schema Validation

Before any event is written to queue or sent over the network, `validate_community_payload(payload)` validates all fields:
1. **Top-Level Allowlist**: Unknown or unexpected keys are rejected immediately.
2. **Closed Enums**: Every categorical value (`os_family`, `command_name`, `command_category`, `command_outcome`, `ai_client`, `task_kind`, `validation_result`, `task_outcome`, `repo_files_bucket`, `repo_size_bucket`, `duration_bucket`, `reason_code`, `retrieval_reason_code`, `selection_reason_codes`, `origin`) is strictly validated against a closed allowlist.
3. **Sanitized Models**: Unrecognized or proprietary model strings are mapped to `"other"` or `"unknown"`. Arbitrary model names never pass through.
4. **Format Verification**:
   - `event_id`: must be a valid UUIDv4.
   - `timestamp_hour`: must match exact UTC hour format `YYYY-MM-DDTHH:00:00Z`.
   - `python_version`: must match major.minor format `^3\.\d+$` (e.g. `3.11`, `3.12`).
   - `ai_dev_version`: bounded string up to 32 characters.
5. **Numeric Bounds & Types**:
   - Booleans are rejected as integers (`True` cannot be smuggled as `1`).
   - All token and count fields must be non-negative integers within safe upper bounds (e.g. tokens `<= 100_000_000`, tool calls `<= 100_000`, files `<= 1_000_000`).
   - Ratios (`cache_hit_ratio`, `semantic_cache_reuse`) must be finite numbers between `0.0` and `1.0`.
   - Durations must be finite numbers between `0.0` and `604800.0`. `NaN` and `Infinity` are rejected.
   - Token consistency: `cached_input_tokens <= input_tokens`, `total_tokens >= input_tokens + output_tokens`.
6. **Payload Size Limit**: Serialized JSON must not exceed 32 KB (`32,768 bytes`).
7. **Fail-Closed Transport**: If any field fails validation, `send_event()` aborts before creating any network connection and records 0 HTTP requests.

---

## Configuration & Storage

Community Telemetry settings are stored at the user level, **not** inside project repositories:

- **Windows**: `%LOCALAPPDATA%\ai-dev\community_telemetry.json`
- **Linux**: `$XDG_CONFIG_HOME/ai-dev/community_telemetry.json` (fallback: `~/.config/ai-dev/community_telemetry.json`)
- **macOS**: `~/Library/Application Support/ai-dev/community_telemetry.json` (fallback: `~/.config/ai-dev/community_telemetry.json`)

### Configuration Content
```json
{
  "telemetry_level": "off"
}
```
If a custom endpoint override is specified, it is recorded under `"endpoint_override"`.

### Endpoint Resolution Precedence
1. Environment variable: `AI_DEV_COMMUNITY_TELEMETRY_ENDPOINT` (highest priority)
2. User explicit override: `endpoint_override` in config file
3. Package default: `DEFAULT_COMMUNITY_ENDPOINT` (currently empty — production collector not yet deployed)

---

## Local Queue & Delivery Architecture

When Community Telemetry is enabled (`basic` or `research`):
1. Upon command completion, an event payload is generated via `build_community_payload(...)`.
2. The event is written atomically to a bounded local queue folder (`%LOCALAPPDATA%\ai-dev\community-telemetry\queue\`, etc.).
3. **Bounded Size**: Maximum 1,000 events. If the limit is reached, the oldest events are pruned automatically.
4. **Bounded Age**: Events older than 7 days are automatically pruned.
5. **Bounded Payload**: Any event exceeding 32 KB is rejected.
6. **Opportunistic Background Flush**: When an endpoint is configured, events are dispatched via non-blocking background transport.
7. **Disabling Telemetry**: Running `ai-dev telemetry sharing disable` immediately removes all pending queued events from disk.

---

## Transport & Network Behavior

- **HTTPS Required**: Production endpoints must strictly use `https://`. Plain `http://` is rejected unless connecting to `localhost` or `127.0.0.1` for local testing.
- **Request**: `POST` with `Content-Type: application/json` and `User-Agent: ai-dev/<version>`.
- **Timeout**: 3.0 seconds maximum.
- **Retries**: Up to 2 attempts with backoff.
- **Network Privacy**:
  - The client does not include IP addresses in the payload.
  - Standard network metadata (IP address, TLS handshake) is visible to intermediate HTTP infrastructure.
  - Future collectors should disable or minimize IP access logging.

---

## CLI Commands

### Preview Semantics

- `ai-dev telemetry sharing preview`:
  - **Real repository inspection**: Scans the local repository tree to compute actual `language_families`, `repo_files_bucket`, and `repo_size_bucket`.
  - Dynamic runtime and token fields (such as `command_duration_bucket`, `input_tokens`, `output_tokens`, `model`) remain `None` or `"unknown"` because no live command or model execution took place.
  - **Nothing is written to queue, nothing is sent.**
- `ai-dev telemetry sharing preview --sample`:
  - **Synthetic example only**: Generates a mock payload demonstrating example token counts and metrics.
  - Labeled explicitly as `SAMPLE / EXAMPLE — NOT QUEUED, NOT SENT`.
  - **Nothing is written to queue, nothing is sent.**

```bash
# Check current telemetry sharing status
ai-dev telemetry sharing status

# Enable basic telemetry
ai-dev telemetry sharing enable basic

# Enable research telemetry
ai-dev telemetry sharing enable research

# Disable telemetry and clear any queued events
ai-dev telemetry sharing disable

# Inspect real repository inspection (dynamic token/duration fields are None)
ai-dev telemetry sharing preview
ai-dev telemetry sharing preview --level basic --json

# Inspect a synthetic sample payload showing example token counts and metrics
ai-dev telemetry sharing preview --sample
ai-dev telemetry sharing preview --sample --level research --json

# Manually flush the queued events to the configured endpoint
ai-dev telemetry sharing flush
```

---

## Local Telemetry vs Community Telemetry

| Feature | Local Telemetry | Community Telemetry |
|---|---|---|
| **Location** | `.ai/token-efficiency/` inside repository | User config/data dir (`%LOCALAPPDATA%`, etc.) |
| **Default State** | Active locally for efficiency & cache tracking | Completely OFF |
| **Network Sharing** | Never touches network | Optional, opt-in upload to configured endpoint |
| **Details Included** | Detailed local sessions, pricing estimation | Bucketed, privacy-preserving metrics without persistent identifiers |
| **User Identifiers** | Local session IDs | Random UUIDv4 per event only |
| **Turning Off** | Configured via policy / gates | `ai-dev telemetry sharing disable` |
