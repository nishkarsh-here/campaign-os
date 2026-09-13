"""Application error hierarchy.

One shape for every failure the API can return (API_SPEC §Conventions). Routes
raise these; a single handler renders them. Messages here are **user-safe** —
anything sensitive goes in `detail`, which is logged and never serialized.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base for every expected failure."""

    code: str = "INTERNAL"
    http_status: int = 500

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        #: Log-side only. Never reaches the client.
        self.detail = detail


class ValidationFailed(AppError):
    code = "VALIDATION_FAILED"
    http_status = 400


class Unauthenticated(AppError):
    code = "UNAUTHENTICATED"
    http_status = 401


class Forbidden(AppError):
    code = "FORBIDDEN"
    http_status = 403


class NotFound(AppError):
    """Also returned for a resource in another organization.

    Cross-tenant reads must not be distinguishable from non-existent ones, so
    the API never answers 403 for "exists, but not yours" (API_SPEC §Scope).
    """

    code = "NOT_FOUND"
    http_status = 404


class Conflict(AppError):
    code = "CONFLICT"
    http_status = 409
