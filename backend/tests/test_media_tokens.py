"""The signed media link, at the unit level.

The HTTP behaviour is in `tests/integration/test_media_links.py`. This file
asserts the properties of the token itself — the ones that do not need a
database and would be tedious to provoke over HTTP: forgery, expiry, and the
binding to one resource.
"""

from __future__ import annotations

import time
import uuid

import pytest

from app.api.media_links import (
    InvalidMediaToken,
    MediaKind,
    MediaLink,
    mint,
    verify,
)
from app.config import AppEnv, Settings
from app.domain.common import Role
from app.domain.workspace import Principal, User
from tests.conftest import production_settings

ORG = str(uuid.uuid4())
OTHER_ORG = str(uuid.uuid4())
USER = str(uuid.uuid4())
ROW = str(uuid.uuid4())
OTHER_ROW = str(uuid.uuid4())


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://localhost/test",
        "media_url_secret": "a-test-signing-key",
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


def _token(**overrides: object) -> str:
    kwargs: dict[str, object] = {
        "kind": MediaKind.GENERATED_ASSET,
        "row_id": ROW,
        "organization_id": ORG,
        "user_id": USER,
        "settings": _settings(),
    }
    kwargs.update(overrides)
    return mint(**kwargs)  # type: ignore[arg-type]


class TestAValidToken:
    def test_it_round_trips_its_claims(self) -> None:
        grant = verify(_token(), kind=MediaKind.GENERATED_ASSET, row_id=ROW, settings=_settings())
        assert grant.kind is MediaKind.GENERATED_ASSET
        assert grant.row_id == ROW
        assert grant.organization_id == ORG
        assert grant.user_id == USER

    def test_it_carries_no_storage_key(self) -> None:
        """The whole point. A token names a row; the key is read from that row.

        If a key could ride in the token, `?token=` would be the arbitrary
        storage access the M10 rule exists to prevent.
        """
        import base64
        import json

        body = _token().split(".")[0]
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        assert set(claims) == {"v", "k", "r", "o", "u", "e"}
        assert not any("/" in str(v) for v in claims.values())


class TestForgery:
    def test_a_tampered_payload_is_refused(self) -> None:
        body, _, signature = _token().partition(".")
        forged = mint(
            kind=MediaKind.GENERATED_ASSET,
            row_id=OTHER_ROW,
            organization_id=OTHER_ORG,
            user_id=USER,
            settings=_settings(),
        ).split(".")[0]
        with pytest.raises(InvalidMediaToken):
            verify(
                f"{forged}.{signature}",
                kind=MediaKind.GENERATED_ASSET,
                row_id=OTHER_ROW,
                settings=_settings(),
            )

    def test_a_token_signed_with_another_key_is_refused(self) -> None:
        theirs = _token(settings=_settings(media_url_secret="a-different-key"))
        with pytest.raises(InvalidMediaToken):
            verify(theirs, kind=MediaKind.GENERATED_ASSET, row_id=ROW, settings=_settings())

    @pytest.mark.parametrize("token", ["", ".", "nodot", "a.b", "....", "not-base64!.also-not!"])
    def test_rubbish_is_refused_rather_than_raising(self, token: str) -> None:
        with pytest.raises(InvalidMediaToken):
            verify(token, kind=MediaKind.GENERATED_ASSET, row_id=ROW, settings=_settings())

    def test_claims_that_are_not_ids_are_refused(self) -> None:
        """A path where an organization id should be is not a near miss."""
        bad = mint(
            kind=MediaKind.GENERATED_ASSET,
            row_id=ROW,
            organization_id="../../etc/passwd",
            user_id=USER,
            settings=_settings(),
        )
        with pytest.raises(InvalidMediaToken):
            verify(bad, kind=MediaKind.GENERATED_ASSET, row_id=ROW, settings=_settings())


class TestBinding:
    def test_a_token_for_one_row_does_not_open_another(self) -> None:
        with pytest.raises(InvalidMediaToken):
            verify(_token(), kind=MediaKind.GENERATED_ASSET, row_id=OTHER_ROW, settings=_settings())

    def test_a_token_for_one_kind_does_not_open_another_route(self) -> None:
        """A brand asset link replayed against the composition route.

        Ids are uuids and a collision is not the threat; the threat is a route
        that trusts a signature without asking what it was signed for.
        """
        brand = _token(kind=MediaKind.BRAND_ASSET)
        with pytest.raises(InvalidMediaToken):
            verify(brand, kind=MediaKind.FINAL_ASSET, row_id=ROW, settings=_settings())


