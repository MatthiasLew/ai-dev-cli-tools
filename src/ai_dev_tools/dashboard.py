# ruff: noqa: E501
from __future__ import annotations

import json
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ai_dev_tools.models.report import Report

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>ai-dev dashboard</title><style>
:root{color-scheme:dark;background:#0b1020;color:#e8eefc;font:15px system-ui}body{margin:0;padding:32px}
h1{margin:0 0 6px}.sub{color:#91a4c6;margin-bottom:24px}.grid{display:grid;gap:16px;
grid-template-columns:repeat(auto-fit,minmax(230px,1fr))}.card{background:#151d32;border:1px solid #293653;
border-radius:12px;padding:18px}.value{font-size:28px;font-weight:700;margin:8px 0}.ok{color:#67e8a5}
.warn{color:#ffd166}pre{white-space:pre-wrap;word-break:break-word;color:#b9c9e8;font-size:12px}</style>
</head><body><h1>ai-dev</h1><div class="sub" id="root"></div><div class="grid" id="grid"></div>
<script>const card=(t,v,d,c='')=>`<section class="card"><div>${t}</div><div class="value ${c}">${v}</div>
<pre>${d}</pre></section>`; async function refresh(){const r=await fetch('/api/status');const x=await r.json();
root.textContent=x.project_root;grid.innerHTML=card('Repository index',x.index.files??0,`updated: ${x.index.updated_at??'never'}`,'ok')+
card('Semantic symbols',x.semantic.symbols??0,`backend: ${x.semantic.backend??'not built'}`)+
card('Daemon',x.daemon.status??'stopped',`events: ${x.daemon.events??0} · updates: ${x.daemon.updates??0}`,x.daemon.status==='running'?'ok':'warn')+
card('Tokens saved',x.token_efficiency.total_saved_tokens??0,`${x.token_efficiency.receipts??0} receipts · latest ${x.token_efficiency.latest_saved_percent??0}%`,'ok')+
card('Provider usage',x.provider_usage.input_tokens??0,`${x.provider_usage.sessions??0} sessions · ${x.provider_usage.cached_input_tokens??0} cache read · ${x.provider_usage.cache_write_input_tokens??0} cache write`,'ok')+
card('Model output',x.provider_usage.output_tokens??0,`reasoning: ${x.provider_usage.reasoning_tokens??0}`)+
card('Usage policy',x.provider_usage.policy?.passed===false?'alert':'ok',`${x.provider_usage.policy?.violations?.length??0} violations · ${x.provider_usage.policy?.alerts?.length??0} alerts`,x.provider_usage.policy?.passed===false?'warn':'ok')+
card('Token optimizer',x.provider_usage.optimizer?.budget_recommendations??0,`${x.provider_usage.optimizer?.model_recommendations??0} model routes · ${x.provider_usage.optimizer?.gaps??0} evidence gaps`,x.provider_usage.optimizer?.gaps?'warn':'ok')+
card('Context delivery',x.token_efficiency.latest_delivery??'none',`cache hit: ${x.token_efficiency.latest_cache_hit?'yes':'no'}`)+
card('Cache',x.cache.files,`${x.cache.bytes} bytes`)+card('Runtime',x.runtime.status??'idle',`pid: ${x.runtime.pid??'-'}`)+
card('Last errors',x.errors.length,x.errors.join('\n')||'none',x.errors.length?'warn':'ok');}refresh();setInterval(refresh,3000)</script>
</body></html>"""


def dashboard_status(project_root: Path) -> Report:
    report = Report(command="dashboard status", project_root=project_root.resolve())
    report.summary = collect_status(project_root)
    return report


def serve_dashboard(project_root: Path, host: str = "127.0.0.1", port: int = 8765) -> int:
    server = create_dashboard_server(project_root, host, port)
    with server:
        print(f"ai-dev dashboard: http://{host}:{server.server_port}", flush=True)
        with suppress(KeyboardInterrupt):
            server.serve_forever()
    return 0


def create_dashboard_server(
    project_root: Path, host: str = "127.0.0.1", port: int = 8765
) -> ThreadingHTTPServer:
    if host not in LOOPBACK_HOSTS or not 0 <= port <= 65_535:
        raise ValueError("Dashboard only binds to a loopback host and a valid port")
    root = project_root.resolve()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path in {"/", "/index.html"}:
                self._send(PAGE.encode(), "text/html; charset=utf-8")
            elif self.path == "/api/status":
                self._send(json.dumps(collect_status(root)).encode(), "application/json")
            else:
                self.send_error(404)

        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


def collect_status(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    index = _read_json(root / ".ai/cache/repository-index.json")
    semantic = _read_json(root / ".ai/cache/semantic-index.json")
    daemon = _read_json(root / ".ai/cache/index-daemon.json")
    runtime = _read_json(root / ".ai/runtime/state.json")
    cache_root = root / ".ai" / "cache"
    cache_files = (
        [path for path in cache_root.rglob("*") if path.is_file()] if cache_root.exists() else []
    )
    errors = _recent_errors(root / ".ai")
    token_efficiency = _token_efficiency(root / ".ai" / "token-efficiency")
    from ai_dev_tools.telemetry import aggregate_usage
    from ai_dev_tools.telemetry_optimizer import compact_optimizer_status
    from ai_dev_tools.telemetry_policy import optional_policy_status

    provider_usage = {
        **aggregate_usage(root),
        "policy": optional_policy_status(root),
        "optimizer": compact_optimizer_status(root),
    }
    return {
        "project_root": str(root),
        "index": {
            "files": _count(index, "entries", "file_count"),
            "updated_at": index.get("updated_at", index.get("generated_at")),
        },
        "semantic": {
            "symbols": _count(semantic, "symbols", "symbol_count"),
            "backend": semantic.get("backend"),
        },
        "daemon": {key: daemon.get(key) for key in ("status", "events", "updates", "pid")},
        "cache": {
            "files": len(cache_files),
            "bytes": sum(path.stat().st_size for path in cache_files),
        },
        "runtime": {key: runtime.get(key) for key in ("status", "pid")},
        "token_efficiency": token_efficiency,
        "provider_usage": provider_usage,
        "errors": errors,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _count(data: dict[str, Any], collection: str, count: str) -> int:
    value = data.get(collection)
    if isinstance(value, list | dict):
        return len(value)
    value = data.get(count)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _recent_errors(ai_root: Path) -> list[str]:
    errors: list[str] = []
    paths = sorted(
        ai_root.glob("**/*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[:20]
    for path in paths:
        payload = _read_json(path)
        issues = payload.get("issues", [])
        if isinstance(issues, list):
            for issue in issues:
                if isinstance(issue, dict) and issue.get("severity") in {"error", "critical"}:
                    errors.append(str(issue.get("message", "Unknown error")))
    return errors[:8]


def _token_efficiency(root: Path) -> dict[str, Any]:
    receipt_paths = sorted((root / "receipts").glob("*.json")) if root.exists() else []
    receipts = [_read_json(path) for path in receipt_paths[-100:]]
    latest = _read_json(root / "latest.json")
    cache = latest.get("cache", {})
    delivery = latest.get("delivery", {})
    return {
        "receipts": len(receipt_paths),
        "total_saved_tokens": sum(
            int(item.get("saved_tokens", 0))
            for item in receipts
            if isinstance(item.get("saved_tokens"), int)
        ),
        "latest_saved_tokens": latest.get("saved_tokens", 0),
        "latest_saved_percent": latest.get("saved_percent", 0),
        "latest_cache_hit": cache.get("hit", False) if isinstance(cache, dict) else False,
        "latest_delivery": delivery.get("delivery", "none") if isinstance(delivery, dict) else "none",
    }
