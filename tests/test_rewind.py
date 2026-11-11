"""Unit and integration tests for agent-rewind."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.storage.engine import SnapshotEngine
from src.watcher.daemon import RewindWatcher


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Fixture providing a clean directory with sample files."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello world')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Project Title\nInitial readme content.\n", encoding="utf-8")
    return tmp_path


def test_create_snapshot(workspace: Path) -> None:
    """Test manual and automated snapshot creation."""
    engine = SnapshotEngine(root_dir=workspace)
    snap_id = engine.create_snapshot("initial snapshot")

    assert isinstance(snap_id, str)
    assert len(snap_id) == 8

    # Check .rewind directory structure
    assert (workspace / ".rewind").exists()
    assert (workspace / ".rewind" / "objects").is_dir()
    assert (workspace / ".rewind" / "snapshots").is_dir()

    snap_file = workspace / ".rewind" / "snapshots" / f"{snap_id}.json"
    assert snap_file.exists()

    snap_data = engine.get_snapshot(snap_id)
    assert snap_data is not None
    assert snap_data["id"] == snap_id
    assert snap_data["message"] == "initial snapshot"
    assert snap_data["total_files"] == 2
    assert "src/main.py" in snap_data["files"]
    assert "README.md" in snap_data["files"]


def test_deduplication(workspace: Path) -> None:
    """Test that identical file content is deduplicated by sha256 in objects storage."""
    engine = SnapshotEngine(root_dir=workspace)

    # Create two files with exact same content and one different
    (workspace / "copy1.txt").write_text("identical content block\n", encoding="utf-8")
    (workspace / "copy2.txt").write_text("identical content block\n", encoding="utf-8")

    engine.create_snapshot("snap with duplicates")

    # In objects_dir, there should be 1 object for the identical files,
    # plus 1 for main.py, 1 for README.md -> total 3 objects
    stored_objects = list(engine.objects_dir.glob("*"))
    # Filter out any possible dotfiles
    stored_hashes = [p.name for p in stored_objects if not p.name.startswith(".")]

    assert len(stored_hashes) == 3

    # Snapshotting again without changes must not add any new object files
    engine.create_snapshot("second snap without changes")
    stored_objects_after = [p.name for p in engine.objects_dir.glob("*") if not p.name.startswith(".")]
    assert len(stored_objects_after) == 3

    # Adding a file with new content creates exactly 1 more object
    (workspace / "new.txt").write_text("brand new unique content", encoding="utf-8")
    engine.create_snapshot("third snap with new file")
    stored_objects_final = [p.name for p in engine.objects_dir.glob("*") if not p.name.startswith(".")]
    assert len(stored_objects_final) == 4


def test_rollback_modified_and_deleted_files(workspace: Path) -> None:
    """Test full rollback restoring original files and removing agent-created extra files."""
    engine = SnapshotEngine(root_dir=workspace)
    base_snap = engine.create_snapshot("base snapshot")

    # 1. Modify existing file
    (workspace / "src" / "main.py").write_text("print('corrupted by agent')\n", encoding="utf-8")

    # 2. Delete existing file
    (workspace / "README.md").unlink()

    # 3. Create extra files and directories (simulating agent creating clutter)
    (workspace / "agent_garbage.tmp").write_text("trash", encoding="utf-8")
    (workspace / "src" / "agent_addon.py").write_text("def evil(): pass\n", encoding="utf-8")
    (workspace / "new_agent_dir").mkdir()
    (workspace / "new_agent_dir" / "nested.log").write_text("log data", encoding="utf-8")

    assert not (workspace / "README.md").exists()
    assert (workspace / "agent_garbage.tmp").exists()
    assert (workspace / "new_agent_dir" / "nested.log").exists()

    # Perform rollback
    success = engine.restore_snapshot(base_snap)
    assert success is True

    # Check modifications rolled back
    assert (workspace / "src" / "main.py").read_text(encoding="utf-8") == "print('hello world')\n"

    # Check deleted file restored
    assert (workspace / "README.md").exists()
    assert "Initial readme content." in (workspace / "README.md").read_text(encoding="utf-8")

    # Check agent extra files deleted
    assert not (workspace / "agent_garbage.tmp").exists()
    assert not (workspace / "src" / "agent_addon.py").exists()
    assert not (workspace / "new_agent_dir" / "nested.log").exists()
    assert not (workspace / "new_agent_dir").exists()  # Empty folder cleaned up


def test_compute_diff(workspace: Path) -> None:
    """Test line-by-line diff generation between current workspace and snapshot."""
    engine = SnapshotEngine(root_dir=workspace)
    snap_id = engine.create_snapshot("base snapshot")

    # Modify main.py
    (workspace / "src" / "main.py").write_text(
        "print('hello world')\nprint('added line')\n",
        encoding="utf-8",
    )

    # Delete README.md
    (workspace / "README.md").unlink()

    # Create new file
    (workspace / "src" / "feature.py").write_text("x = 42\n", encoding="utf-8")

    diffs = engine.compute_diff(snap_id)

    # Check diff keys
    assert "src/main.py" in diffs
    assert "README.md" in diffs
    assert "src/feature.py" in diffs

    # Check contents of diffs
    main_diff = "\n".join(diffs["src/main.py"])
    assert "+print('added line')" in main_diff

    readme_diff = "\n".join(diffs["README.md"])
    assert "-# Project Title" in readme_diff

    feature_diff = "\n".join(diffs["src/feature.py"])
    assert "+x = 42" in feature_diff


def test_list_snapshots_and_history(workspace: Path) -> None:
    """Test listing snapshot history with affected files calculation."""
    engine = SnapshotEngine(root_dir=workspace)

    snap1 = engine.create_snapshot("initial snapshot")
    (workspace / "src" / "main.py").write_text("print('change 1')\n", encoding="utf-8")
    snap2 = engine.create_snapshot("change 1")
    (workspace / "new_file.txt").write_text("new\n", encoding="utf-8")
    snap3 = engine.create_snapshot("added new file")

    snapshots = engine.list_snapshots()
    assert len(snapshots) == 3

    assert snapshots[0]["id"] == snap1
    assert snapshots[0]["affected_files"] == 2  # all initial files

    assert snapshots[1]["id"] == snap2
    assert snapshots[1]["affected_files"] == 1  # 1 modified file

    assert snapshots[2]["id"] == snap3
    assert snapshots[2]["affected_files"] == 1  # 1 added file


def test_auto_ignore_rules(workspace: Path) -> None:
    """Test that ignored directories (.git, .rewind, .venv, etc.) are never snapshotted."""
    engine = SnapshotEngine(root_dir=workspace)

    # Create files in ignored directories
    (workspace / ".git").mkdir()
    (workspace / ".git" / "config").write_text("git config", encoding="utf-8")

    (workspace / ".venv").mkdir()
    (workspace / ".venv" / "pyvenv.cfg").write_text("venv config", encoding="utf-8")

    (workspace / "__pycache__").mkdir()
    (workspace / "__pycache__" / "temp.cpython-314.pyc").write_bytes(b"bytecode")

    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "package.json").write_text("{}", encoding="utf-8")

    (workspace / ".DS_Store").write_bytes(b"\x00\x00")

    snap_id = engine.create_snapshot("snap with ignored dirs")
    snap_data = engine.get_snapshot(snap_id)
    assert snap_data is not None

    tracked = set(snap_data["files"].keys())

    assert "src/main.py" in tracked
    assert "README.md" in tracked

    for path in tracked:
        assert not path.startswith(".git")
        assert not path.startswith(".venv")
        assert not path.startswith("__pycache__")
        assert not path.startswith("node_modules")
        assert not path.startswith(".rewind")
        assert not path.endswith(".DS_Store")


def test_watcher_daemon(workspace: Path) -> None:
    """Test async watcher daemon recording agent changes with debouncing."""
    async def _async_test() -> None:
        engine = SnapshotEngine(root_dir=workspace)
        engine.create_snapshot("baseline")

        stop_event = asyncio.Event()
        snapshots_captured: list[tuple[str, str, int]] = []

        def on_snapshot(snap_id: str, msg: str, count: int) -> None:
            snapshots_captured.append((snap_id, msg, count))
            stop_event.set()

        watcher = RewindWatcher(
            engine=engine,
            debounce_ms=100,
            step_ms=20,
            stop_event=stop_event,
            on_snapshot=on_snapshot,
        )

        watcher_task = asyncio.create_task(watcher.run())

        # Wait briefly for watcher loop to start
        await asyncio.sleep(0.1)

        # Trigger a change
        (workspace / "src" / "main.py").write_text("print('edited by agent')\n", encoding="utf-8")

        # Await stop_event or timeout
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=3.0)
        finally:
            stop_event.set()
            await watcher_task

        assert len(snapshots_captured) >= 1
        snap_id, msg, count = snapshots_captured[0]
        assert msg == "agent step: modified 1 files"
        assert count == 1

    asyncio.run(_async_test())


def test_cli_interface(workspace: Path) -> None:
    """Test CLI commands: snap, list, diff, rollback."""
    runner = CliRunner()

    # 1. snap command
    res_snap = runner.invoke(app, ["snap", "cli snapshot 1", "-p", str(workspace)])
    assert res_snap.exit_code == 0
    assert "Snapshot created" in res_snap.output

    # 2. list command
    res_list = runner.invoke(app, ["list", "-p", str(workspace)])
    assert res_list.exit_code == 0
    assert "cli snapshot 1" in res_list.output

    engine = SnapshotEngine(root_dir=workspace)
    snapshots = engine.list_snapshots()
    assert len(snapshots) == 1
    snap_id = snapshots[0]["id"]

    # 3. diff command when identical
    res_diff_clean = runner.invoke(app, ["diff", snap_id, "-p", str(workspace)])
    assert res_diff_clean.exit_code == 0
    assert "identical" in res_diff_clean.output

    # Modify file
    (workspace / "src" / "main.py").write_text("print('cli change')\n", encoding="utf-8")

    # 4. diff command with changes
    res_diff_changed = runner.invoke(app, ["diff", snap_id, "-p", str(workspace)])
    assert res_diff_changed.exit_code == 0
    assert "src/main.py" in res_diff_changed.output

    # 5. rollback command with confirmation flag
    res_rollback = runner.invoke(app, ["rollback", snap_id, "--yes", "-p", str(workspace)])
    assert res_rollback.exit_code == 0
    assert "Successfully restored" in res_rollback.output
    assert (workspace / "src" / "main.py").read_text(encoding="utf-8") == "print('hello world')\n"

    # 6. rollback command with invalid ID
    res_invalid = runner.invoke(app, ["rollback", "nonexistent999", "--yes", "-p", str(workspace)])
    assert res_invalid.exit_code == 1
    assert "not found" in res_invalid.output
