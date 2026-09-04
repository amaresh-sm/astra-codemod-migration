"""Remove host-specific filesystem paths from persisted run evidence."""

from __future__ import annotations

import re
from pathlib import Path


# Keep the matcher deliberately narrow: container paths such as /workspace and
# /input are part of the public execution model, while these locations reveal
# a particular author's machine or temporary workspace.
HOST_PATH = re.compile(
    r"(?:file://)?/(?:Users/[^/\s\"'`]+|home/[^/\s\"'`]+|private/tmp|private/var/folders|var/folders)(?:/[^\s\"'`<>]*)?"
)


def redact_text(text: str, replacements: dict[Path, str] | None = None) -> str:
    """Replace known workspaces and generic host paths with stable labels."""

    for path, label in sorted((replacements or {}).items(), key=lambda item: len(str(item[0])), reverse=True):
        text = text.replace(str(path.resolve()), label)
    return HOST_PATH.sub("<host-path>", text)


def redact_file(path: Path, replacements: dict[Path, str] | None = None) -> bool:
    """Redact one UTF-8 evidence file, returning whether it changed.

    Binary artifacts are intentionally left alone; they cannot safely expose a
    readable host path and rewriting them could corrupt the artifact.
    """

    try:
        original = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    redacted = redact_text(original, replacements)
    if redacted == original:
        return False
    path.write_text(redacted, encoding="utf-8")
    return True


def redact_tree(root: Path, replacements: dict[Path, str] | None = None) -> list[Path]:
    """Redact every readable report/log file below ``root``."""

    if not root.is_dir():
        return []
    return [path for path in root.rglob("*") if path.is_file() and redact_file(path, replacements)]
