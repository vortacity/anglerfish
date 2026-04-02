"""Validators, auth prompts, template rendering, and UI constants."""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import questionary
from questionary import Style
from rich.console import Console

from ..exceptions import (
    AuthenticationError,
    DeploymentError,
    TemplateError,
)
from ..models import OutlookTemplate
from ..templates import render_template

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_STYLE = Style(
    [
        ("qmark", "fg:#5f8fd4 bold"),
        ("question", "bold"),
        ("answer", "fg:#61afef bold"),
        ("pointer", "fg:#61afef bold"),
        ("highlighted", "fg:#61afef bold"),
        ("selected", "fg:#98c379"),
        ("instruction", "fg:#7f848e italic"),
        ("text", ""),
        ("separator", "fg:#7f848e"),
        ("disabled", "fg:#7f848e"),
    ]
)

_QMARK = "\u2022"
_POINTER = ">"
_SHAREPOINT_LIBRARY_PREFIXES = {"shared documents", "documents"}


@dataclass(frozen=True)
class AuthPromptResult:
    credential_mode: str
    clear_env_vars: tuple[str, ...] = ()


def _validate_email(value: str) -> bool | str:
    candidate = value.strip()
    if _EMAIL_PATTERN.match(candidate):
        return True
    return "Enter a valid email address (example: user@domain.com)."


def _validate_non_empty(value: str) -> bool | str:
    if value.strip():
        return True
    return "This value is required."


def _validate_file_path(value: str) -> bool | str:
    if Path(value.strip()).is_file():
        return True
    return "Enter a valid file path."


def _validate_single_filename(value: str) -> bool | str:
    filename = value.strip()
    if not filename:
        return "Enter a filename."
    if "," in filename:
        return "Enter exactly one filename."
    if "/" in filename or "\\" in filename:
        return "Filename must not contain path separators."
    return True


def _normalize_sharepoint_folder_path(value: str) -> str:
    segments: list[str] = []
    for raw_segment in value.strip().strip("/").split("/"):
        segment = raw_segment.strip()
        if segment:
            segments.append(segment)

    if not segments:
        return ""

    first_segment = unquote(segments[0]).strip().casefold()
    if first_segment in _SHAREPOINT_LIBRARY_PREFIXES:
        segments = segments[1:]

    return "/".join(segments)


def _validate_sharepoint_folder_path(value: str) -> bool | str:
    normalized = _normalize_sharepoint_folder_path(value)
    if not normalized:
        return "Enter a folder path under the site (example: HR/Restricted)."
    if len(normalized) > 400:
        return "Folder path must not exceed 400 characters."
    return True


def _validate_subject(value: str) -> bool | str:
    if not value.strip():
        return "This value is required."
    if len(value.strip()) > 255:
        return "Subject must not exceed 255 characters."
    return True


def _validate_variable_value(value: str) -> bool | str:
    if len(value) > 500:
        return "Variable value must not exceed 500 characters."
    return True


def _parse_var_args(var_args: list[str]) -> dict[str, str]:
    """Parse a list of 'KEY=VALUE' strings into a dict."""
    result: dict[str, str] = {}
    for arg in var_args:
        if "=" not in arg:
            raise TemplateError(f"Invalid --var argument {arg!r}. Expected KEY=VALUE format.")
        key, _, value = arg.partition("=")
        key = key.strip()
        if not key:
            raise TemplateError(f"Invalid --var argument {arg!r}. Key cannot be empty.")
        if len(value) > 500:
            raise TemplateError(f"Variable value for {key!r} exceeds 500 characters.")
        result[key] = value
    return result


