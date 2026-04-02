from __future__ import annotations

from pathlib import Path

import pytest

from anglerfish import auth
from anglerfish.exceptions import AuthenticationError


@pytest.fixture(autouse=True)
def clear_anglerfish_env(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "ANGLERFISH_CLIENT_ID",
        "ANGLERFISH_TENANT_ID",
        "ANGLERFISH_AUTH_MODE",
        "ANGLERFISH_CLIENT_SECRET",
        "ANGLERFISH_APP_CREDENTIAL_MODE",
        "ANGLERFISH_GRAPH_DELEGATED_SCOPES",
        "ANGLERFISH_CLIENT_CERT_PFX_PATH",
        "ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH",
        "ANGLERFISH_CLIENT_CERT_PUBLIC_CERT_PATH",
        "ANGLERFISH_CLIENT_CERT_THUMBPRINT",
        "ANGLERFISH_CLIENT_CERT_PASSPHRASE",
        "ANGLERFISH_CLIENT_CERT_SEND_X5C",
    ):
        monkeypatch.delenv(name, raising=False)


class FakeConfidentialAppSuccess:
    last_client_credential = None

    def __init__(self, client_id, authority, client_credential):
        self.client_id = client_id
        self.authority = authority
        self.client_credential = client_credential
        FakeConfidentialAppSuccess.last_client_credential = client_credential

    def acquire_token_for_client(self, scopes):
        return {"access_token": "app-token-123"}


class FakeConfidentialAppError(FakeConfidentialAppSuccess):
    def acquire_token_for_client(self, scopes):
        return {"error": "invalid_client", "error_description": "client secret invalid"}


def test_authenticate_application_requires_client_id(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth, "CLIENT_ID", "")
    monkeypatch.setattr(auth, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth, "CLIENT_SECRET", "secret")

    with pytest.raises(AuthenticationError, match="ANGLERFISH_CLIENT_ID"):
        auth.authenticate()


def test_authenticate_application_requires_tenant_id(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "TENANT_ID", "")
    monkeypatch.setattr(auth, "CLIENT_SECRET", "secret")

    with pytest.raises(AuthenticationError, match="ANGLERFISH_TENANT_ID"):
        auth.authenticate()


def test_authenticate_application_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "application")
    monkeypatch.setattr(auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth, "CLIENT_SECRET", "secret")
    monkeypatch.setattr(auth, "CLIENT_CERT_PFX_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PRIVATE_KEY_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PUBLIC_CERT_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_THUMBPRINT", "")
    monkeypatch.setattr(auth, "APP_CREDENTIAL_MODE", "auto")
    monkeypatch.setattr(auth.msal, "ConfidentialClientApplication", FakeConfidentialAppSuccess)

    token = auth.authenticate()

    assert token == "app-token-123"


def test_authenticate_application_missing_secret_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "application")
    monkeypatch.setattr(auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth, "CLIENT_SECRET", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PFX_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PRIVATE_KEY_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PUBLIC_CERT_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_THUMBPRINT", "")
    monkeypatch.setattr(auth, "APP_CREDENTIAL_MODE", "secret")

    with pytest.raises(AuthenticationError, match="ANGLERFISH_APP_CREDENTIAL_MODE"):
        auth.authenticate()


def test_authenticate_application_error_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "application")
    monkeypatch.setattr(auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth, "CLIENT_SECRET", "secret")
    monkeypatch.setattr(auth, "CLIENT_CERT_PFX_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PRIVATE_KEY_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PUBLIC_CERT_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_THUMBPRINT", "")
    monkeypatch.setattr(auth, "APP_CREDENTIAL_MODE", "auto")
    monkeypatch.setattr(auth.msal, "ConfidentialClientApplication", FakeConfidentialAppError)

    with pytest.raises(AuthenticationError, match="Application authentication failed"):
        auth.authenticate()


