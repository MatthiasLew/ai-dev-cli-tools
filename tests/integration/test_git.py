from pathlib import Path

from ai_dev_tools.git.inspect import inspect_git
from ai_dev_tools.utils.subprocess import run_command


def test_git_inspect_dirty_repo(tmp_path: Path) -> None:
    run_command(["git", "init", "-b", "main"], tmp_path, 30)
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    report = inspect_git(tmp_path, detailed=True)
    assert "DIRTY" in report.summary["states"]
    assert "file.txt" in report.summary["changed_files"]


def test_git_state_parses_ahead_behind_counts() -> None:
    from ai_dev_tools.git.inspect import _ahead_behind_counts, _states

    porcelain = "## main...origin/main [ahead 2, behind 1]\n M file.txt"
    assert _ahead_behind_counts(porcelain) == (2, 1)
    assert "DIVERGED" in _states(porcelain, "origin/main", False, True, False)


def test_git_inspect_staged_untracked_secret_and_path_with_space(tmp_path: Path) -> None:
    run_command(["git", "init", "-b", "main"], tmp_path, 30)
    spaced = tmp_path / "file with space.txt"
    spaced.write_text("hello", encoding="utf-8")
    run_command(["git", "add", "file with space.txt"], tmp_path, 30)
    secret = tmp_path / "secret.txt"
    fake_key = "sk-" + "1234567890abcdef1234567890"
    secret.write_text("OPENAI_API_KEY=" + fake_key, encoding="utf-8")
    report = inspect_git(tmp_path, detailed=True)
    assert "file with space.txt" in report.summary["staged_files"]
    assert "secret.txt" in report.summary["untracked_files"]
    assert report.summary["secret_findings"]


