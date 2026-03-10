"""Tests for monitor --demo --count behaviour."""

from unittest.mock import MagicMock, patch

from anglerfish.monitor import render_demo_alert


def test_render_demo_alert_default_count():
    """Default count=1 dispatches exactly one alert."""
    console = MagicMock()
    with patch("anglerfish.monitor.AlertDispatcher") as MockDispatcher:
        instance = MockDispatcher.return_value
        render_demo_alert(console)
        assert instance.dispatch.call_count == 1


def test_render_demo_alert_count_3():
    """count=3 dispatches three alerts cycling through canary types."""
    console = MagicMock()
    with patch("anglerfish.monitor.AlertDispatcher") as MockDispatcher:
        with patch("anglerfish.monitor.time") as mock_time:
            instance = MockDispatcher.return_value
            render_demo_alert(console, count=3)
            assert instance.dispatch.call_count == 3
            # Sleep between alerts but not after the last
            assert mock_time.sleep.call_count == 2


def test_render_demo_alert_cycles_canary_types():
    """Alerts cycle through outlook, sharepoint, onedrive."""
    console = MagicMock()
    dispatched = []
    with patch("anglerfish.monitor.AlertDispatcher") as MockDispatcher:
        with patch("anglerfish.monitor.time"):
            instance = MockDispatcher.return_value
            instance.dispatch.side_effect = lambda a: dispatched.append(a.canary_type)
            render_demo_alert(console, count=3)
    assert dispatched == ["outlook (draft)", "sharepoint", "onedrive"]
