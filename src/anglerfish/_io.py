"""Shared filesystem and timestamp helpers."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def write_json_atomic(
    path: Path,
    payload: dict,
    *,
    error_cls: type[Exception],
    label: str = "file",
    indent: int | None = 2,
) -> None:
    """Write JSON to *path* atomically: temp file + 0o600 + fsync + os.replace.

    Raises *error_cls* on OSError so each caller surfaces its own domain error,
    with *label* naming the artifact in the message.
    """
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as fh:
            temp_path = Path(fh.name)
            if hasattr(os, "fchmod"):  # POSIX only; no-op on platforms without fchmod
                os.fchmod(fh.fileno(), 0o600)
            json.dump(payload, fh, indent=indent)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
    except OSError as exc:
        raise error_cls(f"Failed to write {label} '{path}': {exc}") from exc
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def parse_utc_datetime(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp into an aware UTC datetime.

    Tolerates the 'Z' suffix (rejected by Python 3.10's fromisoformat) and
    coerces naive timestamps to UTC. Returns ``None`` for blank or invalid
    input.
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return as_utc(parsed)


def as_utc(value: datetime) -> datetime:
    """Coerce a datetime to aware UTC (naive values are assumed to be UTC)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
