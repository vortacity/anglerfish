"""Textual TUI dashboard for canary monitoring."""

from __future__ import annotations

import random
from datetime import datetime, timezone

from .monitor import CanaryAlert
from .verify import VerifyResult, VerifyStatus


# ------------------------------------------------------------------
# Demo data provider
# ------------------------------------------------------------------

_DEMO_RECORDS: list[tuple[str, dict]] = [
    (
        "~/.anglerfish/records/outlook-cfo-draft.json",
        {
            "canary_type": "outlook",
            "template_name": "Fake Password Reset",
            "target_user": "cfo@contoso.com",
            "folder_name": "IT Notifications",
            "folder_id": "folder-demo-1",
            "internet_message_id": "<demo-msg-1@contoso.com>",
            "subject": "Password Reset Required",
            "status": "active",
        },
    ),
    (
        "~/.anglerfish/records/outlook-hr-send.json",
        {
            "canary_type": "outlook",
            "template_name": "Benefits Update",
            "target_user": "hr@contoso.com",
            "folder_name": "Benefits",
            "folder_id": "folder-demo-2",
            "internet_message_id": "<demo-msg-2@contoso.com>",
            "subject": "Benefits Enrollment",
            "status": "active",
        },
    ),
    (
        "~/.anglerfish/records/sharepoint-hr-salary.json",
        {
            "canary_type": "sharepoint",
            "template_name": "Employee Salary Bands",
            "site_name": "HRSite",
            "site_id": "contoso.sharepoint.com,site-demo-1,web-demo-1",
            "item_id": "item-demo-1",
            "uploaded_files": "salary_bands_2026.xlsx",
            "status": "active",
        },
    ),
    (
        "~/.anglerfish/records/sharepoint-finance-budget.json",
        {
            "canary_type": "sharepoint",
            "template_name": "Q1 Budget Draft",
            "site_name": "FinanceSite",
            "site_id": "contoso.sharepoint.com,site-demo-2,web-demo-2",
            "item_id": "item-demo-2",
            "uploaded_files": "q1_budget_draft.docx",
            "status": "active",
        },
    ),
    (
        "~/.anglerfish/records/onedrive-vpn-config.json",
        {
            "canary_type": "onedrive",
            "template_name": "VPN Credentials Backup",
            "target_user": "j.smith@contoso.com",
            "item_id": "item-demo-3",
            "uploaded_files": "vpn_config.txt",
            "status": "active",
        },
    ),
]

_DEMO_ATTACKERS = [
    ("attacker@evil.com", "203.0.113.42"),
    ("scout@evil.com", "198.51.100.7"),
    ("recon@badactor.net", "192.0.2.99"),
    ("phisher@shady.org", "198.51.100.15"),
    ("apt29@cozylair.ru", "203.0.113.55"),
]

_DEMO_OPERATIONS = {
    "outlook": "MailItemsAccessed",
    "sharepoint": "FileAccessed",
    "onedrive": "FileAccessed",
}


class DemoDataProvider:
    """Synthetic data for --demo mode. No API calls."""

    def __init__(self) -> None:
        self._records = _DEMO_RECORDS
        self._verify_statuses = [
            VerifyStatus.OK,
            VerifyStatus.OK,
            VerifyStatus.GONE,
            VerifyStatus.OK,
            VerifyStatus.OK,
        ]

    def records(self) -> list[tuple[str, dict]]:
        return list(self._records)

    def verify_results(self) -> list[VerifyResult]:
        results: list[VerifyResult] = []
        for i, (_, rec) in enumerate(self._records):
            status = self._verify_statuses[i]
            target = rec.get("target_user") or rec.get("site_name", "")
            detail = "404 Not Found" if status == VerifyStatus.GONE else ""
            results.append(
                VerifyResult(
                    canary_type=rec["canary_type"],
                    template_name=rec["template_name"],
                    target=target,
                    status=status,
                    detail=detail,
                )
            )
        return results

    def generate_alert(self) -> CanaryAlert:
        rec_path, rec = random.choice(self._records)
        attacker, ip = random.choice(_DEMO_ATTACKERS)
        canary_type = rec["canary_type"]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        artifact = rec.get("internet_message_id") or rec.get("item_id", "")
        return CanaryAlert(
            canary_type=canary_type,
            template_name=rec["template_name"],
            artifact_label=f"demo: {artifact}",
            accessed_by=attacker,
            source_ip=ip,
            timestamp=now,
            operation=_DEMO_OPERATIONS.get(canary_type, "FileAccessed"),
            client_info="Client=DemoMode",
            record_path=rec_path,
        )

    def cycle_verify_status(self) -> None:
        """Rotate one random status to simulate changes."""
        idx = random.randint(0, len(self._verify_statuses) - 1)
        current = self._verify_statuses[idx]
        choices = [s for s in VerifyStatus if s != current]
        self._verify_statuses[idx] = random.choice(choices)