def test_authenticate_invalid_mode_raises():
    with pytest.raises(AuthenticationError, match="application auth"):
        auth.authenticate(auth_mode="bad-mode")


def test_authenticate_rejects_delegated_after_reset():
    with pytest.raises(AuthenticationError, match="application auth"):
        auth.authenticate(auth_mode="delegated")


def test_authenticate_management_api_requests_management_scope(monkeypatch: pytest.MonkeyPatch):
    called: dict[str, str | None] = {}

    def fake_acquire_app_token(*, scope: str, app_credential_mode: str | None = None) -> str:
        called["scope"] = scope
        called["mode"] = app_credential_mode
        return "management-token-123"

    monkeypatch.setattr(auth, "MANAGEMENT_API_SCOPE", "https://manage.office.com/.default")
    monkeypatch.setattr(auth, "GRAPH_APP_SCOPE", "https://graph.microsoft.com/.default")
    monkeypatch.setattr(auth, "_acquire_app_token", fake_acquire_app_token)

    token = auth.authenticate_management_api(app_credential_mode="certificate")

    assert token == "management-token-123"
    assert called["scope"] == "https://manage.office.com/.default"
    assert called["scope"] != auth.GRAPH_APP_SCOPE
    assert called["mode"] == "certificate"


def test_authenticate_management_api_rejects_non_application_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANGLERFISH_AUTH_MODE", "delegated")
    with pytest.raises(AuthenticationError, match="application auth"):
        auth.authenticate_management_api()


