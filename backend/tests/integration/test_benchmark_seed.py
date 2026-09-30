"""The benchmark loaded into a database, and the boundary around each company.

The dataset's first claim is tenant isolation: three companies, three
organizations, and no path by which one sees another. That claim is only
worth something if it is tested against the real repositories with the real
scoping, which is what these do.

They seed through `scripts/seed_benchmark.py`'s own builder rather than
inserting rows directly, so what is under test is the thing that actually
runs.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.benchmark import COMPANIES
from app.db.models import BrandProfileRow, CampaignRow, Organization
from app.domain.campaign import CampaignBrief
from app.domain.creative import CreativeSpecification
from app.repositories.brands import BrandRepository
from app.repositories.campaigns import CampaignRepository, CampaignSpecificationRepository
from app.repositories.creative import CreativeSpecificationRepository
from scripts.seed_benchmark import ORG_SLUG_PREFIX, build_company, drop

pytestmark = pytest.mark.integration


async def _brands(session, organization_id):
    """Every brand in the organization.

    The repositories page now (audit finding PERF-1), and these assertions are
    about containment rather than about paging: a benchmark organization holds
    one brand and three campaigns, so one page over the limit is all of them.
    """
    return (await BrandRepository(session, organization_id).list_page(limit=100)).items


async def _campaigns(session, organization_id):
    return (await CampaignRepository(session, organization_id).list_page(limit=100)).items


@pytest.fixture
async def seeded(session, workspace):
    """All three companies, built through the real seeder."""
    await drop(session)
    built = {}
    for company in COMPANIES:
        organization_id, _ = await build_company(session, company, workspace.user.id)
        built[company.slug] = organization_id
    yield built
    await drop(session)


class TestItSeeds:
    async def test_each_company_gets_its_own_organization(self, session, seeded) -> None:
        assert len(set(seeded.values())) == 3

        slugs = (
            (
                await session.execute(
                    select(Organization.slug).where(Organization.slug.startswith(ORG_SLUG_PREFIX))
                )
            )
            .scalars()
            .all()
        )
        assert set(slugs) == {c.organization_slug for c in COMPANIES}

    async def test_every_company_has_one_brand_and_three_campaigns(self, session, seeded) -> None:
        for company in COMPANIES:
            organization_id = seeded[company.slug]
            brands = await _brands(session, organization_id)
            campaigns = await _campaigns(session, organization_id)
            assert len(brands) == 1, company.slug
            assert brands[0].name == company.brand.name
            assert len(campaigns) == 3, company.slug

    async def test_the_campaign_specification_is_stored_and_confirmed(
        self, session, seeded
    ) -> None:
        organization_id = seeded["nila-living"]
        campaigns = await _campaigns(session, organization_id)
        specs = CampaignSpecificationRepository(session, organization_id)

        for campaign in campaigns:
            row = await specs.latest(campaign.id)
            assert row is not None, campaign.title
            assert row.confirmed_at is not None, "the specification is agreed, not draft"
            # It round-trips as the real domain model, not as a loose dict.
            brief = CampaignBrief.model_validate(row.payload)
            assert brief.region and brief.language

    async def test_the_creative_specification_is_approved_with_its_direction(
        self, session, seeded
    ) -> None:
        organization_id = seeded["aarohan-foods"]
        campaigns = await _campaigns(session, organization_id)
        creative = CreativeSpecificationRepository(session, organization_id)

        for campaign in campaigns:
            row = await creative.latest(campaign.id)
            assert row is not None
            assert row.approved_at is not None, "Gate 2 is decided in the dataset"
            assert row.direction_id is not None, "the approved plan names its direction"
            specification = CreativeSpecification.model_validate(row.payload)
            assert specification.campaign_id == str(campaign.id)

    async def test_a_second_build_is_refused_rather_than_duplicated(
        self, session, workspace, seeded
    ) -> None:
        """Idempotency, and where it actually comes from.

        `build_company` is not itself idempotent — but it cannot duplicate
        either, because `brand_profiles` has a unique name per organization
        and the repository turns that into a typed `Conflict`. The script's
        own `already_seeded` guard is what turns "cannot duplicate" into
        "re-running is a clean no-op".
        """
        from app.errors import Conflict

        company = next(c for c in COMPANIES if c.slug == "mitti-and-bean")
        before = len(await _campaigns(session, seeded[company.slug]))

        with pytest.raises(Conflict, match="already exists"):
            await build_company(session, company, workspace.user.id)

        after = len(await _campaigns(session, seeded[company.slug]))
        assert after == before, "a refused re-seed must leave the row count alone"

    async def test_the_script_guard_reports_existing_data(self, session, seeded) -> None:
        from scripts.seed_benchmark import already_seeded

        assert await already_seeded(session) is True


class TestOrganizationIsolation:
    async def test_no_company_can_read_another_companys_brand(self, session, seeded) -> None:
        """The core tenancy claim, tested through the scoped repository."""
        for company in COMPANIES:
            mine = seeded[company.slug]
            visible = {b.name for b in await _brands(session, mine)}
            assert visible == {company.brand.name}, (
                f"{company.slug} can see brands that are not its own: {visible}"
            )

    async def test_no_company_can_read_another_companys_campaigns(self, session, seeded) -> None:
        expected = {c.slug: {e.brief.title for e in c.campaigns} for c in COMPANIES}
        for company in COMPANIES:
            visible = {row.title for row in await _campaigns(session, seeded[company.slug])}
            assert visible == expected[company.slug]
            for other in COMPANIES:
                if other.slug != company.slug:
                    assert not (visible & expected[other.slug]), (
                        f"{company.slug} sees {other.slug}'s campaigns"
                    )

    async def test_fetching_another_organizations_campaign_by_id_returns_nothing(
        self, session, seeded
    ) -> None:
        """Scope is checked on read, not only on list."""
        mitti = seeded["mitti-and-bean"]
        aarohan = seeded["aarohan-foods"]
        theirs = (await _campaigns(session, aarohan))[0]

        as_mitti = CampaignRepository(session, mitti)
        assert await as_mitti.get(theirs.id) is None

    async def test_another_organizations_creative_specification_is_invisible(
        self, session, seeded
    ) -> None:
        nila = seeded["nila-living"]
        aarohan = seeded["aarohan-foods"]
        theirs = (await _campaigns(session, aarohan))[0]

        as_nila = CreativeSpecificationRepository(session, nila)
        assert await as_nila.latest(theirs.id) is None, (
            "a creative specification leaked across an organization boundary"
        )

    async def test_an_unrelated_organization_id_sees_nothing_at_all(self, session, seeded) -> None:
        stranger = uuid.uuid4()
        assert await _brands(session, stranger) == []
        assert await _campaigns(session, stranger) == []


class TestNoCrossLocationContamination:
    async def test_each_organizations_rows_carry_only_its_own_city(self, session, seeded) -> None:
        """Location is carried in the data, not only in the documentation.

        Reads the stored payloads rather than the in-memory dataset, so this
        is a statement about what a database query would return.
        """
        cities = {c.slug: c.market.city for c in COMPANIES}
        for company in COMPANIES:
            organization_id = seeded[company.slug]
            campaigns = await _campaigns(session, organization_id)
            specs = CampaignSpecificationRepository(session, organization_id)

            foreign = [cities[s] for s in cities if s != company.slug]
            for campaign in campaigns:
                row = await specs.latest(campaign.id)
                assert row is not None
                blob = str(row.payload)
                for city in foreign:
                    assert city not in blob, f"{company.slug}/{campaign.title} mentions {city}"

    async def test_the_demo_dataset_is_untouched(self, session, seeded) -> None:
        """`--reset` must never reach outside the benchmark namespace."""
        await drop(session)

        survivors = (
            (
                await session.execute(
                    select(Organization.slug).where(~Organization.slug.startswith(ORG_SLUG_PREFIX))
                )
            )
            .scalars()
            .all()
        )
        assert survivors, "drop() removed organizations it does not own"

        # And nothing of the benchmark's own remains.
        remaining = (
            (
                await session.execute(
                    select(BrandProfileRow)
                    .join(
                        Organization,
                        Organization.id == BrandProfileRow.organization_id,
                    )
                    .where(Organization.slug.startswith(ORG_SLUG_PREFIX))
                )
            )
            .scalars()
            .all()
        )
        assert remaining == []
        assert (
            await session.execute(
                select(CampaignRow)
                .join(Organization, Organization.id == CampaignRow.organization_id)
                .where(Organization.slug.startswith(ORG_SLUG_PREFIX))
            )
        ).scalars().all() == []