class TestExpiry:
    def test_it_expires(self) -> None:
        settings = _settings(media_url_ttl_s=60)
        token = mint(
            kind=MediaKind.GENERATED_ASSET,
            row_id=ROW,
            organization_id=ORG,
            user_id=USER,
            settings=settings,
            now=1_000_000,
        )
        # One second inside the window.
        verify(
            token,
            kind=MediaKind.GENERATED_ASSET,
            row_id=ROW,
            settings=settings,
            now=1_000_059,
        )
        with pytest.raises(InvalidMediaToken, match="Expired"):
            verify(
                token,
                kind=MediaKind.GENERATED_ASSET,
                row_id=ROW,
                settings=settings,
                now=1_000_061,
            )

    def test_the_lifetime_is_bounded(self) -> None:
        """A link that lives for a week is a link, not a short-lived one."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _settings(media_url_ttl_s=10)
        with pytest.raises(ValidationError):
            _settings(media_url_ttl_s=86_401)


class TestTheSigner:
    """`MediaLink` is the only way a route mints one, and it has no parameter
    for an organization — so a route cannot sign for a tenant it is not acting
    as, even by mistake."""

    @staticmethod
    def _link() -> MediaLink:
        return MediaLink(
            Principal(
                user=User(id=USER, email="someone@example.test"),
                organization_id=ORG,
                role=Role.ADMIN,
            ),
            _settings(),
        )

    def test_every_url_it_builds_verifies_for_its_own_route(self) -> None:
        link = self._link()
        campaign, brand, row = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        for url, kind in (
            (link.reference(campaign, row), MediaKind.REFERENCE),
            (link.generated_asset(campaign, row), MediaKind.GENERATED_ASSET),
            (link.brand_asset(brand, row), MediaKind.BRAND_ASSET),
            (link.final_asset(campaign, row), MediaKind.FINAL_ASSET),
        ):
            token = url.split("token=")[1].split("&")[0]
            grant = verify(token, kind=kind, row_id=str(row), settings=_settings())
            assert grant.organization_id == ORG

    def test_the_download_variant_keeps_the_signature_intact(self) -> None:
        """`url + "?download=true"` folds the flag into the token value. The
        server builds the download link so no caller has to know that."""
        url = self._link().final_asset(uuid.uuid4(), ROW, download=True)
        assert "?token=" in url and "&download=true" in url
        token = url.split("token=")[1].split("&")[0]
        verify(token, kind=MediaKind.FINAL_ASSET, row_id=ROW, settings=_settings())


class TestConfiguration:
    def test_no_secret_is_fine_outside_production(self) -> None:
        """The offline demo and the test suite configure nothing.

        A per-process key rather than a shipped default, which would be the
        same on every install and therefore public.
        """
        settings = Settings(
            database_url="postgresql+asyncpg://localhost/test", media_url_secret=None
        )
        token = mint(
            kind=MediaKind.REFERENCE,
            row_id=ROW,
            organization_id=ORG,
            user_id=USER,
            settings=settings,
        )
        assert verify(token, kind=MediaKind.REFERENCE, row_id=ROW, settings=settings)

    def test_production_refuses_to_start_without_one(self) -> None:
        """Two instances with two generated keys reject each other's links,
        which presents as images that load on refresh and not before."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="MEDIA_URL_SECRET"):
            Settings(
                app_env=AppEnv.PRODUCTION,
                database_url="postgresql+asyncpg://localhost/test",
                auth_provider="supabase",
                supabase_url="https://project.supabase.co",
                supabase_anon_key="anon",
            )

    def test_production_starts_with_one(self) -> None:
        settings = production_settings(
            auth_provider="supabase",
            supabase_url="https://project.supabase.co",
            supabase_anon_key="anon",
            media_url_secret="configured",
        )
        assert settings.media_url_secret == "configured"
        assert settings.media_url_ttl_s == 900


def test_a_link_is_short_enough_to_live_in_a_url() -> None:
    """Not cosmetic: these end up in server logs and proxy buffers, and a
    response with fifty of them should not be dominated by signatures."""
    url = MediaLink(
        Principal(
            user=User(id=USER, email="someone@example.test"),
            organization_id=ORG,
            role=Role.ADMIN,
        ),
        _settings(),
    ).generated_asset(uuid.uuid4(), uuid.uuid4())
    assert len(url.split("token=")[1]) < 300


def test_minting_is_cheap() -> None:
    """One per asset per response, so it must not be a per-request cost that
    shows up in a list of fifty."""
    settings = _settings()
    start = time.perf_counter()
    for _ in range(1000):
        mint(
            kind=MediaKind.GENERATED_ASSET,
            row_id=ROW,
            organization_id=ORG,
            user_id=USER,
            settings=settings,
        )
    assert time.perf_counter() - start < 1.0
