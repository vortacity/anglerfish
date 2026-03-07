"""Tests for monitor state persistence (state.py)."""

from __future__ import annotations

import json

from anglerfish.state import StateManager, _MAX_SEEN_IDS


# ------------------------------------------------------------------
# Cold start
# ------------------------------------------------------------------


def test_cold_start_creates_blank_state(tmp_path):
    sm = StateManager(tmp_path / "state.json")
    s = sm.state

    assert s.last_poll_end == ""
    assert s.seen_ids == []
    assert s.total_alerts == 0
    assert s.total_polls == 0
    assert s.started_at != ""


# ------------------------------------------------------------------
# Save and reload
# ------------------------------------------------------------------


def test_save_and_reload(tmp_path):
    path = tmp_path / "state.json"

    sm = StateManager(path)
    sm.mark_seen("evt-001")
    sm.mark_seen("evt-002")
    sm.record_poll("2026-03-05T14:00:00Z", alerts=1)
    sm.save()

    # Reload in a new manager.
    sm2 = StateManager(path)
    s2 = sm2.state

    assert s2.last_poll_end == "2026-03-05T14:00:00Z"
    assert s2.total_polls == 1
    assert s2.total_alerts == 1
    assert sm2.is_seen("evt-001")
    assert sm2.is_seen("evt-002")
    assert not sm2.is_seen("evt-999")


# ------------------------------------------------------------------
# Deduplication
# ------------------------------------------------------------------


def test_is_seen_and_mark_seen(tmp_path):
    sm = StateManager(tmp_path / "state.json")
    assert not sm.is_seen("a")

    sm.mark_seen("a")
    assert sm.is_seen("a")

    # Marking again is a no-op.
    sm.mark_seen("a")
    assert sm.is_seen("a")


def test_seen_ids_bounded(tmp_path):
    sm = StateManager(tmp_path / "state.json")

    # Fill beyond the max.
    for i in range(_MAX_SEEN_IDS + 100):
        sm.mark_seen(f"evt-{i}")

    # The oldest IDs should be evicted.
    assert not sm.is_seen("evt-0")
    assert not sm.is_seen("evt-99")
    # Recent IDs should still be present.
    assert sm.is_seen(f"evt-{_MAX_SEEN_IDS + 99}")


# ------------------------------------------------------------------
# record_poll accumulates
# ------------------------------------------------------------------


def test_record_poll_accumulates(tmp_path):
    sm = StateManager(tmp_path / "state.json")
    sm.record_poll("2026-03-05T14:00:00Z", alerts=2)
    sm.record_poll("2026-03-05T14:05:00Z", alerts=1)

    s = sm.state
    assert s.total_polls == 2
    assert s.total_alerts == 3
    assert s.last_poll_end == "2026-03-05T14:05:00Z"


# ------------------------------------------------------------------
# Atomic write
# ------------------------------------------------------------------


def test_save_creates_parent_directories(tmp_path):
    path = tmp_path / "deep" / "nested" / "state.json"
    sm = StateManager(path)
    sm.record_poll("2026-03-05T14:00:00Z", alerts=0)
    sm.save()

    assert path.is_file()
    data = json.loads(path.read_text())
    assert data["total_polls"] == 1


# ------------------------------------------------------------------
# Corrupted state file
# ------------------------------------------------------------------


def test_invalid_json_raises_monitor_error(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not valid json!!!")

    import pytest

    from anglerfish.exceptions import MonitorError

    with pytest.raises(MonitorError):
        StateManager(path).state


def test_non_dict_json_raises_monitor_error(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps([1, 2, 3]))

    import pytest

    from anglerfish.exceptions import MonitorError

    with pytest.raises(MonitorError):
        StateManager(path).state
