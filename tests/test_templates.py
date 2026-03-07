from pathlib import Path

import pytest

from anglerfish.exceptions import TemplateError
from anglerfish.models import OneDriveTemplate, OutlookTemplate, SharePointTemplate
from anglerfish.templates import list_templates, load_template, render_template


def test_list_templates_returns_packaged_outlook_templates():
    templates = list_templates("outlook")

    assert templates
    assert all(item["path"] for item in templates)
    assert all(item["name"] for item in templates)


def test_load_packaged_template_returns_outlook_template():
    template_ref = list_templates("outlook")[0]["path"]
    template = load_template(template_ref)

    assert isinstance(template, OutlookTemplate)
    assert template.folder_name


def test_list_templates_returns_packaged_sharepoint_templates():
    templates = list_templates("sharepoint")

    assert templates
    assert all(item["path"] for item in templates)
    assert all(item["name"] for item in templates)


def test_load_packaged_template_returns_sharepoint_template():
    template_ref = list_templates("sharepoint")[0]["path"]
    template = load_template(template_ref)

    assert isinstance(template, SharePointTemplate)
    assert template.site_name
    assert template.folder_path
    assert template.filenames
    assert template.content_text


def test_load_template_missing_required_field_raises(tmp_path: Path):
    template_file = tmp_path / "bad_template.yaml"
    template_file.write_text(
        """
name: Invalid
description: Missing required fields
type: outlook
folder_name: Hidden
subject: Test
sender_name: Test
sender_email: test@contoso.com
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(TemplateError, match="missing required fields"):
        load_template(str(template_file))


def test_load_template_parses_variables(tmp_path: Path):
    template_file = tmp_path / "with_vars.yaml"
    template_file.write_text(
        """
name: VarTest
description: Template with variables
type: outlook
variables:
  - name: canary_url
    description: The callback URL
  - name: target_name
    description: Target display name
    default: User
folder_name: Folder
subject: Subject
body_html: "<p>Hello ${target_name}</p>"
sender_name: Sender
sender_email: sender@test.com
""".strip(),
        encoding="utf-8",
    )

    template = load_template(str(template_file))
    assert len(template.variables) == 2
    assert template.variables[0]["name"] == "canary_url"
    assert template.variables[1]["default"] == "User"


def test_render_template_substitutes_variables():
    template = OutlookTemplate(
        name="Test",
        description="desc",
        folder_name="${env}_folder",
        subject="Hello ${target_name}",
        body_html="<a href='${canary_url}'>click</a>",
        sender_name="IT ${dept}",
        sender_email="it@contoso.com",
        variables=[
            {"name": "canary_url", "description": "URL"},
            {"name": "target_name", "description": "Name", "default": "User"},
            {"name": "env", "description": "Environment"},
            {"name": "dept", "description": "Department", "default": "Support"},
        ],
    )

    rendered = render_template(template, {"canary_url": "https://example.com", "env": "prod"})
    assert rendered.body_html == "<a href='https://example.com'>click</a>"
    assert rendered.subject == "Hello User"
    assert rendered.folder_name == "prod_folder"
    assert rendered.sender_name == "IT Support"


def test_render_template_missing_required_variable_raises():
    template = OutlookTemplate(
        name="Test",
        description="desc",
        folder_name="Folder",
        subject="Hello",
        body_html="<p>${canary_url}</p>",
        sender_name="IT",
        sender_email="it@contoso.com",
        variables=[
            {"name": "canary_url", "description": "URL"},
        ],
    )

    with pytest.raises(TemplateError, match="Missing required template variables: canary_url"):
        render_template(template, {})


def test_render_sharepoint_template_substitutes_site_name_and_filenames():
    template = SharePointTemplate(
        name="SharePoint Test",
        description="desc",
        site_name="${site_slug}",
        folder_path="Shared Documents/${site_slug}",
        filenames=["Policy_${quarter}.docx"],
        content_text="Doc ${filename} for ${quarter}",
        variables=[
            {"name": "site_slug", "description": "Site", "default": "finance-site"},
            {"name": "quarter", "description": "Quarter", "default": "Q2-2026"},
        ],
    )

    rendered = render_template(template, {})

    assert rendered.site_name == "finance-site"
    assert rendered.folder_path == "Shared Documents/finance-site"
    assert rendered.filenames == ["Policy_Q2-2026.docx"]
    assert rendered.content_text == "Doc ${filename} for Q2-2026"


def test_load_sharepoint_template_rejects_multiple_filenames(tmp_path: Path):
    template_file = tmp_path / "bad_sharepoint_template.yaml"
    template_file.write_text(
        """
name: Bad SharePoint Template
description: Should fail
type: sharepoint
site_name: Finance
folder_path: Shared Documents/Canary
filenames:
  - one.txt
  - two.txt
content_text: Canary file ${filename}
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(TemplateError, match="must include exactly one value"):
        load_template(str(template_file))


# --- New template tests ---


def test_load_it_compliance_audit_template():
    from string import Template as StringTemplate

    templates = {t["name"]: t["path"] for t in list_templates("outlook")}
    template = load_template(templates["IT Compliance Audit Notice"])

    assert isinstance(template, OutlookTemplate)
    assert template.folder_name == "Compliance Notices"
    assert template.sender_email == "it-compliance@contoso.com"
    StringTemplate(template.body_html).safe_substitute()


def test_load_payroll_direct_deposit_update_template():
    from string import Template as StringTemplate

    templates = {t["name"]: t["path"] for t in list_templates("outlook")}
    template = load_template(templates["Payroll Direct Deposit Update"])

    assert isinstance(template, OutlookTemplate)
    assert template.folder_name == "HR - Payroll"
    assert template.sender_email == "payroll@contoso.com"
    StringTemplate(template.body_html).safe_substitute()


def test_load_acquisition_target_list_template():
    from string import Template as StringTemplate

    templates = {t["name"]: t["path"] for t in list_templates("sharepoint")}
    template = load_template(templates["M&A Acquisition Target List"])

    assert isinstance(template, SharePointTemplate)
    assert template.site_name == "Strategy"
    assert template.folder_path == "Mergers and Acquisitions/Confidential"
    assert len(template.filenames) == 1
    StringTemplate(template.content_text).safe_substitute()


def test_load_employee_salary_bands_template():
    from string import Template as StringTemplate

    templates = {t["name"]: t["path"] for t in list_templates("sharepoint")}
    template = load_template(templates["Employee Salary Bands"])

    assert isinstance(template, SharePointTemplate)
    assert template.site_name == "HR"
    assert template.folder_path == "Compensation/Restricted"
    assert len(template.filenames) == 1
    StringTemplate(template.content_text).safe_substitute()


# --- New template coverage tests ---


def test_list_templates_rejects_unsupported_type():
    with pytest.raises(TemplateError, match="Unsupported canary type"):
        list_templates("email")


def test_list_templates_uses_custom_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    outlook_dir = tmp_path / "outlook"
    outlook_dir.mkdir()
    (outlook_dir / "custom.yaml").write_text(
        "name: Custom\ndescription: A custom template\ntype: outlook\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ANGLERFISH_TEMPLATES_DIR", str(tmp_path))

    templates = list_templates("outlook")

    assert any(t["name"] == "Custom" for t in templates)


def test_list_templates_custom_dir_missing_subdir_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANGLERFISH_TEMPLATES_DIR", str(tmp_path))

    templates = list_templates("outlook")

    assert templates == []


def test_load_template_unsupported_type_raises(tmp_path: Path):
    template_file = tmp_path / "unsupported.yaml"
    template_file.write_text(
        "name: Bad\ndescription: Bad\ntype: email\nsubject: x\nbody_html: y\n",
        encoding="utf-8",
    )

    with pytest.raises(TemplateError, match="Template type must be one of"):
        load_template(str(template_file))


def test_load_template_invalid_package_path_raises():
    with pytest.raises(TemplateError, match="Invalid package template path"):
        load_template("pkg://noslash")


def test_load_template_package_template_not_found_raises():
    with pytest.raises(TemplateError, match="Template not found"):
        load_template("pkg://outlook/nonexistent_template_xyz.yaml")


def test_load_template_filesystem_path_not_found_raises():
    with pytest.raises(TemplateError, match="Template file not found"):
        load_template("/nonexistent/path/template.yaml")


def test_load_template_invalid_yaml_raises(tmp_path: Path):
    template_file = tmp_path / "invalid.yaml"
    template_file.write_text("name: Bad\n  bad indent:\n\t- broken", encoding="utf-8")

    with pytest.raises(TemplateError, match="Failed to parse YAML"):
        load_template(str(template_file))


def test_load_template_yaml_not_dict_raises(tmp_path: Path):
    template_file = tmp_path / "list.yaml"
    template_file.write_text("- item1\n- item2\n", encoding="utf-8")

    with pytest.raises(TemplateError, match="must be a YAML mapping"):
        load_template(str(template_file))


def test_load_sharepoint_template_rejects_empty_name(tmp_path: Path):
    template_file = tmp_path / "sp.yaml"
    template_file.write_text(
        "name: ''\ndescription: desc\ntype: sharepoint\nsite_name: Finance\nfolder_path: Docs\nfilenames:\n  - file.txt\ncontent_text: text\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateError, match="missing required fields"):
        load_template(str(template_file))


def test_load_sharepoint_template_rejects_empty_site_name(tmp_path: Path):
    template_file = tmp_path / "sp.yaml"
    template_file.write_text(
        "name: Test\ndescription: desc\ntype: sharepoint\nsite_name: ''\nfolder_path: Docs\nfilenames:\n  - file.txt\ncontent_text: text\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateError, match="missing required fields"):
        load_template(str(template_file))


def test_load_sharepoint_template_rejects_empty_folder_path(tmp_path: Path):
    template_file = tmp_path / "sp.yaml"
    template_file.write_text(
        "name: Test\ndescription: desc\ntype: sharepoint\nsite_name: Finance\nfolder_path: ''\nfilenames:\n  - file.txt\ncontent_text: text\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateError, match="missing required fields"):
        load_template(str(template_file))


def test_load_sharepoint_template_rejects_empty_content_text(tmp_path: Path):
    template_file = tmp_path / "sp.yaml"
    template_file.write_text(
        "name: Test\ndescription: desc\ntype: sharepoint\nsite_name: Finance\nfolder_path: Docs\nfilenames:\n  - file.txt\ncontent_text: ''\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateError, match="missing required fields"):
        load_template(str(template_file))


def test_parse_variables_rejects_non_list(tmp_path: Path):
    template_file = tmp_path / "bad_vars.yaml"
    template_file.write_text(
        "name: Test\ndescription: desc\ntype: outlook\nfolder_name: Folder\nsubject: Subject\nbody_html: '<p>x</p>'\nsender_name: IT\nsender_email: it@test.com\nvariables: not-a-list\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateError, match="must be a list"):
        load_template(str(template_file))


def test_parse_variables_rejects_entry_without_name(tmp_path: Path):
    template_file = tmp_path / "bad_var_entry.yaml"
    template_file.write_text(
        "name: Test\ndescription: desc\ntype: outlook\nfolder_name: Folder\nsubject: Subject\nbody_html: '<p>x</p>'\nsender_name: IT\nsender_email: it@test.com\nvariables:\n  - description: 'missing name key'\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateError, match="at least a 'name' key"):
        load_template(str(template_file))


def test_parse_filenames_rejects_non_list(tmp_path: Path):
    template_file = tmp_path / "bad_filenames.yaml"
    template_file.write_text(
        "name: Test\ndescription: desc\ntype: sharepoint\nsite_name: Finance\nfolder_path: Docs\nfilenames: not-a-list\ncontent_text: text\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateError, match="'filenames' must be a list"):
        load_template(str(template_file))


def test_parse_filenames_rejects_empty_string_entry(tmp_path: Path):
    template_file = tmp_path / "empty_filename.yaml"
    template_file.write_text(
        "name: Test\ndescription: desc\ntype: sharepoint\nsite_name: Finance\nfolder_path: Docs\nfilenames:\n  - ''\ncontent_text: text\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateError, match="non-empty string"):
        load_template(str(template_file))


def test_parse_filenames_rejects_empty_list(tmp_path: Path):
    template_file = tmp_path / "no_filenames.yaml"
    template_file.write_text(
        "name: Test\ndescription: desc\ntype: sharepoint\nsite_name: Finance\nfolder_path: Docs\nfilenames: []\ncontent_text: text\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateError, match="at least one value"):
        load_template(str(template_file))


def test_render_sharepoint_template_empty_site_name_raises():
    template = SharePointTemplate(
        name="Test",
        description="desc",
        site_name="${site}",
        folder_path="Docs",
        filenames=["file.txt"],
        content_text="text",
        variables=[{"name": "site", "description": "site", "default": ""}],
    )
    with pytest.raises(TemplateError, match="empty site_name"):
        render_template(template, {})


def test_render_sharepoint_template_empty_folder_path_raises():
    template = SharePointTemplate(
        name="Test",
        description="desc",
        site_name="Finance",
        folder_path="${fp}",
        filenames=["file.txt"],
        content_text="text",
        variables=[{"name": "fp", "description": "fp", "default": ""}],
    )
    with pytest.raises(TemplateError, match="empty folder_path"):
        render_template(template, {})


def test_render_sharepoint_template_empty_content_text_raises():
    template = SharePointTemplate(
        name="Test",
        description="desc",
        site_name="Finance",
        folder_path="Docs",
        filenames=["file.txt"],
        content_text="${content}",
        variables=[{"name": "content", "description": "content", "default": ""}],
    )
    with pytest.raises(TemplateError, match="empty content_text"):
        render_template(template, {})


def test_render_template_unsupported_type_raises():
    class FakeTemplate:
        variables = []

    with pytest.raises(TemplateError, match="Unsupported template object"):
        render_template(FakeTemplate(), {})


def test_load_sharepoint_template_missing_required_key_raises(tmp_path: Path):
    template_file = tmp_path / "missing_key.yaml"
    template_file.write_text(
        "name: Test\ndescription: desc\ntype: sharepoint\nsite_name: Finance\nfolder_path: Docs\ncontent_text: text\n",
        encoding="utf-8",
    )

    with pytest.raises(TemplateError, match="missing required fields"):
        load_template(str(template_file))


def test_load_outlook_template_without_variables_key_returns_empty_list(tmp_path: Path):
    template_file = tmp_path / "no_vars.yaml"
    template_file.write_text(
        "name: Test\ndescription: desc\ntype: outlook\nfolder_name: Folder\nsubject: Subject\nbody_html: '<p>test</p>'\nsender_name: IT\nsender_email: it@test.com\n",
        encoding="utf-8",
    )

    template = load_template(str(template_file))

    assert template.variables == []


def test_render_sharepoint_empty_filename_after_substitution_raises():
    template = SharePointTemplate(
        name="Test",
        description="desc",
        site_name="Finance",
        folder_path="Docs",
        filenames=["${filename}"],
        content_text="text",
        variables=[{"name": "filename", "description": "filename", "default": ""}],
    )

    with pytest.raises(TemplateError, match="empty filename"):
        render_template(template, {})


def test_load_board_meeting_minutes_template():
    from string import Template as StringTemplate

    templates = {t["name"]: t["path"] for t in list_templates("sharepoint")}
    template = load_template(templates["Board Meeting Minutes"])

    assert isinstance(template, SharePointTemplate)
    assert template.site_name == "Executive"
    assert template.folder_path == "Board/Minutes"
    assert template.filenames == ["Board_Minutes_${quarter}.docx"]
    StringTemplate(template.content_text).safe_substitute()


def test_load_compensation_analysis_template():
    from string import Template as StringTemplate

    templates = {t["name"]: t["path"] for t in list_templates("sharepoint")}
    template = load_template(templates["Compensation Analysis"])

    assert isinstance(template, SharePointTemplate)
    assert template.site_name == "HR"
    assert template.folder_path == "Compensation/Analysis"
    assert template.filenames == ["${year}_Compensation_Analysis_${department}.xlsx"]
    StringTemplate(template.content_text).safe_substitute()


def test_load_performance_review_notes_template():
    from string import Template as StringTemplate

    templates = {t["name"]: t["path"] for t in list_templates("onedrive")}
    template = load_template(templates["Performance Review Notes"])

    assert isinstance(template, OneDriveTemplate)
    assert template.folder_path == "HR/Reviews"
    assert template.filenames == ["${review_period}_Performance_Review_Notes.docx"]
    StringTemplate(template.content_text).safe_substitute()


def test_load_investment_portfolio_template():
    from string import Template as StringTemplate

    templates = {t["name"]: t["path"] for t in list_templates("onedrive")}
    template = load_template(templates["Investment Portfolio"])

    assert isinstance(template, OneDriveTemplate)
    assert template.folder_path == "Financial/Investments"
    assert template.filenames == ["Portfolio_Summary_${year}.xlsx"]
    StringTemplate(template.content_text).safe_substitute()


def test_render_sharepoint_multiple_filenames_after_substitution_raises():
    template = SharePointTemplate(
        name="Test",
        description="desc",
        site_name="Finance",
        folder_path="Docs",
        filenames=["file1.txt", "file2.txt"],
        content_text="text",
        variables=[],
    )

    with pytest.raises(TemplateError, match="multiple filenames"):
        render_template(template, {})
