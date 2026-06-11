"""Configuration constants for Anglerfish."""

from __future__ import annotations

import os

# Credentials are NOT snapshotted here: auth.AuthConfig.resolved_with_env()
# reads the ANGLERFISH_* credential variables at authentication time, so there
# is exactly one read path and no import-time staleness.

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_APP_SCOPE = "https://graph.microsoft.com/.default"

MANAGEMENT_API_BASE_URL = "https://manage.office.com/api/v1.0"
MANAGEMENT_API_SCOPE = "https://manage.office.com/.default"

MONITOR_STATE_FILE = os.environ.get("ANGLERFISH_MONITOR_STATE_FILE", "").strip()
MONITOR_ALERT_LOG = os.environ.get("ANGLERFISH_MONITOR_ALERT_LOG", "").strip()
MONITOR_SLACK_WEBHOOK = os.environ.get("ANGLERFISH_SLACK_WEBHOOK_URL", "").strip()
MONITOR_NO_CONSOLE = os.environ.get("ANGLERFISH_MONITOR_NO_CONSOLE", "").strip().lower() in (
    "1",
    "true",
    "yes",
)

TEMPLATES_ENV_VAR = "ANGLERFISH_TEMPLATES_DIR"
TEMPLATE_KIND_OUTLOOK = "outlook"
