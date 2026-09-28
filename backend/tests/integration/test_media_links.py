"""Serving bytes to a browser, over HTTP.

## What was broken

Organization scope is resolved from `X-Organization-Id` and identity from
`Authorization`. A browser can put neither on an `<img src>`, so no generated
plate, reference, brand asset or rendered deliverable could be displayed on the
page that describes it. Under `AUTH_PROVIDER=dev_stub` a caller with one
membership worked by accident — the stub ignores the credential and a single
membership is resolved implicitly — and a caller with several got a 403 telling
them to send a header their browser cannot send. Under a real identity provider
nothing would have loaded for anyone.

These tests pin the fix *and* the defect: `test_the_defect` reproduces the
original failure, so a regression that reintroduced header-only media would
fail here rather than in someone's browser.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.integration.factories import make_membership, make_org

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------- setup


async def _second_organization(session, workspace) -> object:
    """A second membership for the same caller — the multi-organization case.

    Every request must now name an organization, which is correct for an API
    client and impossible for an `<img>`.
    """
    other = await make_org(session)
    await make_membership(session, workspace.user, other)
    await session.flush()
    return other


def _as(client: AsyncClient, org) -> dict[str, str]:
    return {"X-Organization-Id": str(org.id)}


async def _brand(client: AsyncClient, headers: dict[str, str], name: str) -> str:
    response = await client.post("/v1/brands", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _campaign(client: AsyncClient, headers: dict[str, str], brand_id: str) -> str:
    response = await client.post(
        "/v1/campaigns", json={"brand_id": brand_id, "title": "Launch"}, headers=headers
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
    b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def _reference(client: AsyncClient, headers: dict[str, str], campaign_id: str) -> dict:
    """A campaign reference, uploaded the way a person uploads one."""
    response = await client.post(
        f"/v1/campaigns/{campaign_id}/references",
        files={"file": ("mood.png", _PNG, "image/png")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _brand_asset(client: AsyncClient, headers: dict[str, str], brand_id: str) -> dict:
    response = await client.post(
        f"/v1/brands/{brand_id}/assets",
        files={"file": ("logo.png", _PNG, "image/png")},
        data={"kind": "logo"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


# ------------------------------------------------------------- the defect


class TestTheDefect:
    """The original bug, kept as a test so it cannot come back quietly."""

    async def test_a_browser_cannot_send_the_scope_header(self, client, session, workspace) -> None:
        other = await _second_organization(session, workspace)
        headers = _as(client, workspace.org)
        brand = await _brand(client, headers, "Northline")
        campaign = await _campaign(client, headers, brand)
        reference = await _reference(client, headers, campaign)
        assert other  # the caller now belongs to two organizations

        # What an `<img src>` sends: no headers at all. Before the fix this
        # was the 403 that told the user to send a header a browser cannot set.
        bare = await client.get(reference["url"].split("?")[0])
        assert bare.status_code == 403
        assert "several organizations" in bare.json()["error"]["message"]

        # What the API hands the page instead.
        signed = await client.get(reference["url"])
        assert signed.status_code == 200
        assert signed.content == _PNG


# -------------------------------------------------------- the two transports


class TestBothTransportsWork:
    async def test_headers_still_serve_bytes(self, client, session, workspace) -> None:
        """An API client, a script and `curl` are unaffected."""
        headers = _as(client, workspace.org)
        brand = await _brand(client, headers, "Northline")
        campaign = await _campaign(client, headers, brand)
        reference = await _reference(client, headers, campaign)

        response = await client.get(reference["url"].split("?")[0], headers=headers)
        assert response.status_code == 200
        assert response.content == _PNG

    async def test_a_single_membership_needs_no_header_at_all(
        self, client, session, workspace
    ) -> None:
        """The dev stub resolves one membership implicitly. That path is
        unchanged — the fix added a transport, it did not replace one."""
        headers: dict[str, str] = {}
        brand = await _brand(client, headers, "Northline")
        campaign = await _campaign(client, headers, brand)
        reference = await _reference(client, headers, campaign)
        assert (await client.get(reference["url"].split("?")[0])).status_code == 200
        assert (await client.get(reference["url"])).status_code == 200


class TestEachOrganizationSeesItsOwn:
    async def test_a_link_works_in_either_organization(self, client, session, workspace) -> None:
        other = await _second_organization(session, workspace)
        mine, theirs = _as(client, workspace.org), _as(client, other)

        here = await _reference(
            client, mine, await _campaign(client, mine, await _brand(client, mine, "Northline"))
        )
        there = await _reference(
            client, theirs, await _campaign(client, theirs, await _brand(client, theirs, "Fenesta"))
        )

        # No headers on either: the signature carries the organization.
        assert (await client.get(here["url"])).status_code == 200
        assert (await client.get(there["url"])).status_code == 200
        assert here["url"] != there["url"]


# ----------------------------------------------------------------- tenancy


class TestTenancy:
    async def test_a_link_minted_in_one_organization_cannot_read_another(
        self, client, session, workspace
    ) -> None:
        """The token names a row and an organization; the route still resolves
        that row through the organization-scoped repository."""
        other = await _second_organization(session, workspace)
        mine, theirs = _as(client, workspace.org), _as(client, other)

        my_campaign = await _campaign(client, mine, await _brand(client, mine, "Northline"))
        their_campaign = await _campaign(client, theirs, await _brand(client, theirs, "Fenesta"))
        their_reference = await _reference(client, theirs, their_campaign)
        my_reference = await _reference(client, mine, my_campaign)

        # My signature, their row: the token is bound to a row id, so it does
        # not verify against theirs.
        my_token = my_reference["url"].split("token=")[1]
        their_path = their_reference["url"].split("?")[0]
        assert (await client.get(f"{their_path}?token={my_token}")).status_code == 404

    async def test_a_valid_token_cannot_be_moved_to_another_campaign(
        self, client, session, workspace
    ) -> None:
        """The campaign in the path is still checked against the row."""
        headers = _as(client, workspace.org)
        brand = await _brand(client, headers, "Northline")
        mine = await _campaign(client, headers, brand)
        decoy = await _campaign(client, headers, brand)
        reference = await _reference(client, headers, mine)

        moved = reference["url"].replace(mine, decoy)
        assert (await client.get(moved)).status_code == 404

    async def test_losing_membership_revokes_outstanding_links(
        self, client, session, workspace
    ) -> None:
        """Membership is authority, not history.

        Expiry alone would leave someone reading a tenant's images for the
        rest of the window after they were removed from it.
        """
        from sqlalchemy import delete

        from app.db.models import Membership

        other = await _second_organization(session, workspace)
        theirs = _as(client, other)
        reference = await _reference(
            client,
            theirs,
            await _campaign(client, theirs, await _brand(client, theirs, "Fenesta")),
        )
        assert (await client.get(reference["url"])).status_code == 200

        await session.execute(
            delete(Membership).where(
                Membership.user_id == workspace.user.id,
                Membership.organization_id == other.id,
            )
        )
        await session.flush()

        assert (await client.get(reference["url"])).status_code == 404


# ------------------------------------------------------------- bad tokens


class TestRefusedTokens:
    @pytest.fixture
    async def link(self, client, session, workspace) -> str:
        headers = _as(client, workspace.org)
        reference = await _reference(
            client,
            headers,
            await _campaign(client, headers, await _brand(client, headers, "Northline")),
        )
        return str(reference["url"])

    async def test_a_tampered_signature_is_not_found(self, client, link) -> None:
        path, _, token = link.partition("token=")
        assert (await client.get(f"{path}token={token[:-4]}AAAA")).status_code == 404

    async def test_an_absent_token_with_no_headers_is_refused(
        self, client, session, workspace, link
    ) -> None:
        await _second_organization(session, workspace)
        assert (await client.get(link.split("?")[0])).status_code == 403

    @pytest.mark.parametrize("token", ["", "rubbish", "a.b", "../../etc/passwd", "%2e%2e%2f"])
    async def test_rubbish_is_not_found_rather_than_a_500(self, client, link, token: str) -> None:
        path = link.split("?")[0]
        assert (await client.get(f"{path}?token={token}")).status_code in (403, 404)

    async def test_an_expired_link_is_not_found(self, client, session, workspace) -> None:
        """Minted in the past, so no clock is slept on."""
        from app.api.media_links import MediaKind, mint
        from app.config import get_settings

        headers = _as(client, workspace.org)
        campaign = await _campaign(client, headers, await _brand(client, headers, "Northline"))
        reference = await _reference(client, headers, campaign)

        settings = get_settings()
        stale = mint(
            kind=MediaKind.REFERENCE,
            row_id=reference["id"],
            organization_id=str(workspace.org.id),
            user_id=str(workspace.user.id),
            settings=settings,
            now=0,
        )
        path = reference["url"].split("?")[0]
        assert (await client.get(f"{path}?token={stale}")).status_code == 404

    async def test_a_token_for_a_row_that_does_not_exist_is_not_found(
        self, client, session, workspace
    ) -> None:
        from app.api.media_links import MediaKind, mint
        from app.config import get_settings

        headers = _as(client, workspace.org)
        campaign = await _campaign(client, headers, await _brand(client, headers, "Northline"))
        ghost = uuid.uuid4()
        token = mint(
            kind=MediaKind.REFERENCE,
            row_id=ghost,
            organization_id=str(workspace.org.id),
            user_id=str(workspace.user.id),
            settings=get_settings(),
        )
        url = f"/v1/campaigns/{campaign}/references/{ghost}/content?token={token}"
        assert (await client.get(url)).status_code == 404

    async def test_a_token_cannot_name_a_storage_key(self, client, session, workspace) -> None:
        """There is no key claim to abuse, and the row id is parsed as a path
        segment — a traversal attempt is a row that does not exist."""
        from app.api.media_links import MediaKind, mint
        from app.config import get_settings

        headers = _as(client, workspace.org)
        campaign = await _campaign(client, headers, await _brand(client, headers, "Northline"))
        token = mint(
            kind=MediaKind.REFERENCE,
            row_id="../../../etc/passwd",
            organization_id=str(workspace.org.id),
            user_id=str(workspace.user.id),
            settings=get_settings(),
        )
        response = await client.get(
            f"/v1/campaigns/{campaign}/references/..%2F..%2Fetc%2Fpasswd/content?token={token}"
        )
        assert response.status_code == 404
        assert b"root:" not in response.content


class TestUnauthenticated:
    async def test_no_credential_and_no_token_is_401(self, session, workspace, api_storage) -> None:
        """The dev stub authenticates everyone, so this is asserted against a
        provider that does not — which is what production runs."""
        from httpx import ASGITransport, AsyncClient

        from app.api.deps import get_db, get_storage_provider
        from app.auth.base import AuthenticationError
        from app.auth.registry import get_auth_provider
        from app.config import Settings, get_settings
        from app.main import create_app
        from tests.integration.conftest import TEST_DATABASE_URL

        class RefusingAuth:
            name = "refusing"

            async def authenticate(self, credentials: str | None) -> object:
                raise AuthenticationError("No session.")

        settings = Settings(
            app_env="test",
            database_url=TEST_DATABASE_URL,
            database_url_sync=TEST_DATABASE_URL.replace("postgresql+asyncpg", "postgresql"),
            auth_provider="dev_stub",
        )
        app = create_app(settings)
        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_auth_provider] = lambda: RefusingAuth()
        app.dependency_overrides[get_storage_provider] = lambda: api_storage

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            response = await http.get(f"/v1/campaigns/{uuid.uuid4()}/assets/{uuid.uuid4()}/content")
            assert response.status_code == 401


# ------------------------------------------------------- every consumer


async def _through_to_generation(
    client: AsyncClient, session, workspace, headers, api_storage
) -> str:
    """A campaign with real generated plates, produced by the real services.

    Generation runs in a background task that the harness stubs out, so the
    jobs are driven here on the test session — the same code the task runs,
    and writing into the storage root the app serves from.
    """
    from app.config import get_settings
    from app.domain.common import Role
    from app.domain.workspace import Principal, User
    from app.providers.mock.embedding import MockEmbeddingProvider
    from app.providers.mock.llm import MockLLMProvider
    from app.services.generation import GenerationService

    brand = await _brand(client, headers, f"Northline {uuid.uuid4().hex[:6]}")
    campaign = await _campaign(client, headers, brand)
    await client.post(f"/v1/campaigns/{campaign}/discovery/start", headers=headers)
    for answer in (
        "This is a product launch.",
        "The FS-9 facade system.",
        "Architects and specifiers in Maharashtra.",
        "Engineered to outlast the building it clads.",
        "LinkedIn and Instagram post.",
    ):
        body = (
            await client.post(
                f"/v1/campaigns/{campaign}/discovery/answer",
                json={"answer": answer},
                headers=headers,
            )
        ).json()
        if body.get("interview_complete"):
            break
    await client.post(f"/v1/campaigns/{campaign}/specification/confirm", headers=headers)
    started = (
        await client.post(f"/v1/campaigns/{campaign}/creative/start", headers=headers)
    ).json()
    await client.post(
        f"/v1/campaigns/{campaign}/creative/strategy",
        json={
            "decision": "APPROVE",
            "direction_id": started["direction_set"]["directions"][0]["id"],
        },
        headers=headers,
    )
    await client.post(
        f"/v1/campaigns/{campaign}/creative/specification/decide",
        json={"decision": "APPROVE"},
        headers=headers,
    )
    await client.post(f"/v1/campaigns/{campaign}/generation/start", headers=headers)

    org_id = headers.get("X-Organization-Id", str(workspace.org.id))
    service = GenerationService(
        session,
        Principal(
            user=User(id=str(workspace.user.id), email=workspace.user.email),
            organization_id=org_id,
            role=Role.ADMIN,
        ),
        settings=get_settings(),
        # The `api_storage` fixture *is* the app's storage, so the bytes these
        # jobs write are the bytes the byte-serving route later reads. Importing
        # the conftest constant instead gets a second copy of that module, with
        # a second temporary directory, and the route finds nothing.
        storage=api_storage,
        llm=MockLLMProvider(),
        embeddings=MockEmbeddingProvider(),
    )
    view = await service.current(uuid.UUID(campaign))
    await service.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])
    return campaign


class TestEveryConsumer:
    """All four media families, because fixing only the one that was reported
    leaves three routes a browser still cannot read."""

    async def test_a_brand_asset_is_readable_from_a_page(self, client, session, workspace) -> None:
        await _second_organization(session, workspace)
        headers = _as(client, workspace.org)
        brand = await _brand(client, headers, "Northline")
        asset = await _brand_asset(client, headers, brand)

        assert "token=" in asset["url"]
        response = await client.get(asset["url"])
        assert response.status_code == 200
        assert response.content == _PNG

    async def test_a_campaign_reference_is_readable_from_a_page(
        self, client, session, workspace
    ) -> None:
        await _second_organization(session, workspace)
        headers = _as(client, workspace.org)
        campaign = await _campaign(client, headers, await _brand(client, headers, "Northline"))
        reference = await _reference(client, headers, campaign)

        assert "token=" in reference["url"]
        assert (await client.get(reference["url"])).status_code == 200

    async def test_a_generated_plate_is_readable_from_a_page(
        self, client, session, workspace, api_storage
    ) -> None:
        await _second_organization(session, workspace)
        headers = _as(client, workspace.org)
        campaign = await _through_to_generation(client, session, workspace, headers, api_storage)

        view = (await client.get(f"/v1/campaigns/{campaign}/assets", headers=headers)).json()
        assert view["assets"], "the batch produced a plate"
        for asset in view["assets"]:
            assert "token=" in asset["url"]
            response = await client.get(asset["url"])
            assert response.status_code == 200, response.text
            assert response.headers["content-type"].startswith("image/")
            assert response.content

    async def test_a_rendered_deliverable_is_readable_and_downloadable(
        self, client, session, workspace, api_storage
    ) -> None:
        await _second_organization(session, workspace)
        headers = _as(client, workspace.org)
        campaign = await _through_to_generation(client, session, workspace, headers, api_storage)
        assets = (await client.get(f"/v1/campaigns/{campaign}/assets", headers=headers)).json()[
            "assets"
        ]
        await client.post(
            f"/v1/campaigns/{campaign}/evaluation/select",
            json={"generated_asset_id": assets[0]["id"]},
            headers=headers,
        )
        await client.post(f"/v1/campaigns/{campaign}/composition", json={}, headers=headers)
        rendered = await client.post(
            f"/v1/campaigns/{campaign}/composition/render", json={}, headers=headers
        )
        assert rendered.status_code == 201, rendered.text
        final = rendered.json()

        assert "token=" in final["url"]
        inline = await client.get(final["url"])
        assert inline.status_code == 200
        assert "content-disposition" not in inline.headers

        # The download variant is built by the server, because appending
        # `?download=true` to a signed URL folds the flag into the token.
        attached = await client.get(final["download_url"])
        assert attached.status_code == 200
        assert "attachment" in attached.headers["content-disposition"]

    async def test_no_response_hands_a_page_an_unsigned_media_url(
        self, client, session, workspace, api_storage
    ) -> None:
        """A `url` a browser cannot fetch is worse than no `url`: it renders as
        a broken image with no explanation. Every one in a response is signed.
        """
        await _second_organization(session, workspace)
        headers = _as(client, workspace.org)
        campaign = await _through_to_generation(client, session, workspace, headers, api_storage)
        brand_id = (await client.get(f"/v1/campaigns/{campaign}", headers=headers)).json()[
            "brand_id"
        ]
        await _brand_asset(client, headers, brand_id)
        await _reference(client, headers, campaign)

        def urls(node: object) -> list[str]:
            if isinstance(node, dict):
                found = [v for k, v in node.items() if k.endswith("url") and isinstance(v, str)]
                for value in node.values():
                    found += urls(value)
                return found
            if isinstance(node, list):
                return [u for item in node for u in urls(item)]
            return []

        checked = 0
        for path in (
            f"/v1/campaigns/{campaign}/generation",
            f"/v1/campaigns/{campaign}/assets",
            f"/v1/campaigns/{campaign}/references",
            # Carries final assets once any have been rendered; none here, so
            # it contributes nothing to the count rather than being asserted
            # to contain something it legitimately does not.
            f"/v1/campaigns/{campaign}/overview",
            f"/v1/brands/{brand_id}",
            f"/v1/brands/{brand_id}/assets",
        ):
            response = await client.get(path, headers=headers)
            assert response.status_code == 200, f"{path}: {response.text}"
            for url in (u for u in urls(response.json()) if "/content" in u):
                assert "token=" in url, f"{path} returned an unsigned media url: {url}"
                checked += 1
        # So the sweep cannot pass by finding nothing.
        assert checked >= 3, f"only {checked} media urls seen; the sweep proved little"