def test_authenticate_application_with_pfx_certificate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    pfx_file = tmp_path / "client-cert.pfx"
    pfx_file.write_bytes(b"fake-pfx-content")

    monkeypatch.setattr(auth, "AUTH_MODE", "application")
    monkeypatch.setattr(auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth, "CLIENT_SECRET", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PFX_PATH", str(pfx_file))
    monkeypatch.setattr(auth, "CLIENT_CERT_PRIVATE_KEY_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PUBLIC_CERT_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_THUMBPRINT", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PASSPHRASE", "passphrase")
    monkeypatch.setattr(auth, "CLIENT_CERT_SEND_X5C", "true")
    monkeypatch.setattr(auth, "APP_CREDENTIAL_MODE", "certificate")
    monkeypatch.setattr(auth.msal, "ConfidentialClientApplication", FakeConfidentialAppSuccess)

    token = auth.authenticate()

    assert token == "app-token-123"
    assert FakeConfidentialAppSuccess.last_client_credential == {
        "private_key_pfx_path": str(pfx_file),
        "passphrase": "passphrase",
        "public_certificate": True,
    }


def test_authenticate_application_with_pem_certificate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    key_file = tmp_path / "client.key"
    cert_file = tmp_path / "client.crt"
    key_file.write_text("-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----\\n", encoding="utf-8")
    cert_file.write_text("-----BEGIN CERTIFICATE-----\\nxyz\\n-----END CERTIFICATE-----\\n", encoding="utf-8")

    monkeypatch.setattr(auth, "AUTH_MODE", "application")
    monkeypatch.setattr(auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth, "CLIENT_SECRET", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PFX_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PRIVATE_KEY_PATH", str(key_file))
    monkeypatch.setattr(auth, "CLIENT_CERT_PUBLIC_CERT_PATH", str(cert_file))
    monkeypatch.setattr(auth, "CLIENT_CERT_THUMBPRINT", "ABCDEF123456")
    monkeypatch.setattr(auth, "CLIENT_CERT_PASSPHRASE", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_SEND_X5C", "false")
    monkeypatch.setattr(auth, "APP_CREDENTIAL_MODE", "certificate")
    monkeypatch.setattr(auth.msal, "ConfidentialClientApplication", FakeConfidentialAppSuccess)

    token = auth.authenticate()

    assert token == "app-token-123"
    credential = FakeConfidentialAppSuccess.last_client_credential
    assert credential["thumbprint"] == "ABCDEF123456"
    assert "PRIVATE KEY" in credential["private_key"]
    assert "CERTIFICATE" in credential["public_certificate"]


def test_authenticate_application_auto_mode_rejects_ambiguous_credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "application")
    monkeypatch.setattr(auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth, "CLIENT_SECRET", "secret")
    monkeypatch.setattr(auth, "CLIENT_CERT_PFX_PATH", "/tmp/example.pfx")
    monkeypatch.setattr(auth, "CLIENT_CERT_PRIVATE_KEY_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PUBLIC_CERT_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_THUMBPRINT", "")
    monkeypatch.setattr(auth, "APP_CREDENTIAL_MODE", "auto")

    with pytest.raises(AuthenticationError, match="Both secret and certificate credentials are configured"):
        auth.authenticate()


# --- New auth coverage tests ---


def test_authenticate_application_auto_mode_no_credentials_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "application")
    monkeypatch.setattr(auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth, "CLIENT_SECRET", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PFX_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PRIVATE_KEY_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PUBLIC_CERT_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_THUMBPRINT", "")
    monkeypatch.setattr(auth, "APP_CREDENTIAL_MODE", "auto")

    with pytest.raises(AuthenticationError, match="No application credential configured"):
        auth.authenticate()


def test_authenticate_application_auto_mode_uses_certificate_when_only_cert_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    pfx_file = tmp_path / "cert.pfx"
    pfx_file.write_bytes(b"fake")

    monkeypatch.setattr(auth, "AUTH_MODE", "application")
    monkeypatch.setattr(auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth, "CLIENT_SECRET", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PFX_PATH", str(pfx_file))
    monkeypatch.setattr(auth, "CLIENT_CERT_PRIVATE_KEY_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PUBLIC_CERT_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_THUMBPRINT", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PASSPHRASE", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_SEND_X5C", "")
    monkeypatch.setattr(auth, "APP_CREDENTIAL_MODE", "auto")
    monkeypatch.setattr(auth.msal, "ConfidentialClientApplication", FakeConfidentialAppSuccess)

    token = auth.authenticate()

    assert token == "app-token-123"
    cred = FakeConfidentialAppSuccess.last_client_credential
    assert "private_key_pfx_path" in cred


def test_authenticate_application_cert_missing_private_key_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "application")
    monkeypatch.setattr(auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth, "CLIENT_SECRET", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PFX_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PRIVATE_KEY_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PUBLIC_CERT_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_THUMBPRINT", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PASSPHRASE", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_SEND_X5C", "")
    monkeypatch.setattr(auth, "APP_CREDENTIAL_MODE", "certificate")

    with pytest.raises(AuthenticationError, match="ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH"):
        auth.authenticate()


def test_authenticate_application_cert_missing_thumbprint_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    key_file = tmp_path / "key.pem"
    key_file.write_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n", encoding="utf-8")

    monkeypatch.setattr(auth, "AUTH_MODE", "application")
    monkeypatch.setattr(auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth, "CLIENT_SECRET", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PFX_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PRIVATE_KEY_PATH", str(key_file))
    monkeypatch.setattr(auth, "CLIENT_CERT_PUBLIC_CERT_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_THUMBPRINT", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PASSPHRASE", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_SEND_X5C", "")
    monkeypatch.setattr(auth, "APP_CREDENTIAL_MODE", "certificate")

    with pytest.raises(AuthenticationError, match="ANGLERFISH_CLIENT_CERT_THUMBPRINT"):
        auth.authenticate()


def test_authenticate_application_pem_with_passphrase(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    key_file = tmp_path / "key.pem"
    key_file.write_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n", encoding="utf-8")

    monkeypatch.setattr(auth, "AUTH_MODE", "application")
    monkeypatch.setattr(auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth, "CLIENT_SECRET", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PFX_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PRIVATE_KEY_PATH", str(key_file))
    monkeypatch.setattr(auth, "CLIENT_CERT_PUBLIC_CERT_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_THUMBPRINT", "ABCDEF")
    monkeypatch.setattr(auth, "CLIENT_CERT_PASSPHRASE", "mypassphrase")
    monkeypatch.setattr(auth, "CLIENT_CERT_SEND_X5C", "false")
    monkeypatch.setattr(auth, "APP_CREDENTIAL_MODE", "certificate")
    monkeypatch.setattr(auth.msal, "ConfidentialClientApplication", FakeConfidentialAppSuccess)

    token = auth.authenticate()

    assert token == "app-token-123"
    cred = FakeConfidentialAppSuccess.last_client_credential
    assert cred["passphrase"] == "mypassphrase"
    assert cred["thumbprint"] == "ABCDEF"


def test_authenticate_application_pem_send_x5c_without_public_cert_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    key_file = tmp_path / "key.pem"
    key_file.write_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n", encoding="utf-8")

    monkeypatch.setattr(auth, "AUTH_MODE", "application")
    monkeypatch.setattr(auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth, "CLIENT_SECRET", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PFX_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PRIVATE_KEY_PATH", str(key_file))
    monkeypatch.setattr(auth, "CLIENT_CERT_PUBLIC_CERT_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_THUMBPRINT", "ABCDEF")
    monkeypatch.setattr(auth, "CLIENT_CERT_PASSPHRASE", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_SEND_X5C", "true")
    monkeypatch.setattr(auth, "APP_CREDENTIAL_MODE", "certificate")

    with pytest.raises(AuthenticationError, match="ANGLERFISH_CLIENT_CERT_SEND_X5C"):
        auth.authenticate()


def test_authenticate_application_pfx_file_not_found_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "application")
    monkeypatch.setattr(auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth, "CLIENT_SECRET", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PFX_PATH", "/nonexistent/path/cert.pfx")
    monkeypatch.setattr(auth, "CLIENT_CERT_PRIVATE_KEY_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PUBLIC_CERT_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_THUMBPRINT", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PASSPHRASE", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_SEND_X5C", "")
    monkeypatch.setattr(auth, "APP_CREDENTIAL_MODE", "certificate")

    with pytest.raises(AuthenticationError, match="ANGLERFISH_CLIENT_CERT_PFX_PATH"):
        auth.authenticate()


def test_authenticate_application_pem_key_file_not_found_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "application")
    monkeypatch.setattr(auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth, "CLIENT_SECRET", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PFX_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PRIVATE_KEY_PATH", "/nonexistent/key.pem")
    monkeypatch.setattr(auth, "CLIENT_CERT_PUBLIC_CERT_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_THUMBPRINT", "ABC123")
    monkeypatch.setattr(auth, "CLIENT_CERT_PASSPHRASE", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_SEND_X5C", "")
    monkeypatch.setattr(auth, "APP_CREDENTIAL_MODE", "certificate")

    with pytest.raises(AuthenticationError, match="ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH"):
        auth.authenticate()


def test_resolve_auth_mode_empty_string_maps_to_application(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANGLERFISH_AUTH_MODE", "")
    monkeypatch.setattr(auth, "AUTH_MODE", "")
    monkeypatch.setattr(auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(auth, "TENANT_ID", "tenant-id")
    monkeypatch.setattr(auth, "CLIENT_SECRET", "secret")
    monkeypatch.setattr(auth, "CLIENT_CERT_PFX_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PRIVATE_KEY_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_PUBLIC_CERT_PATH", "")
    monkeypatch.setattr(auth, "CLIENT_CERT_THUMBPRINT", "")
    monkeypatch.setattr(auth, "APP_CREDENTIAL_MODE", "auto")
    monkeypatch.setattr(auth.msal, "ConfidentialClientApplication", FakeConfidentialAppSuccess)

    token = auth.authenticate()

    assert token == "app-token-123"
