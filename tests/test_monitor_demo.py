"""Tests for monitor --demo --count behaviour."""

from unittest.mock import MagicMock, patch

from anglerfish.monitor import _DEMO_BANNER, render_demo_alert


def test_render_demo_alert_default_count():
    """Default count=1 dispatches exactly one alert."""
    console = MagicMock()
    with patch("anglerfish.monitor.AlertDispatcher") as MockDispatcher:
        instance = MockDispatcher.return_value
        render_demo_alert(console)
        assert instance.dispatch.call_count == 1


def test_render_demo_alert_prints_banner():
    """Demo mode prints a clearly-marked banner so output cannot be mistaken for a live event."""
    console = MagicMock()
    with patch("anglerfish.monitor.AlertDispatcher"):
        render_demo_alert(console)
    printed = " ".join(str(c) for c in console.print.call_args_list)
    assert _DEMO_BANNER in printed


def test_render_demo_alert_marks_each_dispatched_alert():
    """Each dispatched demo alert carries the demo banner in a visible field so panels are unambiguous."""
    console = MagicMock()
    dispatched = []
    with patch("anglerfish.monitor.AlertDispatcher") as MockDispatcher:
        with patch("anglerfish.monitor.time"):
            instance = MockDispatcher.return_value
            instance.dispatch.side_effect = lambda a: dispatched.append(a.template_name)
            render_demo_alert(console, count=2)
    assert all(_DEMO_BANNER in name for name in dispatched)
    assert len(dispatched) == 2


def test_render_demo_alert_count_3():
    """count=3 dispatches three alerts while cycling draft/send demo alerts."""
    console = MagicMock()
    with patch("anglerfish.monitor.AlertDispatcher") as MockDispatcher:
        with patch("anglerfish.monitor.time") as mock_time:
            instance = MockDispatcher.return_value
            render_demo_alert(console, count=3)
            assert instance.dispatch.call_count == 3
            # Sleep between alerts but not after the last
            assert mock_time.sleep.call_count == 2


def test_render_demo_alert_cycles_outlook_modes():
    """Alerts cycle through outlook draft/send modes only."""
    console = MagicMock()
    dispatched = []
    with patch("anglerfish.monitor.AlertDispatcher") as MockDispatcher:
        with patch("anglerfish.monitor.time"):
            instance = MockDispatcher.return_value
            instance.dispatch.side_effect = lambda a: dispatched.append(a.canary_type)
            render_demo_alert(console, count=2)
    assert dispatched == ["outlook (draft)", "outlook (send)"]
