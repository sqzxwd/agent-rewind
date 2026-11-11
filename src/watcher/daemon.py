"""Watcher daemon for agent-rewind: Asynchronous monitoring with debouncing."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from watchfiles import Change, DefaultFilter, awatch

try:
    from src.storage.engine import SnapshotEngine
except ImportError:
    from storage.engine import SnapshotEngine  # type: ignore[no-redef]


class RewindWatchFilter(DefaultFilter):
    """Filter that excludes internal storage and ignored directories/files."""

    def __init__(self, engine: SnapshotEngine) -> None:
        super().__init__(ignore_dirs=tuple(engine.ignored_dirs))
        self.engine = engine

    def __call__(self, change: Change, path: str) -> bool:
        if not super().__call__(change, path):
            return False
        try:
            rel = Path(path).relative_to(self.engine.root_dir)
            return not self.engine.is_ignored(rel)
        except ValueError:
            return False


class RewindWatcher:
    """Watches the project workspace and takes automatic debounced snapshots."""

    def __init__(
        self,
        engine: SnapshotEngine,
        debounce_ms: int = 1500,
        step_ms: int = 50,
        stop_event: asyncio.Event | threading.Event | None = None,
        on_snapshot: Callable[[str, str, int], None] | None = None,
    ) -> None:
        self.engine = engine
        self.debounce_ms = debounce_ms
        self.step_ms = step_ms
        self.stop_event = stop_event
        self.on_snapshot = on_snapshot

    async def run(self) -> None:
        """Asynchronously observe project changes and create snapshots upon edits."""
        watch_filter = RewindWatchFilter(self.engine)
        try:
            async for changes in awatch(
                self.engine.root_dir,
                watch_filter=watch_filter,
                debounce=self.debounce_ms,
                step=self.step_ms,
                stop_event=self.stop_event,
            ):
                valid_paths: set[str] = set()
                for change, path_str in changes:
                    p = Path(path_str)
                    try:
                        rel = p.relative_to(self.engine.root_dir)
                        if not self.engine.is_ignored(rel):
                            valid_paths.add(rel.as_posix())
                    except ValueError:
                        continue

                if not valid_paths:
                    continue

                count = len(valid_paths)
                message = f"agent step: modified {count} files"
                snap_id = self.engine.create_snapshot(message=message)

                if self.on_snapshot:
                    self.on_snapshot(snap_id, message, count)
        except asyncio.CancelledError:
            pass


async def watch_project(
    engine: SnapshotEngine,
    debounce_ms: int = 1500,
    stop_event: asyncio.Event | threading.Event | None = None,
    on_snapshot: Callable[[str, str, int], None] | None = None,
) -> None:
    """Convenience helper to start the watcher."""
    watcher = RewindWatcher(
        engine=engine,
        debounce_ms=debounce_ms,
        stop_event=stop_event,
        on_snapshot=on_snapshot,
    )
    await watcher.run()
