"""Load the Indian Hyperlocal Campaign Benchmark into the database.

    uv run python scripts/seed_benchmark.py            # idempotent load
    uv run python scripts/seed_benchmark.py --reset    # rebuild from scratch

Three fictional companies, each in **its own organization** — which is the
point rather than an implementation detail. The benchmark's first claim is
tenant isolation, and a shared organization with a filter column could only
ever demonstrate that somebody remembered a `WHERE` clause.

**It does not touch the Milestone 10 demo.** That dataset lives in the
`dev_stub_org_slug` organization under the brand "Northline Facades"; this one
lives in three organizations whose slugs begin `benchmark-`. Running either
script leaves the other's data untouched, and `--reset` here deletes only what
this script created.

**No provider is called.** Not an image model, not a language model, not an
embedding model. The dataset is written by hand precisely so that it can be
loaded offline, and the script refuses to run against a live provider for the
same reason `seed_demo.py` does — there is nothing here worth a credit.

What this seeds is the *governed* half of the pipeline: Brand Brain, Campaign
Specification, Creative Directions and the approved Creative Specification
with its per-channel copy. It deliberately stops before generation. Plates,
evaluations and Guardian verdicts are computed by services from real provider
output, and writing them in by hand would be exactly the fake functionality
this project has refused to build since M0.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.benchmark import COMPANIES, BenchmarkCampaign, BenchmarkCompany  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.db.models import (  # noqa: E402
    BrandProfileRow,
    CampaignRow,
    Organization,
    Project,
)
from app.db.session import get_sessionmaker  # noqa: E402
from app.domain.common import CampaignRecordStatus, Role  # noqa: E402
from app.repositories.brands import BrandRepository  # noqa: E402
from app.repositories.campaigns import (  # noqa: E402
    CampaignRepository,
    CampaignSpecificationRepository,
)
from app.repositories.creative import (  # noqa: E402
    CreativeDirectionSetRepository,
    CreativeSpecificationRepository,
)
from app.repositories.organizations import (  # noqa: E402
    MembershipRepository,
    create_organization,
)
from app.repositories.projects import ProjectRepository  # noqa: E402
from app.services.bootstrap import ensure_dev_workspace  # noqa: E402

#: Every organization this script owns starts with this. `--reset` uses it to
#: find exactly its own data and nothing else.
ORG_SLUG_PREFIX = "benchmark-"

PROJECT_NAME = "Hyperlocal benchmark"

#: Namespace for deterministic ids. Seeding twice must produce the same
#: direction and specification ids, or "idempotent" is not true.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "campaign-os.benchmark")


def stable_id(*parts: str) -> uuid.UUID:
    """A deterministic UUID for a dataset key."""
    return uuid.uuid5(NAMESPACE, ":".join(parts))


def say(stage: str, message: str) -> None:
    print(f"  {stage:<12} {message}", flush=True)


def _require_mocks(settings: Settings) -> None:
    live = {
        "LLM_PROVIDER": settings.llm_provider,
        "IMAGE_PROVIDER": settings.image_provider,
        "EMBEDDING_PROVIDER": settings.embedding_provider,
    }
    offenders = [f"{k}={v}" for k, v in live.items() if v != "mock"]
    if offenders:
        raise SystemExit(
            "seed_benchmark refuses to run against a live provider: "
            + ", ".join(offenders)
            + "\nThis dataset is hand-written and needs no provider at all. "
            "Set these to `mock` and re-run."
        )


# --------------------------------------------------------------------------
# Teardown
# --------------------------------------------------------------------------
async def drop(session: AsyncSession) -> int:
    """Delete every benchmark organization's content.

    Scoped by the organization slug prefix, so a developer's own work — and
    the Milestone 10 demo, which lives in a different organization — survives
    untouched. The organizations themselves are kept: they are cheap, their
    ids stay stable across reseeds, and deleting them would take the
    memberships with them for no benefit.
    """
    orgs = (
        (
            await session.execute(
                select(Organization).where(Organization.slug.startswith(ORG_SLUG_PREFIX))
            )
        )
        .scalars()
        .all()
    )
    if not orgs:
        return 0
    org_ids = [o.id for o in orgs]

    # Campaigns first: the cascade runs from the campaign down, and a brand
    # delete would otherwise be blocked by its campaigns' restrict FKs.
    await session.execute(delete(CampaignRow).where(CampaignRow.organization_id.in_(org_ids)))
    await session.execute(
        delete(BrandProfileRow).where(BrandProfileRow.organization_id.in_(org_ids))
    )
    await session.execute(delete(Project).where(Project.organization_id.in_(org_ids)))
    await session.commit()
    return len(orgs)


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
async def _organization(session: AsyncSession, company: BenchmarkCompany) -> Organization:
    """This company's tenant, created once and found thereafter."""
    slug = company.organization_slug
    existing = (
        (await session.execute(select(Organization).where(Organization.slug == slug)))
        .scalars()
        .first()
    )
    if existing is not None:
        return existing
    return await create_organization(session, name=company.display_name, slug=slug)


