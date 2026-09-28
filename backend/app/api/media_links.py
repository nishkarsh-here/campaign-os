"""Short-lived signed links for the bytes an `<img>` has to fetch.

## The problem this exists to solve

Every byte-serving route in this API resolves a **scope-checked row** and reads
*its* storage key — no route has ever taken a key from a request, and that does
not change here (M10). Authorization is carried by two request headers:
`Authorization: Bearer …` says who, and `X-Organization-Id` says which
organization the request acts in.

A browser cannot put either header on `<img src>`, `<video src>` or a plain
download link. So every image in the product was unreachable from the page that
renders it:

* with `AUTH_PROVIDER=dev_stub` the credential is ignored, so a caller with one
  membership worked by accident and a caller with several got a 403 telling
  them to send a header their browser cannot send;
* with `AUTH_PROVIDER=supabase` **nothing** would load for anyone, because the
  bearer token is missing too.

The visible bug was "multi-organization users cannot see their plates". The
actual defect is that media authorization had no transport a browser could use.

## What a link is

A capability to read **one named row**, for a short time, minted by a request
that was already fully authorized to read it:

```
/v1/campaigns/{campaign}/assets/{asset}/content?token=<payload>.<signature>
```

The payload names the resource kind, the row id, the organization, the user it
was minted for, and an expiry. It is signed with HMAC-SHA256 over a server-side
secret. It is signed, not encrypted: there is nothing secret in it, and a
reader learning that an asset id exists learns nothing they did not already
have when they were handed the link.

## What a link is not

**It is not a storage key.** The token carries a *row id*. The byte route still
loads the row through the organization-scoped repository and reads the key from
it, so `?token=…` can no more address another tenant's object than the header
path could. There is nothing to traverse: no path, no key, no filename.

**It is not a session.** It is bound to one `kind` *and* one row id, so a link
for one plate cannot fetch another plate, and a link for a brand asset cannot
be replayed against the composition route. It cannot create, update or delete
anything, and it cannot read JSON.

**It is not a standing grant.** Membership is re-checked on every use, so
removing someone from an organization revokes their outstanding links
immediately rather than at expiry. Expiry is the second bound, not the only
one.

## Why not an organization id in the query string

That was the obvious small fix and it is the wrong one. It addresses the header
that happened to fail first and leaves the other — authentication — broken, so
it would look correct under the dev stub and 401 for every user the day a real
identity provider is switched on. An unsigned organization id in a URL is also
a bearer capability with no expiry and no binding to a person.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from enum import StrEnum

from app.config import Settings
from app.domain.workspace import Principal

#: Bumped if the payload's shape changes. An old token then fails to verify
#: rather than being read under new rules.
_VERSION = 1


class MediaKind(StrEnum):
    """Which family of row a link may read.

    Short values because they travel in a URL. The route asserts its own kind,
    so these names are part of the security boundary: renaming one invalidates
    every outstanding link for it, which is the correct outcome.
    """

    REFERENCE = "ref"
    GENERATED_ASSET = "gen"
    BRAND_ASSET = "brand"
    FINAL_ASSET = "final"


class InvalidMediaToken(Exception):
    """The token is absent, malformed, forged, expired or for something else.

    Deliberately one exception for all of those. The caller turns it into the
    same "not found" a wrong row id produces, because telling someone whether
    their token was *expired* or *forged* tells them something about the secret.
    """


# ---------------------------------------------------------------------- secret

#: Used when no secret is configured. Generated once per process, so an offline
#: demo and the test suite need no configuration at all — and so there is no
#: shipped default value that would be the same on every install, which is the
#: usual way a signing secret becomes public. The cost is that links do not
#: survive a restart or span two instances, which is why production must set
#: one explicitly; `Settings` refuses to start without it there.
_EPHEMERAL_SECRET: str | None = None


def _secret(settings: Settings) -> bytes:
    global _EPHEMERAL_SECRET
    if settings.media_url_secret:
        return settings.media_url_secret.encode()
    if _EPHEMERAL_SECRET is None:
        _EPHEMERAL_SECRET = secrets.token_urlsafe(32)
    return _EPHEMERAL_SECRET.encode()


# ----------------------------------------------------------------- mint/verify


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def mint(
    *,
    kind: MediaKind,
    row_id: uuid.UUID | str,
    organization_id: uuid.UUID | str,
    user_id: uuid.UUID | str,
    settings: Settings,
    now: float | None = None,
) -> str:
    payload = {
        "v": _VERSION,
        "k": str(kind),
        "r": str(row_id),
        "o": str(organization_id),
        "u": str(user_id),
        "e": int((now if now is not None else time.time()) + settings.media_url_ttl_s),
    }
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(_secret(settings), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(signature)}"


class MediaGrant:
    """A verified token's claims."""

    __slots__ = ("kind", "row_id", "organization_id", "user_id")

    def __init__(self, kind: MediaKind, row_id: str, organization_id: str, user_id: str) -> None:
        self.kind = kind
        self.row_id = row_id
        self.organization_id = organization_id
        self.user_id = user_id


