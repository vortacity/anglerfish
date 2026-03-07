"""Static SIEM query generator for canary detection."""

from __future__ import annotations

from .inventory import read_deployment_record


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def generate_query(record_path: str, *, fmt: str = "kql") -> str:
    """Generate a detection query from a deployment record.

    Supported formats: ``kql``, ``splunk``, ``odata``.
    """
    rec = read_deployment_record(record_path)
    canary_type = rec.get("canary_type") or rec.get("type", "")

    generators = {
        "kql": _generate_kql,
        "splunk": _generate_splunk,
        "odata": _generate_odata,
    }
    gen = generators.get(fmt.lower())
    if gen is None:
        raise ValueError(f"Unsupported format '{fmt}'. Choose from: {', '.join(generators)}")
    return gen(canary_type, rec)


# ------------------------------------------------------------------
# KQL
# ------------------------------------------------------------------


def _generate_kql(canary_type: str, rec: dict) -> str:
    if canary_type == "outlook":
        return _kql_outlook(rec)
    if canary_type in ("sharepoint", "onedrive"):
        return _kql_file(rec)
    return f"// Unsupported canary type: {canary_type}"


def _kql_outlook(rec: dict) -> str:
    target_user = rec.get("target_user", "")
    internet_message_id = rec.get("internet_message_id", "")
    folder_name = rec.get("folder_name", "")

    lines = [
        "OfficeActivity",
        '| where Operation == "MailItemsAccessed"',
    ]
    if target_user:
        lines.append(f'| where MailboxOwnerUPN =~ "{target_user}"')
    if internet_message_id:
        lines.extend(
            [
                "| mv-expand Folders",
                "| mv-expand Folders.FolderItems",
                f'| where Folders_FolderItems.InternetMessageId == "{internet_message_id}"',
            ]
        )
    elif folder_name:
        lines.extend(
            [
                "| mv-expand Folders",
                f'| where Folders.Path contains "{folder_name}"',
            ]
        )
    lines.append("| project TimeGenerated, UserId, ClientIP, Operation, MailboxOwnerUPN")
    return "\n".join(lines)


def _kql_file(rec: dict) -> str:
    uploaded_files = rec.get("uploaded_files", "")
    if isinstance(uploaded_files, list):
        filename = uploaded_files[0] if uploaded_files else ""
    else:
        filename = str(uploaded_files).split(",")[0].strip() if uploaded_files else ""

    site_name = rec.get("site_name", "")
    target_user = rec.get("target_user", "")

    lines = [
        "OfficeActivity",
        '| where Operation in ("FileAccessed", "FileDownloaded")',
    ]
    if filename:
        lines.append(f'| where OfficeObjectId contains "{filename}"')
    if site_name:
        lines.append(f'| where SiteUrl contains "{site_name}"')
    elif target_user:
        lines.append(f'| where UserId != "{target_user}" or 1==1')
        # Provide a hint about the OneDrive owner.
        lines[-1] = f"// OneDrive owner: {target_user}"
    lines.append("| project TimeGenerated, UserId, ClientIP, Operation, OfficeObjectId")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Splunk SPL
# ------------------------------------------------------------------


def _generate_splunk(canary_type: str, rec: dict) -> str:
    if canary_type == "outlook":
        return _splunk_outlook(rec)
    if canary_type in ("sharepoint", "onedrive"):
        return _splunk_file(rec)
    return f"| noop `Unsupported canary type: {canary_type}`"


def _splunk_outlook(rec: dict) -> str:
    target_user = rec.get("target_user", "")
    internet_message_id = rec.get("internet_message_id", "")
    folder_name = rec.get("folder_name", "")

    parts = [
        'index=o365 sourcetype="o365:management:activity"',
        'Operation="MailItemsAccessed"',
    ]
    if target_user:
        parts.append(f'MailboxOwnerUPN="{target_user}"')
    if internet_message_id:
        parts.append(f'Folders{{}}.FolderItems{{}}.InternetMessageId="{internet_message_id}"')
    elif folder_name:
        parts.append(f'Folders{{}}.Path="*{folder_name}*"')
    parts.append("| table _time, UserId, ClientIP, Operation, MailboxOwnerUPN")
    return "\n".join(parts)


def _splunk_file(rec: dict) -> str:
    uploaded_files = rec.get("uploaded_files", "")
    if isinstance(uploaded_files, list):
        filename = uploaded_files[0] if uploaded_files else ""
    else:
        filename = str(uploaded_files).split(",")[0].strip() if uploaded_files else ""

    site_name = rec.get("site_name", "")

    parts = [
        'index=o365 sourcetype="o365:management:activity"',
        '(Operation="FileAccessed" OR Operation="FileDownloaded")',
    ]
    if filename:
        parts.append(f'SourceFileName="{filename}"')
    if site_name:
        parts.append(f'SiteUrl="*{site_name}*"')
    parts.append("| table _time, UserId, ClientIP, Operation, SourceFileName, ObjectId")
    return "\n".join(parts)


# ------------------------------------------------------------------
# OData filter
# ------------------------------------------------------------------


def _generate_odata(canary_type: str, rec: dict) -> str:
    if canary_type == "outlook":
        return _odata_outlook(rec)
    if canary_type in ("sharepoint", "onedrive"):
        return _odata_file(rec)
    return f"# Unsupported canary type: {canary_type}"


def _odata_outlook(rec: dict) -> str:
    target_user = rec.get("target_user", "")
    parts = ["Operation eq 'MailItemsAccessed'"]
    if target_user:
        parts.append(f"MailboxOwnerUPN eq '{target_user}'")
    return " and ".join(parts)


def _odata_file(rec: dict) -> str:
    uploaded_files = rec.get("uploaded_files", "")
    if isinstance(uploaded_files, list):
        filename = uploaded_files[0] if uploaded_files else ""
    else:
        filename = str(uploaded_files).split(",")[0].strip() if uploaded_files else ""

    parts = ["(Operation eq 'FileAccessed' or Operation eq 'FileDownloaded')"]
    if filename:
        parts.append(f"contains(ObjectId, '{filename}')")
    return " and ".join(parts)
