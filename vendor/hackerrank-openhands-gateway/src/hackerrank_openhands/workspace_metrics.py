"""Git-independent workspace change metrics."""

from __future__ import annotations

import difflib
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_EXCLUDED_DIRS = frozenset({
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "build",
    "dist",
})


@dataclass(frozen=True)
class FileState:
    """State captured for one workspace file."""

    digest: str
    size_bytes: int
    is_text: bool
    line_count: int | None
    lines: tuple[str, ...] | None


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """Immutable workspace state used for before/after comparison."""

    files: dict[str, FileState]


def _is_excluded(path: Path, excluded_roots: tuple[Path, ...]) -> bool:
    return any(path == root or root in path.parents for root in excluded_roots)


def _iter_files(root: Path, excluded_roots: tuple[Path, ...]) -> Iterable[Path]:
    """Yield regular files below root without following symlinked directories."""
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        dirnames[:] = [
            name
            for name in dirnames
            if name not in DEFAULT_EXCLUDED_DIRS
            and not _is_excluded(directory_path / name, excluded_roots)
        ]
        for name in filenames:
            path = directory_path / name
            if not path.is_symlink() and not _is_excluded(path, excluded_roots):
                yield path


def _file_state(path: Path) -> FileState:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    try:
        text = data.decode("utf-8")
        is_text = "\x00" not in text
    except UnicodeDecodeError:
        is_text = False
        text = ""
    if not is_text:
        return FileState(digest, len(data), False, None, None)
    lines = tuple(text.splitlines(keepends=True))
    return FileState(digest, len(data), True, len(lines), lines)


def snapshot_workspace(
    workspace: Path,
    *,
    excluded_paths: Iterable[Path] = (),
) -> WorkspaceSnapshot:
    """Capture regular file hashes and text contents below a workspace."""
    root = workspace.resolve()
    excluded_roots = tuple(path.resolve() for path in excluded_paths)
    files = {
        str(path.relative_to(root)): _file_state(path)
        for path in _iter_files(root, excluded_roots)
    }
    return WorkspaceSnapshot(files)


def _line_delta(before: FileState, after: FileState) -> tuple[int, int]:
    """Return added and deleted text lines for one modified file."""
    if not before.is_text or not after.is_text or before.lines is None or after.lines is None:
        return 0, 0
    added = 0
    deleted = 0
    matcher = difflib.SequenceMatcher(a=before.lines, b=after.lines)
    for tag, before_start, before_end, after_start, after_end in matcher.get_opcodes():
        if tag in {"replace", "delete"}:
            deleted += before_end - before_start
        if tag in {"replace", "insert"}:
            added += after_end - after_start
    return added, deleted


def compare_snapshots(before: WorkspaceSnapshot, after: WorkspaceSnapshot) -> dict[str, object]:
    """Compare two snapshots and return JSON-compatible file/line metrics."""
    before_paths = set(before.files)
    after_paths = set(after.files)
    added_paths = after_paths - before_paths
    deleted_paths = before_paths - after_paths
    common_paths = before_paths & after_paths
    modified_paths = {
        path for path in common_paths if before.files[path].digest != after.files[path].digest
    }

    # Exact-content renames are detectable without Git. Renamed paths are
    # removed from added/deleted counts and counted as one logical change.
    deleted_by_digest: dict[str, list[str]] = {}
    for path in deleted_paths:
        deleted_by_digest.setdefault(before.files[path].digest, []).append(path)
    renamed: list[dict[str, str]] = []
    remaining_added = set(added_paths)
    remaining_deleted = set(deleted_paths)
    for new_path in sorted(added_paths):
        digest = after.files[new_path].digest
        candidates = deleted_by_digest.get(digest, [])
        old_path = next((candidate for candidate in candidates if candidate in remaining_deleted), None)
        if old_path is not None:
            remaining_added.remove(new_path)
            remaining_deleted.remove(old_path)
            renamed.append({"from": old_path, "to": new_path})

    lines_added = 0
    lines_deleted = 0
    for path in remaining_added:
        line_count = after.files[path].line_count
        lines_added += line_count or 0
    for path in remaining_deleted:
        line_count = before.files[path].line_count
        lines_deleted += line_count or 0
    for path in modified_paths:
        added, deleted = _line_delta(before.files[path], after.files[path])
        lines_added += added
        lines_deleted += deleted

    files_added = len(remaining_added)
    files_deleted = len(remaining_deleted)
    files_modified = len(modified_paths)
    files_renamed = len(renamed)
    return {
        "status": "available",
        "files": {
            "added": files_added,
            "modified": files_modified,
            "deleted": files_deleted,
            "renamed": files_renamed,
            "total_changed": files_added + files_modified + files_deleted + files_renamed,
        },
        "lines": {
            "added": lines_added,
            "deleted": lines_deleted,
            "changed": lines_added + lines_deleted,
        },
        "renames": renamed,
    }