def verify(
    token: str,
    *,
    kind: MediaKind,
    row_id: str,
    settings: Settings,
    now: float | None = None,
) -> MediaGrant:
    """Check a token, and that it is for *this* row on *this* route.

    `kind` and `row_id` are required rather than returned for the caller to
    compare, because a comparison a caller has to remember to make is one that
    eventually is not made.
    """
    body, _, signature = token.partition(".")
    if not body or not signature:
        raise InvalidMediaToken("Malformed token.")

    expected = hmac.new(_secret(settings), body.encode(), hashlib.sha256).digest()
    try:
        given = _unb64(signature)
    except (ValueError, TypeError) as exc:
        raise InvalidMediaToken("Malformed signature.") from exc
    # Constant time: a comparison that returns early leaks the signature one
    # byte at a time to anyone willing to measure.
    if not hmac.compare_digest(expected, given):
        raise InvalidMediaToken("Bad signature.")

    try:
        claims = json.loads(_unb64(body))
    except (ValueError, TypeError) as exc:
        raise InvalidMediaToken("Malformed payload.") from exc
    if not isinstance(claims, dict) or claims.get("v") != _VERSION:
        raise InvalidMediaToken("Unsupported token version.")

    if claims.get("e", 0) <= (now if now is not None else time.time()):
        raise InvalidMediaToken("Expired.")
    # Bound to one resource. Without this a link to any plate would be a link
    # to every plate the signer could read.
    if claims.get("k") != str(kind) or claims.get("r") != str(row_id):
        raise InvalidMediaToken("Token is for a different resource.")

    for field in ("o", "u"):
        try:
            uuid.UUID(str(claims.get(field)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise InvalidMediaToken("Malformed claims.") from exc

    return MediaGrant(
        kind=MediaKind(claims["k"]),
        row_id=str(claims["r"]),
        organization_id=str(claims["o"]),
        user_id=str(claims["u"]),
    )


# ------------------------------------------------------------------- minting


class MediaLink:
    """Mints links for the organization and caller this request acts as.

    Built from an already-resolved `Principal`, so a link can only ever be
    minted by a request that passed the ordinary authorization it replaces.
    There is deliberately no way to mint one for another organization: the
    signer has no parameter for it.

    Each method owns the path template as well as the kind, so the two cannot
    drift apart — a link that claimed `BRAND_ASSET` while pointing at the
    plate route would simply fail to verify, but it would fail confusingly.
    """

    __slots__ = ("_principal", "_settings")

    def __init__(self, principal: Principal, settings: Settings) -> None:
        self._principal = principal
        self._settings = settings

    def _token(self, kind: MediaKind, row_id: uuid.UUID | str) -> str:
        return mint(
            kind=kind,
            row_id=row_id,
            organization_id=self._principal.organization_id,
            user_id=self._principal.user.id,
            settings=self._settings,
        )

    def reference(self, campaign_id: uuid.UUID | str, reference_id: uuid.UUID | str) -> str:
        token = self._token(MediaKind.REFERENCE, reference_id)
        return f"/v1/campaigns/{campaign_id}/references/{reference_id}/content?token={token}"

    def generated_asset(self, campaign_id: uuid.UUID | str, asset_id: uuid.UUID | str) -> str:
        token = self._token(MediaKind.GENERATED_ASSET, asset_id)
        return f"/v1/campaigns/{campaign_id}/assets/{asset_id}/content?token={token}"

    def brand_asset(self, brand_id: uuid.UUID | str, asset_id: uuid.UUID | str) -> str:
        token = self._token(MediaKind.BRAND_ASSET, asset_id)
        return f"/v1/brands/{brand_id}/assets/{asset_id}/content?token={token}"

    def final_asset(
        self, campaign_id: uuid.UUID | str, asset_id: uuid.UUID | str, *, download: bool = False
    ) -> str:
        """The rendered deliverable, inline or as an attachment.

        `download` is built here rather than left to the caller because `url`
        already carries a query string: appending `?download=true` to a signed
        link folds the flag into the token value and produces a bad signature.
        """
        token = self._token(MediaKind.FINAL_ASSET, asset_id)
        suffix = "&download=true" if download else ""
        return f"/v1/campaigns/{campaign_id}/final-assets/{asset_id}/content?token={token}{suffix}"
