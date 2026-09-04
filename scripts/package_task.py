#!/usr/bin/env python3
"""Validate and create a deterministic authoring-package archive."""

from __future__ import annotations

import argparse
import gzip
import io
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path("dist/task-package.tar.gz")
EXCLUDED_PARTS = frozenset(
    {".git", "__pycache__", ".pytest_cache", ".venv", "dist", "node_modules", "runs"}
)
EXCLUDED_FILES = frozenset({".DS_Store", ".env", "auth.json"})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run readiness gates and create a deterministic task-package archive"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="archive path (default: dist/task-package.tar.gz)",
    )
    return parser.parse_args(argv)


def readiness_commands() -> list[list[str]]:
    """Return every required pre-package check in dependency order."""

    python = sys.executable
    return [
        [python, "scripts/validate_task.py", "tasks"],
        [python, "readiness_checks/check_package.py"],
        [python, "readiness_checks/check_acceptance.py"],
        [python, "readiness_checks/check_report_privacy.py"],
        [python, "readiness_checks/check_scoring.py"],
        [python, "readiness_checks/check_determinism.py"],
        [python, "readiness_checks/check_proof_work.py"],
        [python, "readiness_checks/check_reference.py"],
        [python, "readiness_checks/check_mutants.py"],
    ]


def run_readiness() -> bool:
    """Run all readiness gates and return false without creating an archive on failure."""

    for command in readiness_commands():
        print(f"$ {' '.join(command)}")
        completed = subprocess.run(command, cwd=REPOSITORY_ROOT, check=False)
        if completed.returncode != 0:
            print("Packaging stopped: readiness checks did not pass.", file=sys.stderr)
            return False
    return True


def _is_excluded(path: Path) -> bool:
    relative = path.relative_to(REPOSITORY_ROOT)
    return bool(EXCLUDED_PARTS.intersection(relative.parts)) or path.name in EXCLUDED_FILES


def package_paths(excluded_paths: set[Path] | None = None) -> list[Path]:
    """Return sorted regular files and directories that belong in the archive."""

    excluded_paths = {path.resolve() for path in (excluded_paths or set())}
    paths = [
        path
        for path in REPOSITORY_ROOT.rglob("*")
        if (
            not _is_excluded(path)
            and path.resolve() not in excluded_paths
            and not path.is_symlink()
            and (path.is_file() or path.is_dir())
        )
    ]
    return sorted(paths, key=lambda path: path.relative_to(REPOSITORY_ROOT).as_posix())


def _normalized_info(tar_info: tarfile.TarInfo) -> tarfile.TarInfo:
    """Remove host-specific ownership and timestamps for reproducible archives."""

    tar_info.uid = 0
    tar_info.gid = 0
    tar_info.uname = ""
    tar_info.gname = ""
    tar_info.mtime = 0
    return tar_info


def _add_path(archive: tarfile.TarFile, path: Path) -> None:
    """Add one path while replacing this checkout's absolute path in file contents."""

    relative = path.relative_to(REPOSITORY_ROOT).as_posix()
    if not path.is_file():
        archive.add(path, arcname=relative, recursive=False, filter=_normalized_info)
        return

    # Evidence logs can contain the author's checkout path.  Rewrite only the
    # archive copy so local proof files remain useful and unchanged on disk.
    data = path.read_bytes().replace(
        str(REPOSITORY_ROOT).encode("utf-8"), b"/workspace"
    )
    info = archive.gettarinfo(path, arcname=relative)
    info.size = len(data)
    info = _normalized_info(info)
    archive.addfile(info, io.BytesIO(data))


def create_archive(output: Path) -> Path:
    """Create a deterministic gzip-compressed tar archive and return its path."""

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    paths = package_paths({output})
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        with temporary_path.open("wb") as raw_stream:
            with gzip.GzipFile(
                filename="", fileobj=raw_stream, mode="wb", mtime=0
            ) as gzip_stream:
                with tarfile.open(
                    fileobj=gzip_stream, mode="w", format=tarfile.PAX_FORMAT
                ) as archive:
                    for path in paths:
                        _add_path(archive, path)
        temporary_path.replace(output)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not run_readiness():
        return 1
    output = create_archive(args.output)
    print(f"Created task package: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
