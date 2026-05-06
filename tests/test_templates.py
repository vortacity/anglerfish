from pathlib import Path

import pytest

from anglerfish.exceptions import TemplateError
from anglerfish.models import OutlookTemplate
from anglerfish.templates import list_templates, load_template, render_template

OUTLOOK_TEMPLATE_YAML = """
name: Custom Outlook
description: Custom template
type: outlook
folder_name: Inbox
subject: Subject
body_html: "<p>Body</p>"
sender_name: Sender
sender_email: sender@example.com
""".strip()


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


def test_list_templates_rejects_unsupported_type():
    with pytest.raises(TemplateError, match="Unsupported canary type"):
        list_templates("email")


def test_list_templates_rejects_removed_sharepoint_type():
    with pytest.raises(TemplateError, match="outlook"):
        list_templates("sharepoint")


def test_custom_outlook_template_dir_still_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    outlook_dir = tmp_path / "outlook"
    outlook_dir.mkdir()
    (outlook_dir / "custom.yaml").write_text(OUTLOOK_TEMPLATE_YAML, encoding="utf-8")
    monkeypatch.setenv("ANGLERFISH_TEMPLATES_DIR", str(tmp_path))

    assert list_templates("outlook")[0]["name"] == "Custom Outlook"


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


def test_load_outlook_template_without_variables_key_returns_empty_list(tmp_path: Path):
    template_file = tmp_path / "no_vars.yaml"
    template_file.write_text(
        "name: Test\ndescription: desc\ntype: outlook\nfolder_name: Folder\nsubject: Subject\nbody_html: '<p>test</p>'\nsender_name: IT\nsender_email: it@test.com\n",
        encoding="utf-8",
    )

    template = load_template(str(template_file))

    assert template.variables == []


def test_render_template_unsupported_type_raises():
    class FakeTemplate:
        variables = []

    with pytest.raises(TemplateError, match="Unsupported template object"):
        render_template(FakeTemplate(), {})
