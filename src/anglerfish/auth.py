"""Authentication helpers for Microsoft Graph auth flows."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Sequence

import msal
from rich.console import Console

from .config import (
    APP_CREDENTIAL_MODE,
    AUTH_MODE,
    CLIENT_CERT_PASSPHRASE,
    CLIENT_CERT_PFX_PATH,
    CLIENT_CERT_PRIVATE_KEY_PATH,
    CLIENT_CERT_PUBLIC_CERT_PATH,
    CLIENT_CERT_SEND_X5C,
    CLIENT_CERT_THUMBPRINT,
    CLIENT_ID,
    CLIENT_SECRET,
    GRAPH_APP_SCOPE,
    GRAPH_DELEGATED_SCOPES,
    MANAGEMENT_API_SCOPE,
    TENANT_ID,
)
from .exceptions import AuthenticationError

logger = logging.getLogger(__name__)
console = Console(stderr=True)

_DEFAULT_DELEGATED_SCOPES = (
    "User.Read",
    "Team.ReadBasic.All",
    "Channel.ReadBasic.All",
    "ChannelMessage.Send",
    "ChannelMessage.Read.All",
    "Chat.Create",
    "Chat.ReadWrite",
    "ChatMessage.Send",
)
_RESERVED_DELEGATED_SCOPES = frozenset({"offline_access", "openid", "profile"})


def authenticate(
    auth_mode: str | None = None,
    app_credential_mode: str | None = None,
    delegated_scopes: Sequence[str] | None = None,
) -> str:
    """Authenticate using the configured auth mode and return an access token."""
    normalized_mode = _resolve_auth_mode(auth_mode)
    logger.debug("Authenticating: mode=%s", normalized_mode)
    if normalized_mode == "application":
        return _authenticate_application(app_credential_mode=app_credential_mode)
    if normalized_mode == "delegated":
        return _authenticate_delegated(delegated_scopes=delegated_scopes)
    raise AuthenticationError(
        f"Invalid auth mode '{normalized_mode}'. Supported values are 'application' and 'delegated'."
    )


def _resolve_auth_mode(auth_mode: str | None) -> str:
    selected = auth_mode if auth_mode is not None else _get_str_env("ANGLERFISH_AUTH_MODE", AUTH_MODE)
    normalized = selected.strip().lower()
    if normalized in {"application", "delegated"}:
        return normalized
    if normalized == "":
        return "application"
    raise AuthenticationError(f"Invalid auth mode '{selected}'. Supported values are 'application' and 'delegated'.")


def _authenticate_delegated(delegated_scopes: Sequence[str] | None = None) -> str:
    """Authenticate via delegated device code flow and return a user access token."""
    client_id = _get_str_env("ANGLERFISH_CLIENT_ID", CLIENT_ID)
    tenant_id = _get_str_env("ANGLERFISH_TENANT_ID", TENANT_ID)
    if not client_id:
        raise AuthenticationError("ANGLERFISH_CLIENT_ID environment variable is required for delegated auth mode.")
    if not tenant_id:
        raise AuthenticationError("ANGLERFISH_TENANT_ID environment variable is required for delegated auth mode.")

    scopes = _resolve_delegated_scopes(delegated_scopes)
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.PublicClientApplication(
        client_id=client_id,
        authority=authority,
    )
    flow = app.initiate_device_flow(scopes=scopes)
    if not isinstance(flow, dict) or "user_code" not in flow:
        raise AuthenticationError("Failed to start delegated device code flow.")

    message = str(flow.get("message", "")).strip()
    if message:
        console.print(message)

    result = app.acquire_token_by_device_flow(flow)
    if not isinstance(result, dict) or "access_token" not in result:
        details = "Unknown error"
        if isinstance(result, dict):
            details = result.get("error_description", result.get("error", details))
        raise AuthenticationError(f"Delegated authentication failed: {details}")

    return str(result["access_token"])


def _resolve_delegated_scopes(delegated_scopes: Sequence[str] | None = None) -> list[str]:
    if delegated_scopes:
        scopes = _sanitize_delegated_scopes(delegated_scopes)
        if scopes:
            return scopes
        raise AuthenticationError(
            "Delegated scopes must include at least one Microsoft Graph permission "
            "(reserved scopes like openid/profile/offline_access are not allowed)."
        )

    configured_scopes = _get_str_env("ANGLERFISH_GRAPH_DELEGATED_SCOPES", GRAPH_DELEGATED_SCOPES)
    if configured_scopes:
        scopes = _sanitize_delegated_scopes(configured_scopes.split(","))
        if scopes:
            return scopes
        raise AuthenticationError(
            "ANGLERFISH_GRAPH_DELEGATED_SCOPES must include at least one Microsoft Graph permission "
            "(reserved scopes like openid/profile/offline_access are not allowed)."
        )

    return _sanitize_delegated_scopes(_DEFAULT_DELEGATED_SCOPES)


def _sanitize_delegated_scopes(raw_scopes: Sequence[str]) -> list[str]:
    scopes: list[str] = []
    seen: set[str] = set()
    for raw_scope in raw_scopes:
        scope = raw_scope.strip()
        if not scope:
            continue
        normalized = scope.casefold()
        if normalized in _RESERVED_DELEGATED_SCOPES or normalized in seen:
            continue
        seen.add(normalized)
        scopes.append(scope)
    return scopes


def authenticate_management_api(app_credential_mode: str | None = None) -> str:
    """Authenticate for the Office 365 Management Activity API (app-only).

    Uses the same MSAL client credentials flow and credential resolution as
    ``_authenticate_application`` but requests a token scoped to
    ``https://manage.office.com/.default`` instead of Graph.

    Raises ``AuthenticationError`` if delegated mode is attempted (the
    Management Activity API requires application-level permissions).
    """
    auth_mode = _resolve_auth_mode(None)
    if auth_mode == "delegated":
        raise AuthenticationError(
            "The Management Activity API requires application (client credentials) auth. "
            "Delegated auth mode is not supported for monitoring."
        )
    return _acquire_app_token(scope=MANAGEMENT_API_SCOPE, app_credential_mode=app_credential_mode)


def _acquire_app_token(*, scope: str, app_credential_mode: str | None = None) -> str:
    """Shared logic for acquiring an app-only token for a given scope."""
    client_id = _get_str_env("ANGLERFISH_CLIENT_ID", CLIENT_ID)
    tenant_id = _get_str_env("ANGLERFISH_TENANT_ID", TENANT_ID)
    client_secret = _get_str_env("ANGLERFISH_CLIENT_SECRET", CLIENT_SECRET)
    cert_pfx_path = _get_str_env("ANGLERFISH_CLIENT_CERT_PFX_PATH", CLIENT_CERT_PFX_PATH)
    cert_private_key_path = _get_str_env("ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH", CLIENT_CERT_PRIVATE_KEY_PATH)
    cert_public_cert_path = _get_str_env("ANGLERFISH_CLIENT_CERT_PUBLIC_CERT_PATH", CLIENT_CERT_PUBLIC_CERT_PATH)
    cert_thumbprint = _get_str_env("ANGLERFISH_CLIENT_CERT_THUMBPRINT", CLIENT_CERT_THUMBPRINT)
    cert_passphrase = os.environ.get("ANGLERFISH_CLIENT_CERT_PASSPHRASE", CLIENT_CERT_PASSPHRASE)
    cert_send_x5c = _get_str_env("ANGLERFISH_CLIENT_CERT_SEND_X5C", CLIENT_CERT_SEND_X5C)
    configured_app_credential_mode = _get_str_env("ANGLERFISH_APP_CREDENTIAL_MODE", APP_CREDENTIAL_MODE)

    if not client_id:
        raise AuthenticationError("ANGLERFISH_CLIENT_ID environment variable is required for application auth mode.")
    if not tenant_id:
        raise AuthenticationError("ANGLERFISH_TENANT_ID environment variable is required for application auth mode.")

    raw_mode = app_credential_mode if app_credential_mode is not None else configured_app_credential_mode
    credential_mode = raw_mode.strip().lower()
    if credential_mode not in ("auto", "secret", "certificate"):
        credential_mode = "auto"
    has_secret = bool(client_secret)
    has_certificate_config = bool(cert_pfx_path or cert_private_key_path or cert_public_cert_path or cert_thumbprint)

    if credential_mode == "secret":
        if not has_secret:
            raise AuthenticationError(
                "ANGLERFISH_APP_CREDENTIAL_MODE is 'secret' but ANGLERFISH_CLIENT_SECRET is not set."
            )
        client_credential: str | dict[str, str | bool] = client_secret
    elif credential_mode == "certificate":
        client_credential = _build_certificate_credential(
            cert_pfx_path=cert_pfx_path,
            cert_private_key_path=cert_private_key_path,
            cert_public_cert_path=cert_public_cert_path,
            cert_thumbprint=cert_thumbprint,
            cert_passphrase=cert_passphrase,
            cert_send_x5c=cert_send_x5c,
        )
    else:
        if has_secret and has_certificate_config:
            raise AuthenticationError(
                "Both secret and certificate credentials are configured. "
                "Set one credential type or set ANGLERFISH_APP_CREDENTIAL_MODE to 'secret' or 'certificate'."
            )
        if has_secret:
            client_credential = client_secret
        elif has_certificate_config:
            client_credential = _build_certificate_credential(
                cert_pfx_path=cert_pfx_path,
                cert_private_key_path=cert_private_key_path,
                cert_public_cert_path=cert_public_cert_path,
                cert_thumbprint=cert_thumbprint,
                cert_passphrase=cert_passphrase,
                cert_send_x5c=cert_send_x5c,
            )
        else:
            raise AuthenticationError(
                "No application credential configured. "
                "Set ANGLERFISH_CLIENT_SECRET or certificate variables. See README.md."
            )

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        authority=authority,
        client_credential=client_credential,
    )

    result = app.acquire_token_for_client(scopes=[scope])
    if not isinstance(result, dict) or "access_token" not in result:
        details = "Unknown error"
        if isinstance(result, dict):
            details = result.get("error_description", result.get("error", details))
        raise AuthenticationError(f"Application authentication failed: {details}")

    return str(result["access_token"])


def _authenticate_application(app_credential_mode: str | None = None) -> str:
    """Authenticate via client credentials flow and return an app access token."""
    return _acquire_app_token(scope=GRAPH_APP_SCOPE, app_credential_mode=app_credential_mode)


def _build_certificate_credential(
    *,
    cert_pfx_path: str,
    cert_private_key_path: str,
    cert_public_cert_path: str,
    cert_thumbprint: str,
    cert_passphrase: str,
    cert_send_x5c: str,
) -> dict[str, str | bool]:
    """Build MSAL client_credential dictionary for certificate auth."""
    send_x5c = _parse_bool(cert_send_x5c)
    passphrase = cert_passphrase if cert_passphrase else None

    if cert_pfx_path:
        pfx_path = Path(cert_pfx_path)
        if not pfx_path.is_file():
            raise AuthenticationError(
                f"ANGLERFISH_CLIENT_CERT_PFX_PATH does not exist or is not a file: {cert_pfx_path}"
            )

        credential: dict[str, str | bool] = {"private_key_pfx_path": str(pfx_path)}
        if passphrase:
            credential["passphrase"] = passphrase
        if send_x5c:
            credential["public_certificate"] = True
        return credential

    if not cert_private_key_path:
        raise AuthenticationError(
            "Certificate auth requires ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH (or ANGLERFISH_CLIENT_CERT_PFX_PATH)."
        )
    if not cert_thumbprint:
        raise AuthenticationError(
            "Certificate auth requires ANGLERFISH_CLIENT_CERT_THUMBPRINT when using PEM private key."
        )

    private_key = _read_text_file(
        cert_private_key_path,
        "ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH",
    )

    credential = {
        "private_key": private_key,
        "thumbprint": cert_thumbprint,
    }

    if passphrase:
        credential["passphrase"] = passphrase

    if cert_public_cert_path:
        public_cert = _read_text_file(
            cert_public_cert_path,
            "ANGLERFISH_CLIENT_CERT_PUBLIC_CERT_PATH",
        )
        credential["public_certificate"] = public_cert
    elif send_x5c:
        raise AuthenticationError(
            "ANGLERFISH_CLIENT_CERT_SEND_X5C is true but no public cert is configured. "
            "Set ANGLERFISH_CLIENT_CERT_PUBLIC_CERT_PATH (PEM certificate content)."
        )

    return credential


def _read_text_file(path_value: str, variable_name: str) -> str:
    path = Path(path_value)
    if not path.is_file():
        raise AuthenticationError(f"{variable_name} does not exist or is not a file: {path_value}")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AuthenticationError(f"Failed to read {variable_name} at {path_value}: {exc}") from exc


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_str_env(name: str, fallback: str) -> str:
    return os.environ.get(name, fallback).strip()
