"""Read the small, dependency-free acceptance-criteria YAML format."""

from __future__ import annotations

from pathlib import Path


def read_acceptance(path: Path) -> tuple[str, list[dict[str, object]]]:
    """Return the task ID and criteria from an acceptance-criteria file.

    The authoring format intentionally supports only a top-level ``task_id``
    and a list of scalar criterion properties. This keeps the shared harness
    dependency-free and makes malformed hand-authored files fail clearly.
    """

    if not path.is_file():
        raise SystemExit(f"missing acceptance-criteria.yml: {path}")
    task_id = ""
    criteria: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        stripped = line.strip()
        if not stripped or stripped == "criteria:":
            continue
        if stripped.startswith("task_id:"):
            task_id = stripped.split(":", 1)[1].strip().strip("'\"")
            continue
        if stripped.startswith("- "):
            if current is not None:
                criteria.append(current)
            current = {}
            stripped = stripped[2:].strip()
        if current is None or ":" not in stripped:
            continue
        key, value = (part.strip() for part in stripped.split(":", 1))
        value = value.strip("'\"")
        if key == "weight":
            try:
                current[key] = float(value)
            except ValueError as exc:
                raise SystemExit(f"invalid acceptance weight for criterion: {value}") from exc
        else:
            current[key] = value
    if current is not None:
        criteria.append(current)
    if not task_id:
        raise SystemExit("acceptance-criteria.yml must contain task_id")
    if not criteria:
        raise SystemExit("acceptance-criteria.yml must contain criteria")
    return task_id, criteria
