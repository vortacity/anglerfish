"""Configuration constants for Anglerfish."""

from __future__ import annotations

import os

CLIENT_ID = os.environ.get("ANGLERFISH_CLIENT_ID", "").strip()
TENANT_ID = os.environ.get("ANGLERFISH_TENANT_ID", "").strip()
AUTH_MODE = os.environ.get("ANGLERFISH_AUTH_MODE", "application").strip().lower()
CLIENT_SECRET = os.environ.get("ANGLERFISH_CLIENT_SECRET", "").strip()
APP_CREDENTIAL_MODE = os.environ.get("ANGLERFISH_APP_CREDENTIAL_MODE", "auto").strip().lower()

CLIENT_CERT_PFX_PATH = os.environ.get("ANGLERFISH_CLIENT_CERT_PFX_PATH", "").strip()
CLIENT_CERT_PRIVATE_KEY_PATH = os.environ.get("ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH", "").strip()
CLIENT_CERT_PUBLIC_CERT_PATH = os.environ.get("ANGLERFISH_CLIENT_CERT_PUBLIC_CERT_PATH", "").strip()
CLIENT_CERT_THUMBPRINT = os.environ.get("ANGLERFISH_CLIENT_CERT_THUMBPRINT", "").strip()
CLIENT_CERT_PASSPHRASE = os.environ.get("ANGLERFISH_CLIENT_CERT_PASSPHRASE", "")
CLIENT_CERT_SEND_X5C = os.environ.get("ANGLERFISH_CLIENT_CERT_SEND_X5C", "").strip().lower()

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_APP_SCOPE = "https://graph.microsoft.com/.default"
GRAPH_DELEGATED_SCOPES = os.environ.get("ANGLERFISH_GRAPH_DELEGATED_SCOPES", "").strip()

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
TEMPLATE_KIND_SHAREPOINT = "sharepoint"
TEMPLATE_KIND_ONEDRIVE = "onedrive"
