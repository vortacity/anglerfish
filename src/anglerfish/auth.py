"""Authentication helpers for Microsoft Graph auth flows."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import msal

from .config import GRAPH_APP_SCOPE, MANAGEMENT_API_SCOPE
from .exceptions import AuthenticationError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthConfig:
    """Application credentials passed by value.

    Blank fields fall back to the corresponding ``ANGLERFISH_*`` environment
    variable at resolution time (``resolved_with_env``) — the environment is
    one *input*, never something the auth flow writes to. Prompted secrets
    travel inside this object instead of through ``os.environ``.
    """

    tenant_id: str = ""
    client_id: str = ""
    credential_mode: str = ""
    client_secret: str = ""
    cert_pfx_path: str = ""
    cert_private_key_path: str = ""
    cert_public_cert_path: str = ""
    cert_thumbprint: str = ""
    cert_passphrase: str = ""
    cert_send_x5c: str = ""

    def resolved_with_env(self) -> AuthConfig:
        """Fill blank fields from the environment, read once, here."""

        def env(name: str) -> str:
            return os.environ.get(name, "").strip()

        return AuthConfig(
            tenant_id=self.tenant_id.strip() or env("ANGLERFISH_TENANT_ID"),
            client_id=self.client_id.strip() or env("ANGLERFISH_CLIENT_ID"),
            credential_mode=(self.credential_mode.strip() or env("ANGLERFISH_APP_CREDENTIAL_MODE")).lower(),
            client_secret=self.client_secret or env("ANGLERFISH_CLIENT_SECRET"),
            cert_pfx_path=self.cert_pfx_path.strip() or env("ANGLERFISH_CLIENT_CERT_PFX_PATH"),
            cert_private_key_path=self.cert_private_key_path.strip() or env("ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH"),
            cert_public_cert_path=self.cert_public_cert_path.strip() or env("ANGLERFISH_CLIENT_CERT_PUBLIC_CERT_PATH"),
            cert_thumbprint=self.cert_thumbprint.strip() or env("ANGLERFISH_CLIENT_CERT_THUMBPRINT"),
            cert_passphrase=self.cert_passphrase or os.environ.get("ANGLERFISH_CLIENT_CERT_PASSPHRASE", ""),
            cert_send_x5c=self.cert_send_x5c.strip() or env("ANGLERFISH_CLIENT_CERT_SEND_X5C"),
        )


def authenticate(
    auth_mode: str | None = None,
    app_credential_mode: str | None = None,
    *,
    auth_config: AuthConfig | None = None,
) -> str:
    """Authenticate using the configured auth mode and return an access token."""
    normalized_mode = _resolve_auth_mode(auth_mode)
    logger.debug("Authenticating: mode=%s", normalized_mode)
    if normalized_mode != "application":
        raise AuthenticationError("Only application auth is supported in this release.")
    return _acquire_app_token(scope=GRAPH_APP_SCOPE, app_credential_mode=app_credential_mode, auth_config=auth_config)


def _resolve_auth_mode(auth_mode: str | None) -> str:
    selected = auth_mode if auth_mode is not None else os.environ.get("ANGLERFISH_AUTH_MODE", "application")
    normalized = selected.strip().lower()
    if normalized in {"", "application"}:
        return "application"
    return normalized


def authenticate_management_api(
    app_credential_mode: str | None = None, *, auth_config: AuthConfig | None = None
) -> str:
    """Authenticate for the Office 365 Management Activity API (app-only).

    Uses the same MSAL client credentials flow and credential resolution as
    ``_authenticate_application`` but requests a token scoped to
    ``https://manage.office.com/.default`` instead of Graph.

    Raises ``AuthenticationError`` if non-application mode is attempted.
    """
    auth_mode = _resolve_auth_mode(None)
    if auth_mode != "application":
        raise AuthenticationError("Only application auth is supported in this release.")
    return _acquire_app_token(
        scope=MANAGEMENT_API_SCOPE, app_credential_mode=app_credential_mode, auth_config=auth_config
    )


def authenticate_management_api_with_expiry(
    app_credential_mode: str | None = None, *, auth_config: AuthConfig | None = None
) -> tuple[str, int]:
    """Like ``authenticate_management_api`` but also returns the token lifetime.

    Returns ``(access_token, expires_in_seconds)``. The lifetime comes from the
    MSAL response so callers can refresh on the tenant's actual token policy
    rather than an assumed one; it defaults to 3600 when the response omits it.
    """
    auth_mode = _resolve_auth_mode(None)
    if auth_mode != "application":
        raise AuthenticationError("Only application auth is supported in this release.")
    return _acquire_app_token_with_expiry(
        scope=MANAGEMENT_API_SCOPE, app_credential_mode=app_credential_mode, auth_config=auth_config
    )


def _acquire_app_token(
    *, scope: str, app_credential_mode: str | None = None, auth_config: AuthConfig | None = None
) -> str:
    token, _expires_in = _acquire_app_token_with_expiry(
        scope=scope, app_credential_mode=app_credential_mode, auth_config=auth_config
    )
    return token


def _acquire_app_token_with_expiry(
    *, scope: str, app_credential_mode: str | None = None, auth_config: AuthConfig | None = None
) -> tuple[str, int]:
    """Shared logic for acquiring an app-only token for a given scope."""
    config = (auth_config or AuthConfig()).resolved_with_env()
    client_id = config.client_id
    tenant_id = config.tenant_id
    client_secret = config.client_secret
    cert_pfx_path = config.cert_pfx_path
    cert_private_key_path = config.cert_private_key_path
    cert_public_cert_path = config.cert_public_cert_path
    cert_thumbprint = config.cert_thumbprint
    cert_passphrase = config.cert_passphrase
    cert_send_x5c = config.cert_send_x5c
    configured_app_credential_mode = config.credential_mode or "auto"

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
        details: str = "Unknown error"
        if isinstance(result, dict):
            raw = result.get("error_description", result.get("error", details))
            details = str(raw) if raw is not None else details
        raise AuthenticationError(f"Application authentication failed: {details}")

    try:
        expires_in = int(result.get("expires_in", 3600))
    except (TypeError, ValueError):
        expires_in = 3600
    return str(result["access_token"]), expires_in


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
