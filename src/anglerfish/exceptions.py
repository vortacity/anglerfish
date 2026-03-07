"""Custom exception hierarchy for Anglerfish."""


class AnglerfishError(Exception):
    """Base exception for all anglerfish errors."""


class AuthenticationError(AnglerfishError):
    """Failed to authenticate."""


class GraphApiError(AnglerfishError):
    """Graph API returned an error response."""

    def __init__(
        self,
        message: str,
        status_code: int = 0,
        *,
        method: str | None = None,
        path: str | None = None,
        request_id: str | None = None,
        client_request_id: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.method = (method or "").strip().upper()
        self.path = (path or "").strip()
        self.request_id = (request_id or "").strip()
        self.client_request_id = (client_request_id or "").strip()


class TemplateError(AnglerfishError):
    """Template loading, parsing, or validation failed."""


class DeploymentError(AnglerfishError):
    """Canary deployment failed."""


class MonitorError(AnglerfishError):
    """Monitor state or runtime error."""


class AuditApiError(AnglerfishError):
    """Management Activity API returned an error response."""

    def __init__(
        self,
        message: str,
        status_code: int = 0,
        *,
        method: str | None = None,
        url: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.method = (method or "").strip().upper()
        self.url = (url or "").strip()
