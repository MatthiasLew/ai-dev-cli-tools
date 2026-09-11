from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ai_dev_tools.cache import repository
from ai_dev_tools.cache.repository import _sha256, read_repository_index, update_repository_index
from ai_dev_tools.runners.coordination import coordinate_agents
from ai_dev_tools.telemetry import record_usage


def _worker_update_index(root_str: str) -> bool:
    root = Path(root_str)
    res = update_repository_index(root)
    return isinstance(res, dict) and "entries" in res


def _worker_record_telemetry(root_str: str, worker_id: int) -> bool:
    root = Path(root_str)
    res = record_usage(
        root,
        client="generic",
        input_tokens=100 + worker_id,
        output_tokens=50 + worker_id,
        model=f"model-{worker_id}",
        source_id=f"req-{worker_id}",
    )
    return isinstance(res, dict) and "total_tokens" in res


def test_concurrent_repository_index_updates(tmp_path: Path) -> None:
    for i in range(10):
        (tmp_path / f"file_{i}.py").write_text(f"x = {i}\n", encoding="utf-8")

    update_repository_index(tmp_path)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_worker_update_index, str(tmp_path)) for _ in range(8)]
        results = [f.result() for f in futures]

    assert all(results)

    index_file = tmp_path / ".ai" / "cache" / "repository-index.json"
    assert index_file.exists()
    payload = json.loads(index_file.read_text(encoding="utf-8"))
    assert len(payload["entries"]) == 10

    tmps = list((tmp_path / ".ai" / "cache").glob("*.tmp"))
    assert len(tmps) == 0