async def _campaign(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    brand_id: uuid.UUID,
    project_id: uuid.UUID,
    company: BenchmarkCompany,
    entry: BenchmarkCampaign,
) -> uuid.UUID:
    """One campaign, through the governed part of the pipeline.

    Campaign Specification -> Creative Directions (Gate 1 approved) ->
    Creative Specification (Gate 2 approved). Every write goes through an
    organization-scoped repository, so the seed exercises the same tenancy
    checks a request would.
    """
    campaigns = CampaignRepository(session, organization_id)
    campaign_row = await campaigns.create(
        brand_id=brand_id,
        title=entry.brief.title,
        project_id=project_id,
        created_by=user_id,
    )

    # 1. The Campaign Specification — the source of truth (CLAUDE.md §3.1).
    specs = CampaignSpecificationRepository(session, organization_id)
    brief = entry.brief.model_copy(update={"campaign_id": str(campaign_row.id)})
    spec_row = await specs.create_version(
        campaign_id=campaign_row.id, payload=brief.model_dump(mode="json")
    )
    await specs.confirm(spec_row, user_id=user_id)

    # 2. Creative Directions, with Gate 1 already decided.
    directions = [
        d.model_copy(update={"campaign_id": str(campaign_row.id)}) for d in entry.directions
    ]
    selected = next(d for d in directions if d.ordinal == entry.selected_direction_ordinal)
    selected_uuid = stable_id(company.slug, entry.slug, "direction", str(selected.ordinal))

    direction_sets = CreativeDirectionSetRepository(session, organization_id)
    await direction_sets.upsert_version(
        campaign_id=campaign_row.id,
        version=1,
        payload={
            "campaign_id": str(campaign_row.id),
            "version": 1,
            "directions": [d.model_dump(mode="json") for d in directions],
            "recommended_ordinal": entry.selected_direction_ordinal,
            "recommendation_reasons": [
                f"Selected for the benchmark: {selected.distinctness_note or selected.title}"
            ],
        },
        selected_direction_id=selected_uuid,
    )

    # 3. The Creative Specification, with Gate 2 already decided.
    creative_specs = CreativeSpecificationRepository(session, organization_id)
    specification = entry.specification.model_copy(
        update={"campaign_id": str(campaign_row.id), "direction_id": str(selected_uuid)}
    )
    creative_row = await creative_specs.upsert_version(
        campaign_id=campaign_row.id,
        version=1,
        direction_id=selected_uuid,
        payload=specification.model_dump(mode="json"),
    )
    await creative_specs.approve(creative_row, user_id=user_id)

    # Stops here deliberately. Generation onward is computed by services from
    # real provider output; seeding it would be inventing results.
    #
    # `CampaignRecordStatus` is the row's own vocabulary, distinct from the
    # graph's `CampaignStatus`. The database check constraint is generated
    # from this same enum, so this cannot drift.
    await campaigns.set_status(campaign_row, CampaignRecordStatus.SPECIFICATION_CONFIRMED.value)
    return campaign_row.id


async def build_company(
    session: AsyncSession, company: BenchmarkCompany, user_id: uuid.UUID
) -> tuple[uuid.UUID, int]:
    """One company in its own organization. Returns (organization id, campaigns)."""
    organization = await _organization(session, company)
    await session.flush()

    memberships = MembershipRepository(session)
    if await memberships.role_in(user_id, organization.id) is None:
        await memberships.grant(
            user_id=user_id, organization_id=organization.id, role=Role.ADMIN.value
        )

    projects = ProjectRepository(session, organization.id)
    project = await projects.create(
        name=PROJECT_NAME,
        description=f"Synthetic benchmark campaigns for {company.display_name} (fictional).",
        created_by=user_id,
    )

    brands = BrandRepository(session, organization.id)
    profile = company.brand.model_copy(update={"organization_id": str(organization.id)})
    brand_row = await brands.create(
        name=company.brand.name,
        payload=profile.model_dump(mode="json"),
        created_by=user_id,
    )

    for entry in company.campaigns:
        await _campaign(
            session,
            organization_id=organization.id,
            user_id=user_id,
            brand_id=brand_row.id,
            project_id=project.id,
            company=company,
            entry=entry,
        )

    await session.commit()
    return organization.id, len(company.campaigns)


async def already_seeded(session: AsyncSession) -> bool:
    stmt = select(Organization).where(Organization.slug.startswith(ORG_SLUG_PREFIX))
    return (await session.execute(stmt)).scalars().first() is not None


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset", action="store_true", help="delete the benchmark data, then rebuild"
    )
    args = parser.parse_args()

    settings = get_settings()
    _require_mocks(settings)

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        if args.reset:
            removed = await drop(session)
            say("reset", f"cleared {removed} benchmark organization(s)")
        elif await already_seeded(session):
            print(
                "Benchmark data is already present. Use --reset to rebuild.\nNothing was changed."
            )
            return 0

        # One identity across all three organizations, with a separate
        # membership in each. That is what makes the isolation test real: the
        # same user, scoped differently, must not see across the boundary.
        user, _ = await ensure_dev_workspace(session, settings)
        await session.commit()

        total = 0
        for company in COMPANIES:
            organization_id, campaigns = await build_company(session, company, user.id)
            say(
                company.size.value,
                f"{company.display_name} ({company.market.city}) — "
                f"{campaigns} campaigns, org {organization_id}",
            )
            total += campaigns

    print(f"\ndone. {len(COMPANIES)} organizations, {total} campaigns.")
    print("Every company in this dataset is fictional.")
    print("See docs/HYPERLOCAL_BENCHMARK.md for the methodology.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
