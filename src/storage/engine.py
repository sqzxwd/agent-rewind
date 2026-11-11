"""Storage engine for agent-rewind: Git-less time-machine and sandbox for AI agents."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_IGNORED_DIRS: set[str] = {
    ".git",
    ".rewind",
    ".venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

DEFAULT_IGNORED_FILES: set[str] = {
    ".DS_Store",
}


class SnapshotEngine:
    """Manages incremental shadow snapshots with SHA-256 content deduplication."""

    def __init__(
        self,
        root_dir: str | Path = ".",
        ignored_dirs: set[str] | None = None,
        ignored_files: set[str] | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.rewind_dir = self.root_dir / ".rewind"
        self.objects_dir = self.rewind_dir / "objects"
        self.snapshots_dir = self.rewind_dir / "snapshots"

        self.ignored_dirs = set(ignored_dirs) if ignored_dirs is not None else set(DEFAULT_IGNORED_DIRS)
        self.ignored_files = set(ignored_files) if ignored_files is not None else set(DEFAULT_IGNORED_FILES)

        self._ensure_storage()

    def _ensure_storage(self) -> None:
        """Create storage directories if they do not exist."""
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def is_ignored(self, path: Path) -> bool:
        """Check whether a given path (relative to root_dir) should be ignored."""
        try:
            rel = path if not path.is_absolute() else path.relative_to(self.root_dir)
        except ValueError:
            return True

        for part in rel.parts:
            if part in self.ignored_dirs:
                return True

        if rel.name in self.ignored_files or rel.name.endswith(".pyc"):
            return True

        return False

    def _is_dir_ignored(self, dir_name: str, full_path: Path) -> bool:
        """Check if a directory should be pruned during traversal."""
        if dir_name in self.ignored_dirs:
            return True
        try:
            rel = full_path.relative_to(self.root_dir)
            for part in rel.parts:
                if part in self.ignored_dirs:
                    return True
        except ValueError:
            return True
        return False

    def _scan_files(self) -> list[Path]:
        """Scan working directory for all non-ignored files, returning relative paths."""
        tracked_files: list[Path] = []
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if not self._is_dir_ignored(d, Path(root) / d)]
            for file_name in files:
                file_path = Path(root) / file_name
                try:
                    rel = file_path.relative_to(self.root_dir)
                except ValueError:
                    continue
                if not self.is_ignored(rel):
                    tracked_files.append(rel)
        return sorted(tracked_files)

    def _store_content(self, content: bytes) -> str:
        """Store file content indexed by its SHA-256 hash (deduplication)."""
        content_hash = hashlib.sha256(content).hexdigest()
        obj_path = self.objects_dir / content_hash
        if not obj_path.exists():
            tmp_path = self.objects_dir / f".tmp_{content_hash}_{uuid.uuid4().hex[:6]}"
            tmp_path.write_bytes(content)
            tmp_path.replace(obj_path)
        return content_hash

    def _count_affected_files(self, current_files: dict[str, Any], parent_files: dict[str, Any]) -> int:
        """Count the number of changed, added, or deleted files relative to parent snapshot."""
        all_keys = set(current_files.keys()) | set(parent_files.keys())
        affected = 0
        for key in all_keys:
            if key not in parent_files or key not in current_files:
                affected += 1
            elif current_files[key]["hash"] != parent_files[key]["hash"]:
                affected += 1
        return affected

    def create_snapshot(self, message: str = "auto snapshot") -> str:
        """Create a new snapshot of the working directory and return its ID."""
        self._ensure_storage()
        files = self._scan_files()
        files_meta: dict[str, dict[str, Any]] = {}

        for rel_path in files:
            full_path = self.root_dir / rel_path
            try:
                content = full_path.read_bytes()
                stat = full_path.stat()
            except OSError:
                continue

            content_hash = self._store_content(content)
            files_meta[rel_path.as_posix()] = {
                "hash": content_hash,
                "size": len(content),
                "mode": stat.st_mode,
            }

        existing_snapshots = self.list_snapshots()
        parent_id: str | None = None
        affected_files: int = len(files_meta)

        if existing_snapshots:
            latest = existing_snapshots[-1]
            parent_id = latest["id"]
            parent_files = latest.get("files", {})
            affected_files = self._count_affected_files(files_meta, parent_files)

        snap_id = uuid.uuid4().hex[:8]
        while (self.snapshots_dir / f"{snap_id}.json").exists():
            snap_id = uuid.uuid4().hex[:8]

        metadata: dict[str, Any] = {
            "id": snap_id,
            "parent_id": parent_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "message": message,
            "total_files": len(files_meta),
            "files_count": len(files_meta),
            "total_size": sum(f["size"] for f in files_meta.values()),
            "affected_files": affected_files,
            "changed_files_count": affected_files,
            "files": files_meta,
        }

        snap_path = self.snapshots_dir / f"{snap_id}.json"
        tmp_snap_path = self.snapshots_dir / f".tmp_{snap_id}.json"
        tmp_snap_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_snap_path.replace(snap_path)

        return snap_id

    def list_snapshots(self) -> list[dict[str, Any]]:
        """Return history of all recorded snapshots sorted chronologically."""
        self._ensure_storage()
        snapshots: list[dict[str, Any]] = []

        for entry in self.snapshots_dir.glob("*.json"):
            if entry.name.startswith("."):
                continue
            try:
                data = json.loads(entry.read_text(encoding="utf-8"))
                snapshots.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        snapshots.sort(key=lambda s: s.get("created_at", ""))
        return snapshots

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        """Find a snapshot by exact ID or unique prefix."""
        exact_path = self.snapshots_dir / f"{snapshot_id}.json"
        if exact_path.exists():
            try:
                return json.loads(exact_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None

        # Try prefix matching
        matches: list[dict[str, Any]] = []
        for snap in self.list_snapshots():
            if snap.get("id", "").startswith(snapshot_id):
                matches.append(snap)

        if len(matches) == 1:
            return matches[0]
        return None

    def restore_snapshot(self, snapshot_id: str) -> bool:
        """Restore exact state of all files from snapshot and delete agent-created extra files."""
        snapshot = self.get_snapshot(snapshot_id)
        if not snapshot:
            return False

        target_files = snapshot.get("files", {})

        # 1. Remove extra files currently on disk that are not in the snapshot
        current_files = self._scan_files()
        for rel_path in current_files:
            rel_posix = rel_path.as_posix()
            if rel_posix not in target_files:
                full_path = self.root_dir / rel_path
                try:
                    if full_path.is_file() or full_path.is_symlink():
                        full_path.unlink()
                except OSError:
                    pass

        # 2. Clean up empty directories bottom-up
        for root, dirs, files in os.walk(self.root_dir, topdown=False):
            root_p = Path(root)
            if root_p == self.root_dir:
                continue
            try:
                rel = root_p.relative_to(self.root_dir)
            except ValueError:
                continue
            if self.is_ignored(rel):
                continue
            try:
                if not any(root_p.iterdir()):
                    root_p.rmdir()
            except OSError:
                pass

        # 3. Restore all files from snapshot
        for rel_posix, meta in target_files.items():
            target_path = self.root_dir / rel_posix
            obj_path = self.objects_dir / meta["hash"]

            if not obj_path.exists():
                raise FileNotFoundError(f"Content object for {rel_posix} (hash: {meta['hash']}) is missing.")

            content = obj_path.read_bytes()

            # Check if file already exists with same content
            if target_path.is_file():
                try:
                    current_hash = hashlib.sha256(target_path.read_bytes()).hexdigest()
                    if current_hash == meta["hash"]:
                        continue
                except OSError:
                    pass

            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(content)

            if "mode" in meta:
                try:
                    os.chmod(target_path, meta["mode"])
                except OSError:
                    pass

        return True

    def _bytes_to_lines(self, data: bytes) -> list[str]:
        """Convert bytes to a list of text lines handling decoding gracefully."""
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = data.decode("latin-1")
            except Exception:
                text = data.decode("utf-8", errors="replace")
        return text.splitlines()

    def compute_diff(self, snapshot_id: str) -> dict[str, list[str]]:
        """Calculate line-by-line diff between current workspace and the chosen snapshot."""
        snapshot = self.get_snapshot(snapshot_id)
        if not snapshot:
            raise ValueError(f"Snapshot '{snapshot_id}' not found")

        snap_files = snapshot.get("files", {})
        curr_files_list = self._scan_files()
        curr_files = {p.as_posix(): p for p in curr_files_list}

        all_paths = sorted(set(snap_files.keys()) | set(curr_files.keys()))
        diff_results: dict[str, list[str]] = {}

        for rel_posix in all_paths:
            if rel_posix not in curr_files:
                # File was deleted in working directory
                snap_hash = snap_files[rel_posix]["hash"]
                obj_path = self.objects_dir / snap_hash
                if not obj_path.exists():
                    continue
                snap_bytes = obj_path.read_bytes()

                if b"\0" in snap_bytes:
                    diff_results[rel_posix] = [f"Binary file {rel_posix} was deleted"]
                else:
                    snap_lines = self._bytes_to_lines(snap_bytes)
                    diff_lines = list(
                        difflib.unified_diff(
                            snap_lines,
                            [],
                            fromfile=f"snapshot:{snapshot['id']}/{rel_posix}",
                            tofile="/dev/null",
                            lineterm="",
                        )
                    )
                    if diff_lines:
                        diff_results[rel_posix] = diff_lines

            elif rel_posix not in snap_files:
                # File was added in working directory
                curr_path = self.root_dir / rel_posix
                try:
                    curr_bytes = curr_path.read_bytes()
                except OSError:
                    continue

                if b"\0" in curr_bytes:
                    diff_results[rel_posix] = [f"Binary file {rel_posix} was added"]
                else:
                    curr_lines = self._bytes_to_lines(curr_bytes)
                    diff_lines = list(
                        difflib.unified_diff(
                            [],
                            curr_lines,
                            fromfile="/dev/null",
                            tofile=f"workspace/{rel_posix}",
                            lineterm="",
                        )
                    )
                    if diff_lines:
                        diff_results[rel_posix] = diff_lines

            else:
                # File exists in both; compare hashes
                curr_path = self.root_dir / rel_posix
                try:
                    curr_bytes = curr_path.read_bytes()
                except OSError:
                    continue

                curr_hash = hashlib.sha256(curr_bytes).hexdigest()
                snap_hash = snap_files[rel_posix]["hash"]

                if curr_hash == snap_hash:
                    continue

                obj_path = self.objects_dir / snap_hash
                if not obj_path.exists():
                    continue
                snap_bytes = obj_path.read_bytes()

                if b"\0" in snap_bytes or b"\0" in curr_bytes:
                    diff_results[rel_posix] = [f"Binary files snapshot and workspace differ for {rel_posix}"]
                else:
                    snap_lines = self._bytes_to_lines(snap_bytes)
                    curr_lines = self._bytes_to_lines(curr_bytes)
                    diff_lines = list(
                        difflib.unified_diff(
                            snap_lines,
                            curr_lines,
                            fromfile=f"snapshot:{snapshot['id']}/{rel_posix}",
                            tofile=f"workspace/{rel_posix}",
                            lineterm="",
                        )
                    )
                    if diff_lines:
                        diff_results[rel_posix] = diff_lines

        return diff_results