def test_optimistic_concurrency_merging(tmp_path: Path) -> None:
    (tmp_path / "mod_a.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "mod_b.py").write_text("b = 1\n", encoding="utf-8")

    idx1 = update_repository_index(tmp_path)
    assert len(idx1["entries"]) == 2

    (tmp_path / "mod_b.py").write_text("b = 2; c = 3\n", encoding="utf-8")
    idx2 = update_repository_index(tmp_path)
    b_hash_newer = [e["sha256"] for e in idx2["entries"] if e["path"] == "mod_b.py"][0]

    (tmp_path / "mod_a.py").write_text("a = 99\n", encoding="utf-8")
    idx3 = update_repository_index(tmp_path)
    b_hash_final = [e["sha256"] for e in idx3["entries"] if e["path"] == "mod_b.py"][0]

    assert b_hash_final == b_hash_newer, "Optimistic concurrency must preserve newer file hash"


def test_optimistic_concurrency_stale_write_interleaving(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    import threading
    import time

    from ai_dev_tools.cache import repository
    from ai_dev_tools.cache.repository import _sha256, read_repository_index

    # Setup initial files and index
    (tmp_path / "mod_a.py").write_text("a = 10\n", encoding="utf-8")
    (tmp_path / "mod_b.py").write_text("b = 20\n", encoding="utf-8")
    (tmp_path / "mod_del.py").write_text("del_me = 1\n", encoding="utf-8")
    initial_idx = update_repository_index(tmp_path)
    assert len(initial_idx["entries"]) == 3

    event_a_scanned = threading.Event()
    event_b_finished = threading.Event()

    original_build_graph = repository.build_impact_graph

    def controlled_build_graph(root: Path, paths: set[str], **kwargs):  # type: ignore[no-untyped-def]
        if threading.current_thread().name == "worker_a":
            # Signal that Thread A has read previous index and scanned/hashed files
            event_a_scanned.set()
            # Wait for Thread B to modify mod_b, add mod_c, delete mod_del, and commit index
            assert event_b_finished.wait(timeout=5.0), "Thread B did not finish in time"
        return original_build_graph(root, paths, **kwargs)

    monkeypatch.setattr(repository, "build_impact_graph", controlled_build_graph)

    # Thread A worker: modifies mod_a, then runs update_repository_index
    worker_a_result: dict[str, object] = {}

    def worker_a_target() -> None:
        time.sleep(0.01)
        (tmp_path / "mod_a.py").write_text("a = 999; # modified by A\n", encoding="utf-8")
        res = update_repository_index(tmp_path)
        worker_a_result.update(res)

    thread_a = threading.Thread(target=worker_a_target, name="worker_a")
    thread_a.start()

    # Main thread acts as Process/Thread B
    # Wait until Thread A has scanned files and paused before write
    assert event_a_scanned.wait(timeout=5.0), "Thread A did not reach scan point"

    time.sleep(0.02)
    # Thread B modifies mod_b, adds mod_c, deletes mod_del
    (tmp_path / "mod_b.py").write_text("b = 888; # modified by B\n", encoding="utf-8")
    (tmp_path / "mod_c.py").write_text("c = 777; # added by B\n", encoding="utf-8")
    (tmp_path / "mod_del.py").unlink()

    idx_b = update_repository_index(tmp_path)
    b_entries = {e["path"]: e for e in idx_b["entries"]}  # type: ignore[union-attr]
    assert "mod_b.py" in b_entries
    assert "mod_c.py" in b_entries
    assert "mod_del.py" not in b_entries
    expected_b_hash = b_entries["mod_b.py"]["sha256"]
    expected_c_hash = b_entries["mod_c.py"]["sha256"]

    # Thread B finishes, unblock Thread A to complete its write
    event_b_finished.set()
    thread_a.join(timeout=5.0)
    assert not thread_a.is_alive(), "Thread A timed out"

    # Verify on-disk repository-index.json after Thread A's lagging write
    final_on_disk = read_repository_index(tmp_path)
    assert final_on_disk, "Final index must exist on disk"
    final_entries = {e["path"]: e for e in final_on_disk["entries"]}  # type: ignore[union-attr]

    # Thread B's update to mod_b must NOT have been overwritten by Thread A's stale state
    assert final_entries["mod_b.py"]["sha256"] == expected_b_hash
    # Thread A's update to mod_a must be present
    assert final_entries["mod_a.py"]["sha256"] == _sha256(tmp_path / "mod_a.py")
    # Thread B's newly added mod_c must be present
    assert final_entries["mod_c.py"]["sha256"] == expected_c_hash
    # mod_del.py deleted by Thread B must NOT be resurrected
    assert "mod_del.py" not in final_entries

    summary = final_on_disk.get("summary", {})  # type: ignore[union-attr]
    assert summary.get("files") == 3
    assert len(final_entries) == 3


def test_optimistic_concurrency_three_way_commit_race(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    # Setup initial files
    (tmp_path / "mod_a.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "mod_b.py").write_text("b = 1\n", encoding="utf-8")
    (tmp_path / "mod_c.py").write_text("c = 1\n", encoding="utf-8")
    update_repository_index(tmp_path)

    event_a_ready = threading.Event()
    event_bc_finished = threading.Event()

    orig_read_repo = repository.read_repository_index

    # Synchronization hook for Thread A during commit
    def sync_read_repo(root: Path) -> dict[str, object]:
        if threading.current_thread().name == "Thread-A":
            event_a_ready.set()
            # Wait until both Thread B and Thread C have written newer versions
            assert event_bc_finished.wait(timeout=5.0)
        return orig_read_repo(root)

    monkeypatch.setattr(repository, "read_repository_index", sync_read_repo)

    def worker_a() -> None:
        (tmp_path / "mod_a.py").write_text("a = 999\n", encoding="utf-8")
        update_repository_index(tmp_path)

    thread_a = threading.Thread(target=worker_a, name="Thread-A")
    thread_a.start()

    assert event_a_ready.wait(timeout=5.0)

    # Thread B writes newer state
    (tmp_path / "mod_b.py").write_text("b = 888\n", encoding="utf-8")
    update_repository_index(tmp_path)
    hash_b = _sha256(tmp_path / "mod_b.py")

    # Thread C writes newest state
    (tmp_path / "mod_c.py").write_text("c = 777\n", encoding="utf-8")
    update_repository_index(tmp_path)
    hash_c = _sha256(tmp_path / "mod_c.py")

    # Release Thread A to attempt its final commit
    event_bc_finished.set()
    thread_a.join(timeout=5.0)
    assert not thread_a.is_alive()

    # Verify final on-disk index
    final_idx = read_repository_index(tmp_path)
    assert final_idx
    entries = {e["path"]: e for e in final_idx["entries"]}  # type: ignore[union-attr]

    # Verify all 3 updates were preserved without data loss!
    assert entries["mod_a.py"]["sha256"] == _sha256(tmp_path / "mod_a.py")
    assert entries["mod_b.py"]["sha256"] == hash_b
    assert entries["mod_c.py"]["sha256"] == hash_c
    assert len(entries) == 3


def test_concurrent_telemetry_records(tmp_path: Path) -> None:
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_worker_record_telemetry, str(tmp_path), i) for i in range(20)]
        results = [f.result() for f in futures]

    assert all(results)

    sessions_dir = tmp_path / ".ai" / "token-efficiency" / "sessions"
    assert sessions_dir.exists()
    session_files = list(sessions_dir.glob("*.json"))
    assert len(session_files) == 20

    for sf in session_files:
        data = json.loads(sf.read_text(encoding="utf-8"))
        assert "total_tokens" in data

    latest_file = tmp_path / ".ai" / "token-efficiency" / "latest-session.json"
    assert latest_file.exists()
    latest_data = json.loads(latest_file.read_text(encoding="utf-8"))
    assert "total_tokens" in latest_data

    tmps = list((tmp_path / ".ai" / "token-efficiency").glob("*.tmp"))
    assert len(tmps) == 0


def test_coordination_lock_contention_and_safety(tmp_path: Path) -> None:
    rep1 = coordinate_agents(
        tmp_path,
        "add",
        task_id="task-1",
        title="Task 1",
        paths=["src/app.py"],
    )
    assert rep1.status == "success"

    def claim_task(agent: str) -> str:
        rep = coordinate_agents(
            tmp_path,
            "claim",
            task_id="task-1",
            agent_id=agent,
        )
        return str(rep.status)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(claim_task, "agent-1")
        f2 = executor.submit(claim_task, "agent-2")
        res1 = f1.result()
        res2 = f2.result()

    statuses = sorted([res1, res2])
    assert statuses == ["blocked", "success"], (
        f"Expected one success and one blocked, got {statuses}"
    )