def test_name_status_parses_rename(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools.git import inspect as git_inspect
    from ai_dev_tools.git.inspect import _entry_paths, _name_status
    from ai_dev_tools.utils.subprocess import CommandResult

    def fake_run(command: list[str], root: Path, timeout_seconds: int = 300) -> CommandResult:
        return CommandResult(command, 0, "R100\0old name.py\0new name.py\0", "", 0.01)

    monkeypatch.setattr(git_inspect, "run_command", fake_run)
    entries = _name_status(["git", "diff", "--name-status", "-z"], Path.cwd())
    assert entries == [{"status": "R100", "path": "new name.py", "old_path": "old name.py"}]
    assert _entry_paths(entries) == ["new name.py"]


def test_git_status_can_skip_report_writes(tmp_path: Path) -> None:
    run_command(["git", "init", "-b", "main"], tmp_path, 30)

    report = inspect_git(tmp_path, write_reports=False)

    assert report.status == "success"
    assert not (tmp_path / ".ai" / "reports").exists()


def test_git_inspect_includes_symbol_level_diff(tmp_path: Path) -> None:
    run_command(["git", "init", "-b", "main"], tmp_path, 30)
    run_command(["git", "config", "user.email", "agent@example.com"], tmp_path, 30)
    run_command(["git", "config", "user.name", "Agent"], tmp_path, 30)
    source = tmp_path / "service.py"
    source.write_text("def calculate(value):\n    return value + 1\n", encoding="utf-8")
    run_command(["git", "add", "service.py"], tmp_path, 30)
    run_command(["git", "commit", "-m", "initial"], tmp_path, 30)
    source.write_text(
        "def calculate(value, offset=2):\n    return value + offset\n", encoding="utf-8"
    )

    report = inspect_git(tmp_path, detailed=True, write_reports=False)

    assert report.summary["changed_symbols"][0]["name"] == "calculate"
    assert report.summary["changed_symbols"][0]["risk"] == "high"
    assert report.summary["symbol_diff_summary"]["symbols_changed"] == 1


def test_git_inspect_avoids_duplicate_diff_calls(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools.git import inspect as git_inspect
    from ai_dev_tools.utils.subprocess import run_command as real_run_command

    run_command(["git", "init", "-b", "main"], tmp_path, 30)
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")

    diff_commands: list[list[str]] = []

    def spy_run(command: list[str], root: Path, timeout_seconds: int = 300):  # type: ignore[no-untyped-def]
        if command == ["git", "diff"]:
            diff_commands.append(command)
        return real_run_command(command, root, timeout_seconds)

    monkeypatch.setattr(git_inspect, "run_command", spy_run)
    report = inspect_git(tmp_path, detailed=True, write_reports=False)

    assert len(diff_commands) == 1
    assert report.summary["diff_size_bytes"] == report.summary["unstaged_diff_bytes"]


def test_git_status_single_subprocess_call(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools.git import inspect as git_inspect
    from ai_dev_tools.utils.subprocess import run_command as real_run_command

    run_command(["git", "init", "-b", "main"], tmp_path, 30)
    (tmp_path / "test.txt").write_text("hello", encoding="utf-8")

    git_commands: list[list[str]] = []

    def spy_run(command: list[str], root: Path, timeout_seconds: int = 300):  # type: ignore[no-untyped-def]
        git_commands.append(command)
        return real_run_command(command, root, timeout_seconds)

    monkeypatch.setattr(git_inspect, "run_command", spy_run)
    report = inspect_git(tmp_path, detailed=False, write_reports=False)

    assert len(git_commands) == 1
    assert git_commands[0] == ["git", "status", "--porcelain=v2", "--branch", "-z"]
    assert report.summary["untracked_files"] == ["test.txt"]
    assert "DIRTY" in report.summary["states"]


def test_parse_porcelain_v2_all_entry_types() -> None:
    from ai_dev_tools.git.inspect import _parse_porcelain_v2

    h0 = "0" * 40
    h1 = "2ce75e2a24f7d6841a504cf3616ef5a59edb3a2d"
    h2 = "df967b96a579e45a18b8251732d16804b2e56a55"
    h3 = "abaddc0b9edd523c69166a2c9f3a9e31a4c873e3"
    h4 = "3b18e512dba79e4c8300dd08aeb37f8e728b8dad"
    h5 = "0f20c90ab8589d0844d84a9d7096294fe57882e3"
    h6 = "1193ff46343f4f6a0522e2b28b871e905178c1f0"
    output = (
        "# branch.oid 1234567890abcdef\0"
        "# branch.head feature/opt\0"
        "# branch.upstream origin/feature/opt\0"
        "# branch.ab +3 -1\0"
        f"1 A. N... 000000 100644 100644 {h0} {h1} added.py\0"
        f"1 MM N... 100644 100644 100644 {h2} {h2} mod_both.py\0"
        f"1 .D N... 100644 100644 000000 {h3} {h3} unstaged_del.py\0"
        f"2 R. N... 100644 100644 100644 {h4} {h4} R100 new_name.py\0"
        "old_name.py\0"
        f"u UU N... 100644 100644 100644 100644 {h2} {h5} {h6} conflict.py\0"
        "? untracked.py\0"
    )

    parsed = _parse_porcelain_v2(output)
    assert parsed["branch"] == "feature/opt"
    assert parsed["upstream"] == "origin/feature/opt"
    assert parsed["ahead"] == 3
    assert parsed["behind"] == 1
    assert parsed["untracked_files"] == ["untracked.py"]
    assert parsed["conflicted_files"] == ["conflict.py"]

    staged_paths = [e["path"] for e in parsed["staged_entries"]]
    assert "added.py" in staged_paths
    assert "mod_both.py" in staged_paths
    assert "new_name.py" in staged_paths
    assert "conflict.py" in staged_paths

    unstaged_paths = [e["path"] for e in parsed["unstaged_entries"]]
    assert "mod_both.py" in unstaged_paths
    assert "unstaged_del.py" in unstaged_paths
    assert "conflict.py" in unstaged_paths

    renames = [e for e in parsed["staged_entries"] if e["status"].startswith("R")]
    assert len(renames) == 1
    assert renames[0] == {"status": "R100", "path": "new_name.py", "old_path": "old_name.py"}


def test_git_inspect_stash_count(tmp_path: Path) -> None:
    run_command(["git", "init", "-b", "main"], tmp_path, 30)
    run_command(["git", "config", "user.email", "agent@example.com"], tmp_path, 30)
    run_command(["git", "config", "user.name", "Agent"], tmp_path, 30)
    (tmp_path / "file.txt").write_text("v1", encoding="utf-8")
    run_command(["git", "add", "."], tmp_path, 30)
    run_command(["git", "commit", "-m", "initial"], tmp_path, 30)

    # Initial report: stash_count must be 0
    report = inspect_git(tmp_path, detailed=False, write_reports=False)
    assert report.summary["stash_count"] == 0

    # Modify and stash
    (tmp_path / "file.txt").write_text("v2", encoding="utf-8")
    run_command(["git", "stash"], tmp_path, 30)

    report_stashed = inspect_git(tmp_path, detailed=False, write_reports=False)
    assert report_stashed.summary["stash_count"] == 1


def test_git_inspect_worktree_stash_count(tmp_path: Path) -> None:
    from ai_dev_tools.git.inspect import _stash_count

    worktree_dir = tmp_path / "worktree"
    worktree_dir.mkdir()
    dot_git = worktree_dir / ".git"
    gitdir_target = tmp_path / "main_repo" / ".git" / "worktrees" / "worktree"
    gitdir_target.mkdir(parents=True)
    dot_git.write_text(f"gitdir: {gitdir_target}\n", encoding="utf-8")

    assert _stash_count(worktree_dir) == 0


def test_git_states_and_large_files(tmp_path: Path) -> None:
    from ai_dev_tools.git.inspect import _large_files, _states

    states = _states("## HEAD (no branch)\nUU conflict.txt\n", None, True, False, True)
    assert "DETACHED_HEAD" in states
    assert "NO_UPSTREAM" in states
    assert "CONFLICT" in states

    large_file = tmp_path / "big.bin"
    large_file.write_bytes(b"0" * 1_000_005)
    normal_file = tmp_path / "small.txt"
    normal_file.write_bytes(b"0" * 100)

    res = _large_files(tmp_path, ["big.bin", "small.txt", "missing.txt"])
    assert res == ["big.bin"]



