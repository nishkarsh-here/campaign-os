"""Keyset pagination on the organization-level lists.

Audit findings DOC-2/BG-6 and PERF-1. `API_SPEC.md` stated `?limit=&cursor=` as a
convention for lists and one endpoint implemented it; brands and campaigns
returned every row in the organization.

The properties worth asserting are the ones a hand-rolled cursor gets wrong:
that walking the pages yields every row exactly once, that the order each screen
already had is preserved, and that a row written between two reads cannot make a
row disappear — the failure offset pagination has and keyset does not.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ValidationFailed
from app.repositories.brands import BrandRepository
from app.repositories.campaigns import CampaignRepository
from app.repositories.pagination import MAX_LIMIT

pytestmark = pytest.mark.integration

ORG_HEADER = "X-Organization-Id"


async def _brands(session: AsyncSession, org_id, names: list[str]) -> None:
    repo = BrandRepository(session, org_id)
    for name in names:
        await repo.create(name=name, payload={"name": name}, created_by=None)
    await session.flush()


async def _campaigns(session: AsyncSession, org_id, brand_id, count: int) -> None:
    repo = CampaignRepository(session, org_id)
    for index in range(count):
        await repo.create(
            brand_id=brand_id,
            project_id=None,
            title=f"Campaign {index:02d}",
            created_by=None,
        )
    await session.flush()


async def _walk(fetch, limit: int) -> list:
    """Every page, following `next_cursor` to the end."""
    collected: list = []
    cursor: str | None = None
    for _ in range(50):  # a loop bound, so a cursor that never advances fails
        page = await fetch(limit=limit, cursor=cursor)
        collected.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            return collected
    raise AssertionError("pagination did not terminate")


class TestBrandsPageAlphabetically:
    async def test_walking_the_pages_yields_every_brand_once(
        self, session: AsyncSession, workspace
    ) -> None:
        names = [f"Brand {letter}" for letter in "ABCDEFG"]
        await _brands(session, workspace.org.id, names)
        repo = BrandRepository(session, workspace.org.id)

        walked = await _walk(repo.list_page, limit=2)

        assert [row.name for row in walked] == names

    async def test_the_order_the_screen_had_is_preserved(
        self, session: AsyncSession, workspace
    ) -> None:
        """Alphabetical, not by creation. Paging both lists by `created_at`
        would have quietly reordered this one."""
        await _brands(session, workspace.org.id, ["Zebra", "Apple", "Mango"])
        repo = BrandRepository(session, workspace.org.id)

        page = await repo.list_page(limit=10)

        assert [row.name for row in page.items] == ["Apple", "Mango", "Zebra"]

    async def test_the_last_page_has_no_cursor(self, session: AsyncSession, workspace) -> None:
        await _brands(session, workspace.org.id, ["One", "Two"])
        repo = BrandRepository(session, workspace.org.id)

        assert (await repo.list_page(limit=10)).next_cursor is None

    async def test_a_full_page_with_nothing_after_it_has_no_cursor(
        self, session: AsyncSession, workspace
    ) -> None:
        """The off-by-one: fetching limit+1 is what distinguishes "exactly a
        page" from "a page and more", and a cursor here would mean an extra
        request returning nothing."""
        await _brands(session, workspace.org.id, ["One", "Two"])
        repo = BrandRepository(session, workspace.org.id)

        assert (await repo.list_page(limit=2)).next_cursor is None

    async def test_an_empty_organization_pages_cleanly(
        self, session: AsyncSession, workspace
    ) -> None:
        page = await BrandRepository(session, workspace.org.id).list_page(limit=10)

        assert page.items == []
        assert page.next_cursor is None


class TestCampaignsPageNewestFirst:
    async def test_walking_the_pages_yields_every_campaign_once(
        self, session: AsyncSession, workspace
    ) -> None:
        await _brands(session, workspace.org.id, ["Only"])
        brand = (await BrandRepository(session, workspace.org.id).list_page(limit=1)).items[0]
        await _campaigns(session, workspace.org.id, brand.id, 7)
        repo = CampaignRepository(session, workspace.org.id)

        walked = await _walk(repo.list_page, limit=3)

        titles = [row.title for row in walked]
        assert len(titles) == 7
        assert len(set(titles)) == 7, "a row appeared on two pages"

    async def test_newest_first_is_preserved_across_pages(
        self, session: AsyncSession, workspace
    ) -> None:
        """Descending, so the cursor comparison must be `<`. With `>` the second
        page walks backwards and the same rows come round for ever — which the
        loop bound in `_walk` would catch, but the order is the point."""
        await _brands(session, workspace.org.id, ["Only"])
        brand = (await BrandRepository(session, workspace.org.id).list_page(limit=1)).items[0]
        await _campaigns(session, workspace.org.id, brand.id, 5)
        repo = CampaignRepository(session, workspace.org.id)

        walked = await _walk(repo.list_page, limit=2)
        stamps = [row.created_at for row in walked]

        assert stamps == sorted(stamps, reverse=True)

    async def test_the_brand_filter_survives_paging(self, session: AsyncSession, workspace) -> None:
        await _brands(session, workspace.org.id, ["Mine", "Theirs"])
        brands = (await BrandRepository(session, workspace.org.id).list_page(limit=10)).items
        mine, theirs = brands[0], brands[1]
        await _campaigns(session, workspace.org.id, mine.id, 4)
        await _campaigns(session, workspace.org.id, theirs.id, 3)
        repo = CampaignRepository(session, workspace.org.id)

        walked = await _walk(
            lambda limit, cursor: repo.list_page(brand_id=mine.id, limit=limit, cursor=cursor),
            limit=2,
        )

        assert len(walked) == 4
        assert {row.brand_profile_id for row in walked} == {mine.id}


class TestRowsAddedBetweenPagesDoNotHideOthers:
    async def test_an_insert_during_paging_does_not_skip_a_row(
        self, session: AsyncSession, workspace
    ) -> None:
        """The reason this is keyset and not offset. With `OFFSET 2`, inserting a
        row that sorts before the cursor shifts everything down and page two
        repeats a row while a later one is never seen."""
        await _brands(session, workspace.org.id, ["Bravo", "Delta", "Foxtrot", "Hotel"])
        repo = BrandRepository(session, workspace.org.id)

        first = await repo.list_page(limit=2)
        assert [row.name for row in first.items] == ["Bravo", "Delta"]

        # Sorts before the cursor, so it belongs to a page already read.
        await _brands(session, workspace.org.id, ["Alpha"])

        second = await repo.list_page(limit=2, cursor=first.next_cursor)

        assert [row.name for row in second.items] == ["Foxtrot", "Hotel"]


class TestABadCursorIsRefused:
    async def test_nonsense_is_a_validation_failure_not_a_crash(
        self, session: AsyncSession, workspace
    ) -> None:
        with pytest.raises(ValidationFailed):
            await BrandRepository(session, workspace.org.id).list_page(cursor="not-base64!!")

    async def test_a_cursor_from_another_list_is_refused_rather_than_misread(
        self, session: AsyncSession, workspace
    ) -> None:
        """A campaign cursor carries a timestamp; the brand list keys on a name.
        Tagging the kind is what stops one being silently read as the other."""
        await _brands(session, workspace.org.id, ["Only"])
        brand = (await BrandRepository(session, workspace.org.id).list_page(limit=1)).items[0]
        await _campaigns(session, workspace.org.id, brand.id, 3)
        campaigns = await CampaignRepository(session, workspace.org.id).list_page(limit=1)
        assert campaigns.next_cursor is not None

        with pytest.raises(ValidationFailed):
            await BrandRepository(session, workspace.org.id).list_page(cursor=campaigns.next_cursor)


class TestOverHttp:
    async def test_the_brand_list_reports_a_cursor(self, client: AsyncClient, workspace) -> None:
        for name in ("Alpha", "Beta", "Gamma"):
            assert (await client.post("/v1/brands", json={"name": name})).status_code == 201

        response = await client.get("/v1/brands?limit=2")

        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 2
        assert body["next_cursor"]

    async def test_a_client_that_ignores_the_cursor_still_reads_items(
        self, client: AsyncClient, workspace
    ) -> None:
        """The field is additive on purpose: every existing caller reads
        `items` and none of them broke."""
        assert (await client.post("/v1/brands", json={"name": "Only"})).status_code == 201

        body = (await client.get("/v1/brands")).json()

        assert [item["name"] for item in body["items"]] == ["Only"]
        assert body["next_cursor"] is None

    async def test_an_oversized_limit_is_refused(self, client: AsyncClient, workspace) -> None:
        """A ceiling, not a suggestion — an unbounded list is the defect, so a
        caller must not be able to ask for one. `400` rather than FastAPI's `422`
        because this app maps request validation onto its one error shape."""
        response = await client.get(f"/v1/brands?limit={MAX_LIMIT + 1}")

        assert response.status_code == 400

    async def test_the_campaign_list_reports_a_cursor(
        self, client: AsyncClient, session: AsyncSession, workspace
    ) -> None:
        brand_id = (await client.post("/v1/brands", json={"name": "Only"})).json()["id"]
        for index in range(3):
            created = await client.post(
                "/v1/campaigns", json={"brand_id": brand_id, "title": f"C{index}"}
            )
            assert created.status_code == 201, created.text

        body = (await client.get("/v1/campaigns?limit=2")).json()

        assert len(body["items"]) == 2
        assert body["next_cursor"]
