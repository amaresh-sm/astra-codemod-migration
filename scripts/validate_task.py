#!/usr/bin/env python3
"""Validate the public/private layout and metadata of one task package."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    tomllib = None

PROFILES = {"brownfield", "greenfield", "migration", "frontend"}
PRIVATE_NAMES = {
    "verifier",
    "hidden-tests",
    "reference-solution",
    "mutants",
    "proof-of-work",
    "acceptance-criteria.yml",
    "scoring.yml",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an ASTRA task package")
    parser.add_argument("task_dir", type=Path)
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def load_task(path: Path) -> dict[str, object]:
    if tomllib is None:
        fail("Python 3.11+ is required (or install the tomli compatibility package)")
    try:
        with path.open("rb") as stream:
            value = tomllib.load(stream)
    except FileNotFoundError:
        fail("task.toml is required")
    except tomllib.TOMLDecodeError as exc:
        fail(f"invalid task.toml: {exc}")
    if not isinstance(value, dict):
        fail("task.toml must contain a table")
    return value


def validate(task_dir: Path) -> None:
    if not task_dir.is_dir():
        fail(f"task directory does not exist: {task_dir}")
    task = load_task(task_dir / "task.toml")
    task_id = task.get("id")
    profile = task.get("profile")
    title = task.get("title")
    if not isinstance(task_id, str) or not task_id or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in task_id
    ) or task_id[0] == "-":
        fail("task.toml: id must be non-empty kebab-case")
    if profile not in PROFILES:
        fail(f"task.toml: unsupported profile {profile!r}")
    if not isinstance(title, str) or not title.strip():
        fail("task.toml: title is required")
    instruction = task_dir / "instruction.md"
    if not instruction.is_file():
        fail("instruction.md is required")

    public_dir = task_dir / "public"
    if public_dir.exists():
        for path in public_dir.rglob("*"):
            if any(part in PRIVATE_NAMES for part in path.relative_to(public_dir).parts):
                fail(f"private file under public/: {path.relative_to(task_dir)}")

    print(f"Valid task package: {task_id} ({profile})")


if __name__ == "__main__":
    try:
        validate(parse_args().task_dir.resolve())
    except OSError as exc:
        fail(str(exc))
