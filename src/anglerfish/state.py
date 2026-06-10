"""Persistent monitor state: watermark, seen event IDs, poll/alert counters."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ._io import parse_utc_datetime, write_json_atomic
from .exceptions import MonitorError

_DEFAULT_STATE_PATH = Path.home() / ".anglerfish" / "monitor-state.json"
_MAX_SEEN_IDS = 50_000


@dataclass
class MonitorState:
    """Serializable snapshot of monitor progress."""

    last_poll_end: str = ""
    seen_ids: list[str] = field(default_factory=list)
    total_alerts: int = 0
    total_polls: int = 0
    started_at: str = ""


class StateManager:
    """Load, update, and persist monitor state to a JSON file.

    Cold start (no file): returns a blank state with ``started_at`` set to now.
    Warm restart: loads from disk, resumes from ``last_poll_end``.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else _DEFAULT_STATE_PATH
        self._state: MonitorState | None = None
        self._seen_deque: deque[str] = deque(maxlen=_MAX_SEEN_IDS)
        self._seen_set: set[str] = set()

    @property
    def state(self) -> MonitorState:
        if self._state is None:
            self._state = self._load()
        return self._state

    def _load(self) -> MonitorState:
        """Load state from disk or create a fresh state."""
        if self.path.is_file():
            try:
                with self.path.open("r", encoding="utf-8") as fh:
                    raw = json.load(fh)
            except (OSError, json.JSONDecodeError) as exc:
                raise MonitorError(f"Failed to read monitor state '{self.path}': {exc}") from exc
            if not isinstance(raw, dict):
                raise MonitorError(f"Monitor state '{self.path}' is not a valid JSON object.")

            seen_ids = raw.get("seen_ids") or []
            if not isinstance(seen_ids, list):
                raise MonitorError(f"Monitor state '{self.path}' has a non-list 'seen_ids' field.")
            try:
                state = MonitorState(
                    last_poll_end=str(raw.get("last_poll_end") or ""),
                    seen_ids=[str(eid) for eid in seen_ids],
                    total_alerts=int(raw.get("total_alerts") or 0),
                    total_polls=int(raw.get("total_polls") or 0),
                    started_at=str(raw.get("started_at") or ""),
                )
            except (TypeError, ValueError) as exc:
                raise MonitorError(f"Monitor state '{self.path}' contains invalid field values: {exc}") from exc
            if state.last_poll_end and parse_utc_datetime(state.last_poll_end) is None:
                raise MonitorError(f"Monitor state '{self.path}' has an invalid 'last_poll_end' timestamp.")
            # Rebuild lookup structures from persisted IDs.
            for eid in state.seen_ids[-_MAX_SEEN_IDS:]:
                self._seen_deque.append(eid)
                self._seen_set.add(eid)
            return state

        # Cold start.
        return MonitorState(started_at=datetime.now(timezone.utc).isoformat())

    def is_seen(self, event_id: str) -> bool:
        _ = self.state  # ensure loaded
        return event_id in self._seen_set

    def mark_seen(self, event_id: str) -> None:
        _ = self.state  # ensure loaded
        if event_id in self._seen_set:
            return
        # If deque is at capacity, evict the oldest ID from the set.
        if len(self._seen_deque) == self._seen_deque.maxlen:
            evicted = self._seen_deque[0]
            self._seen_set.discard(evicted)
        self._seen_deque.append(event_id)
        self._seen_set.add(event_id)

    def record_poll(self, end_time: str, alerts: int) -> None:
        """Update counters after a completed poll cycle."""
        s = self.state
        s.last_poll_end = end_time
        s.total_polls += 1
        s.total_alerts += alerts

    def save(self) -> None:
        """Persist current state to disk atomically."""
        s = self.state
        s.seen_ids = list(self._seen_deque)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_poll_end": s.last_poll_end,
            "seen_ids": s.seen_ids,
            "total_alerts": s.total_alerts,
            "total_polls": s.total_polls,
            "started_at": s.started_at,
        }
        write_json_atomic(self.path, payload, error_cls=MonitorError, label="monitor state")
