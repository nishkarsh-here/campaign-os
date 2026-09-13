"""The authentication boundary.

`AuthProvider` answers exactly one question: *who is making this request?* It
returns an identity, never a `Principal` — because a Principal also carries an
organization, and which organization a request targets is a routing concern,
not an identity-provider concern. Keeping those separate is what lets the dev
stub be swapped for Supabase Auth (or anything else) without touching
membership logic (CLAUDE.md, ADR-002).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class AuthenticatedUser:
    """An identity as asserted by the identity provider.

    `subject` is the provider's stable id for the user, and is what we store on
    `users.auth_subject`. It is deliberately not our own user id: the provider
    does not know about our database.
    """

    subject: str
    email: str
    display_name: str | None = None


class AuthenticationError(Exception):
    """Raised when a caller cannot be identified. Becomes a 401."""


@runtime_checkable
class AuthProvider(Protocol):
    name: str

    async def authenticate(self, credentials: str | None) -> AuthenticatedUser:
        """Resolve the bearer credential to an identity.

        Raises `AuthenticationError` if the credential is missing or invalid.
        Implementations must not touch the database — identity resolution and
        user provisioning are separate responsibilities.
        """
        ...