def _prompt_auth_setup(
    args: argparse.Namespace,
    console: Console,
    *,
    auth_mode: str = "application",
    non_interactive: bool = False,
) -> AuthPromptResult | None:
    selected_auth_mode = auth_mode.strip().lower()
    if selected_auth_mode in ("", "application"):
        selected_auth_mode = "application"
    else:
        raise AuthenticationError("Only application auth is supported in this release.")

    cli_tenant_id = str(args.tenant_id or "").strip()
    if cli_tenant_id:
        os.environ["ANGLERFISH_TENANT_ID"] = cli_tenant_id

    cli_client_id = str(args.client_id or "").strip()
    if cli_client_id:
        os.environ["ANGLERFISH_CLIENT_ID"] = cli_client_id

    if not os.environ.get("ANGLERFISH_TENANT_ID", "").strip():
        if non_interactive:
            raise AuthenticationError(
                "ANGLERFISH_TENANT_ID is not set. Provide it via environment variable or --tenant-id."
            )
        console.print("ANGLERFISH_TENANT_ID is not set. Please provide your tenant ID.")
        tenant_id = questionary.text(
            "Entra Directory (tenant) ID:",
            validate=_validate_non_empty,
            style=_STYLE,
            qmark=_QMARK,
        ).ask()
        if tenant_id is None:
            return None
        tenant_value = tenant_id.strip()
        if tenant_value:
            os.environ["ANGLERFISH_TENANT_ID"] = tenant_value

    if not os.environ.get("ANGLERFISH_CLIENT_ID", "").strip():
        if non_interactive:
            raise AuthenticationError(
                "ANGLERFISH_CLIENT_ID is not set. Provide it via environment variable or --client-id."
            )
        console.print("ANGLERFISH_CLIENT_ID is not set. Let's configure it now.")
        client_id = questionary.text(
            "Entra Application (client) ID:", validate=_validate_non_empty, style=_STYLE, qmark=_QMARK
        ).ask()
        if client_id is None:
            return None
        os.environ["ANGLERFISH_CLIENT_ID"] = client_id.strip()

    os.environ["ANGLERFISH_AUTH_MODE"] = selected_auth_mode

    current_mode = args.credential_mode or os.environ.get("ANGLERFISH_APP_CREDENTIAL_MODE", "auto").strip().lower()
    if current_mode not in ("auto", "secret", "certificate"):
        current_mode = "auto"

    clear_env_vars: list[str] = []

    has_secret = bool(os.environ.get("ANGLERFISH_CLIENT_SECRET", "").strip())
    has_certificate = bool(
        os.environ.get("ANGLERFISH_CLIENT_CERT_PFX_PATH", "").strip()
        or os.environ.get("ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH", "").strip()
        or os.environ.get("ANGLERFISH_CLIENT_CERT_PUBLIC_CERT_PATH", "").strip()
        or os.environ.get("ANGLERFISH_CLIENT_CERT_THUMBPRINT", "").strip()
    )

    if current_mode == "auto":
        if has_secret and has_certificate:
            if non_interactive:
                # Default to secret when both are present and mode is unspecified.
                current_mode = "secret"
            else:
                selected = questionary.select(
                    "Both secret and certificate settings are present. Which should be used for this run?",
                    choices=[
                        questionary.Choice("Client secret", value="secret"),
                        questionary.Choice("Certificate", value="certificate"),
                    ],
                    style=_STYLE,
                    qmark=_QMARK,
                    pointer=_POINTER,
                ).ask()
                if selected is None:
                    return None
                current_mode = selected
        elif has_secret:
            current_mode = "secret"
        elif has_certificate:
            current_mode = "certificate"
        else:
            if non_interactive:
                raise AuthenticationError(
                    "No application credentials found. "
                    "Set ANGLERFISH_CLIENT_SECRET or certificate environment variables, "
                    "or use --credential-mode to specify the credential type."
                )
            selected = questionary.select(
                "Choose application credential type:",
                choices=[
                    questionary.Choice("Client secret", value="secret"),
                    questionary.Choice("Certificate", value="certificate"),
                ],
                style=_STYLE,
                qmark=_QMARK,
                pointer=_POINTER,
            ).ask()
            if selected is None:
                return None
            current_mode = selected

    if current_mode == "secret":
        if not has_secret:
            if non_interactive:
                raise AuthenticationError("Credential mode is 'secret' but ANGLERFISH_CLIENT_SECRET is not set.")
            secret = questionary.password(
                "Client secret:", validate=_validate_non_empty, style=_STYLE, qmark=_QMARK
            ).ask()
            if secret is None:
                return None
            os.environ["ANGLERFISH_CLIENT_SECRET"] = secret
            clear_env_vars.append("ANGLERFISH_CLIENT_SECRET")
        os.environ["ANGLERFISH_APP_CREDENTIAL_MODE"] = "secret"
        return AuthPromptResult(credential_mode="secret", clear_env_vars=tuple(clear_env_vars))

    # current_mode == "certificate"
    pfx_path = os.environ.get("ANGLERFISH_CLIENT_CERT_PFX_PATH", "").strip()
    key_path = os.environ.get("ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH", "").strip()
    thumbprint = os.environ.get("ANGLERFISH_CLIENT_CERT_THUMBPRINT", "").strip()

    if not pfx_path and not key_path:
        if non_interactive:
            raise AuthenticationError(
                "Credential mode is 'certificate' but no certificate path is set. "
                "Set ANGLERFISH_CLIENT_CERT_PFX_PATH or ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH."
            )
        cert_kind = questionary.select(
            "Choose certificate input type:",
            choices=[
                questionary.Choice("PFX file", value="pfx"),
                questionary.Choice("PEM private key + thumbprint", value="pem"),
            ],
            style=_STYLE,
            qmark=_QMARK,
            pointer=_POINTER,
        ).ask()
        if cert_kind is None:
            return None

        if cert_kind == "pfx":
            pfx = questionary.text(
                "Path to .pfx certificate file:", validate=_validate_file_path, style=_STYLE, qmark=_QMARK
            ).ask()
            if pfx is None:
                return None
            os.environ["ANGLERFISH_CLIENT_CERT_PFX_PATH"] = pfx.strip()
            pfx_passphrase = questionary.password(
                "PFX passphrase (leave blank if none):", style=_STYLE, qmark=_QMARK
            ).ask()
            if pfx_passphrase is None:
                return None
            os.environ["ANGLERFISH_CLIENT_CERT_PASSPHRASE"] = pfx_passphrase
            clear_env_vars.append("ANGLERFISH_CLIENT_CERT_PASSPHRASE")
        else:
            key = questionary.text(
                "Path to PEM private key file:", validate=_validate_file_path, style=_STYLE, qmark=_QMARK
            ).ask()
            if key is None:
                return None
            os.environ["ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH"] = key.strip()
            cert_thumbprint = questionary.text(
                "Certificate thumbprint (hex, no colons):",
                validate=_validate_non_empty,
                style=_STYLE,
                qmark=_QMARK,
            ).ask()
            if cert_thumbprint is None:
                return None
            os.environ["ANGLERFISH_CLIENT_CERT_THUMBPRINT"] = cert_thumbprint.strip()

            cert_file = questionary.text("Path to PEM public certificate (optional):", style=_STYLE, qmark=_QMARK).ask()
            if cert_file is None:
                return None
            if cert_file.strip():
                os.environ["ANGLERFISH_CLIENT_CERT_PUBLIC_CERT_PATH"] = cert_file.strip()

            key_passphrase = questionary.password(
                "Private key passphrase (leave blank if none):", style=_STYLE, qmark=_QMARK
            ).ask()
            if key_passphrase is None:
                return None
            os.environ["ANGLERFISH_CLIENT_CERT_PASSPHRASE"] = key_passphrase
            clear_env_vars.append("ANGLERFISH_CLIENT_CERT_PASSPHRASE")

    if key_path and not thumbprint:
        if non_interactive:
            raise AuthenticationError("ANGLERFISH_CLIENT_CERT_THUMBPRINT is required when using PEM private key auth.")
        cert_thumbprint = questionary.text(
            "Certificate thumbprint (hex, no colons):",
            validate=_validate_non_empty,
            style=_STYLE,
            qmark=_QMARK,
        ).ask()
        if cert_thumbprint is None:
            return None
        os.environ["ANGLERFISH_CLIENT_CERT_THUMBPRINT"] = cert_thumbprint.strip()

    os.environ["ANGLERFISH_APP_CREDENTIAL_MODE"] = "certificate"
    return AuthPromptResult(credential_mode="certificate", clear_env_vars=tuple(clear_env_vars))


def _render_deploy_template(
    template: OutlookTemplate,
    *,
    canary_type: str,
    console: Console,
    non_interactive: bool,
    cli_var_values: dict[str, str],
) -> OutlookTemplate | None:
    if not template.variables:
        return template

    var_values: dict[str, str] = {}

    for var in template.variables:
        name = str(var.get("name", "")).strip()

        if non_interactive:
            # Use --var overrides first, then fall back to template default.
            default = str(var.get("default", ""))
            value = cli_var_values.get(name, default)
            if not value and not default:
                raise DeploymentError(
                    f"Variable '{name}' is required but not set. Pass --var {name}=<value> in --non-interactive mode."
                )
            var_values[name] = value
        else:
            default = var.get("default", "")
            answer = questionary.text(
                f"{var.get('description', var['name'])}:",
                default=default,
                validate=_validate_non_empty if not default else _validate_variable_value,
                style=_STYLE,
                qmark=_QMARK,
            ).ask()
            if answer is None:
                return None
            var_values[name] = answer.strip()

    return render_template(template, var_values)
