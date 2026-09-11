from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ai_dev_tools.cache.repository import update_repository_index
from ai_dev_tools.detectors.repository_map import map_repository


def test_gitignore_conformance_with_git_ls_files(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )

    gitignore_content = "\n".join([
        "build/*",
        "!build/important.json",
        "/root_only.txt",
        "cache/",
        "*.log",
    ]) + "\n"
    (tmp_path / ".gitignore").write_text(gitignore_content, encoding="utf-8")

    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "temp.o").write_text("binary", encoding="utf-8")
    (tmp_path / "build" / "important.json").write_text("{\"keep\": true}", encoding="utf-8")

    (tmp_path / "root_only.txt").write_text("root", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "root_only.txt").write_text("not root", encoding="utf-8")

    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "data.bin").write_text("cache", encoding="utf-8")

    (tmp_path / "app.log").write_text("log", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')", encoding="utf-8")

    (tmp_path / "packages" / "subpkg").mkdir(parents=True)
    (tmp_path / "packages" / "subpkg" / ".gitignore").write_text(
        "nested_ignored.txt\n", encoding="utf-8"
    )
    (tmp_path / "packages" / "subpkg" / "nested_ignored.txt").write_text("secret", encoding="utf-8")
    (tmp_path / "packages" / "subpkg" / "kept.py").write_text("x = 1", encoding="utf-8")

    git_proc = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    git_expected_files = sorted(
        p.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        for p in git_proc.stdout.split(b"\0")
        if p
    )

    index_payload = update_repository_index(tmp_path)
    raw_entries = index_payload.get("entries")
    assert isinstance(raw_entries, list)
    indexed_paths = sorted(e["path"].replace("\\", "/") for e in raw_entries)

    assert indexed_paths == git_expected_files

    assert "build/important.json" in indexed_paths
    assert "build/temp.o" not in indexed_paths
    assert "root_only.txt" not in indexed_paths
    assert "sub/root_only.txt" in indexed_paths
    assert "cache/data.bin" not in indexed_paths
    assert "app.log" not in indexed_paths
    assert "packages/subpkg/nested_ignored.txt" not in indexed_paths
    assert "packages/subpkg/kept.py" in indexed_paths

    map_rep = map_repository(tmp_path)
    scanned_files = map_rep.summary["file_count_scanned"]
    assert scanned_files == len(git_expected_files)


def test_gitignore_fallback_in_nongit_directory(tmp_path: Path) -> None:
    assert not (tmp_path / ".git").exists()

    (tmp_path / ".gitignore").write_text(
        "build/*\n!build/important.json\n/root_only.txt\ncache/\n*.log\n",
        encoding="utf-8",
    )
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "temp.o").write_text("bin", encoding="utf-8")
    (tmp_path / "build" / "important.json").write_text("{}", encoding="utf-8")
    (tmp_path / "root_only.txt").write_text("root", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "root_only.txt").write_text("sub", encoding="utf-8")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "temp.txt").write_text("temp", encoding="utf-8")
    (tmp_path / "app.log").write_text("log", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("pass", encoding="utf-8")

    rep = map_repository(tmp_path)
    all_summary_files = (
        rep.summary["important_files"]
        + rep.summary["tests"]
        + rep.summary["documentation"]
        + rep.summary["generated_or_lock_files"]
    )
    all_posix = [f.replace("\\", "/") for f in all_summary_files]

    assert (
        any("important.json" in f for f in all_posix or rep.summary["large_files"])
        or rep.summary["file_count_scanned"] >= 3
    )
    assert not any("app.log" in f for f in all_posix)


def test_subprocess_efficiency_in_git_mapping(monkeypatch: Any, tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    (tmp_path / "a.py").write_text("a=1", encoding="utf-8")
    (tmp_path / "b.py").write_text("b=2", encoding="utf-8")

    import subprocess as original_subprocess
    call_count = 0
    real_run = original_subprocess.run

    def tracked_run(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(original_subprocess, "run", tracked_run)

    map_repository(tmp_path)
    assert call_count == 1


def test_nested_subproject_git_detection(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )

    (tmp_path / ".gitignore").write_text("*.log\n", encoding="utf-8")

    # Nested 3 levels down: repo/packages/backend/service
    service_dir = tmp_path / "packages" / "backend" / "service"
    service_dir.mkdir(parents=True)
    (service_dir / "main.py").write_text("def run(): pass\n", encoding="utf-8")
    (service_dir / "debug.log").write_text("ignored log\n", encoding="utf-8")

    # Index directly on the nested project root
    idx = update_repository_index(service_dir)
    raw_entries = idx.get("entries")
    assert isinstance(raw_entries, list)
    entries = {e["path"] for e in raw_entries}
    assert "main.py" in entries
    assert "debug.log" not in entries, "Gitignore *.log must be respected in nested project"

    rep = map_repository(service_dir)
    assert rep.summary["file_count_scanned"] == 1


def test_custom_ignore_paths_with_git(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )

    # Configure custom ignores in .ai-dev-tools.toml (not in .gitignore)
    config_content = '[ignore]\npaths = ["generated_api", "vendor-local"]\n'
    (tmp_path / ".ai-dev-tools.toml").write_text(config_content, encoding="utf-8")

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("pass", encoding="utf-8")

    (tmp_path / "generated_api").mkdir()
    (tmp_path / "generated_api" / "client.py").write_text("# gen", encoding="utf-8")

    (tmp_path / "vendor-local").mkdir()
    (tmp_path / "vendor-local" / "lib.py").write_text("# vendor", encoding="utf-8")

    # Git track everything including vendor-local
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)

    idx = update_repository_index(tmp_path)
    raw_entries = idx.get("entries")
    assert isinstance(raw_entries, list)
    entries = {e["path"] for e in raw_entries}

    assert "src/app.py" in entries
    assert "generated_api/client.py" not in entries, "Custom ignore path must be excluded"
    assert "vendor-local/lib.py" not in entries, "Tracked file in custom ignore must be excluded"
