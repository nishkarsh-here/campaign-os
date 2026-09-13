"""Build the canonical demo campaign, end to end, from real services.

    uv run python scripts/seed_demo.py          # build (skips if it exists)
    uv run python scripts/seed_demo.py --reset  # delete and rebuild
    uv run python scripts/seed_demo.py --drop   # delete only

**Everything here goes through the same services the API calls.** The
interview really runs, the directions are really generated and checked for
distinctness, the prompts are really compiled, the evaluator really scores, the
Guardian really checks, the revision really produces v2, and the renderer
really composes the final assets. Nothing writes a fabricated result into a
table that a service is supposed to compute.

That matters for two reasons. A dataset stuffed in by hand drifts the moment a
service changes, and the first person to notice is whoever is presenting. And a
seeded "evaluation" nobody computed is exactly the fake functionality this
project has refused to build since Milestone 0.

**Mock providers only.** The script refuses to run against a live provider: a
demo dataset is not worth someone's API credit, and the point of the demo path
is that it cannot be broken by a dead key or a conference network.

The images are generated here with Pillow rather than committed as binaries, so
the repository stays text and the seed stays reproducible.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.db.models import (  # noqa: E402
    BrandProfileRow,
    CampaignRow,
    Organization,
    Project,
    User,
)
from app.db.session import build_sessionmaker  # noqa: E402
from app.domain.approval import Decision  # noqa: E402
from app.domain.common import Channel, JobStatus, Role  # noqa: E402
from app.domain.workspace import Principal  # noqa: E402
from app.domain.workspace import User as PrincipalUser  # noqa: E402
from app.providers.base import (  # noqa: E402
    EmbeddingProvider,
    LLMProvider,
    StorageProvider,
)
from app.providers.registry import (  # noqa: E402
    build_embedding_provider,
    build_llm_provider,
    build_storage_provider,
)
from app.services.bootstrap import ensure_dev_workspace  # noqa: E402
from app.services.campaigns import CampaignDiscoveryService, ensure_checkpoint_tables  # noqa: E402
from app.services.composition_stage import CompositionService  # noqa: E402
from app.services.creative_stage import CreativeStageService  # noqa: E402
from app.services.evaluation_stage import EvaluationService  # noqa: E402
from app.services.generation import GenerationService  # noqa: E402
from app.services.revision_stage import RevisionStageService  # noqa: E402

# --------------------------------------------------------------------------
# The demo content
# --------------------------------------------------------------------------
#: Marks everything this script owns, so `--reset` can delete exactly what it
#: created and nothing a human made alongside it.
DEMO_BRAND = "Northline Facades"
DEMO_CAMPAIGN = "FS-9 Facade Launch"
DEMO_PROJECT = "Demo campaigns"

BRAND_FIELDS = {
    "name": DEMO_BRAND,
    "positioning": (
        "Engineered facade systems for architects who specify for a 40-year life, "
        "not a 10-year warranty."
    ),
    "audience_description": (
        "Architects, facade consultants and specification writers on commercial "
        "projects in India and the Gulf."
    ),
    "tagline": "Built to outlast the building it clads.",
}

#: Brand knowledge the Brain ingests, chunks, embeds and extracts facts from.
BRAND_DOCUMENT = """\
Northline Facades — brand and communication guidelines (extract)

Positioning
Northline makes engineered facade systems for commercial architecture. We sell
to people who read a technical datasheet before they look at a render. Our
promise is longevity that is demonstrable, not asserted.

Voice
Precise, calm, technical without being cold. We describe what a system does and
what it has been tested to. We never use superlatives we cannot evidence.

Colour
Graphite #1F2933 is the primary. Ember #E4572E is the accent and is used
sparingly — a single accent per composition. Paper #F7F7F5 is the light ground.

Typography
Headlines set tight and large. Body copy generous. Never centre long copy.

Prohibited claims
Do not describe any product as indestructible, maintenance-free, or permanent.
Do not claim compliance with a standard the specific system has not been tested
against. Do not use the word "guaranteed" without the warranty term beside it.

Products
FS-9 is the unitised aluminium rainscreen system. Tested to 2,400 Pa wind load.
Available in anodised and PVDF finishes. Specified on projects up to 28 storeys.
"""

#: What the interviewer is told, keyed by the field it asks about.
#:
#: Keyed rather than ordered because the reply *is* the field value — the
#: interviewer asks about `key_message` and whatever comes back becomes the key
#: message. Answering "The key message is that it is built to last" would put
#: those seven meta words on the poster, which is exactly the kind of detail
#: that makes a demo look broken. So every answer here is phrased as the value
#: itself, and looking them up by field keeps that true if the question order
#: ever changes.
INTERVIEW_ANSWERS: dict[str, str] = {
    "campaign_objective": (
        "Get FS-9 specified at design stage by architects working on commercial towers."
    ),
    "target_audience": "Architects and facade consultants in Mumbai.",
    "product": "FS-9 unitised aluminium rainscreen facade system.",
    "key_message": "Built to outlast the building it clads.",
    "cta": "Request the specification pack",
    "region": "Mumbai, Maharashtra, India.",
    "channels": "Instagram and LinkedIn.",
    "campaign_tone": "Technical, confident, never salesy.",
    "tone": "Technical, confident, never salesy.",
    "key_offer": "A full FS-9 specification pack, including wind-load test data.",
    "desired_emotional_response": "Confidence that this will still look right in twenty years.",
    "timing_occasion": "This quarter, ahead of the design season.",
    "market_context": "Commercial towers in Mumbai, where facade longevity is under scrutiny.",
    "reference_style": "Orthographic, hard light, one accent colour.",
    "required_elements": "The FS-9 name and the wind-load figure.",
    "avoid_restrictions": "No stock photography, no people shaking hands.",
    "constraints": "No stock photography, no people shaking hands.",
    "brand_requirements": "Graphite ground with a single ember accent.",
    "visual_preferences": "Technical and minimal.",
    "budget_note": "Not decided yet.",
    "deadline": "End of this quarter.",
    "language": "English.",
}

#: For a field with no scripted answer. Better than a blank: the interviewer
#: treats an empty reply as an error, and a demo should not depend on this
#: dictionary staying exhaustive forever.
DEFAULT_ANSWER = "Not decided yet — treat that as unknown for now."

#: The edits a human makes on the specification screen before confirming.
#:
#: The interview has a turn budget and stops when it has enough to proceed —
#: which is correct behaviour, and leaves a few fields thin. Rather than
#: pretending otherwise, the seed does what a person does: it opens the
#: specification and fixes them. These go through `update_specification`, so
#: they are marked `edited_by_human` and recompilation cannot overwrite them —
#: which is itself worth showing.
SPECIFICATION_EDITS: dict[str, object] = {
    "title": "FS-9 facade launch — Mumbai",
    "audience": "Architects and facade consultants specifying commercial towers in Mumbai.",
    "audience_insight": (
        "They are judged on a building that has to still look right in twenty years, "
        "so longevity evidence beats aesthetics in the first conversation."
    ),
    "cta": "Request the specification pack",
    "region": "Mumbai, Maharashtra, India",
    "channels": ["instagram_post", "instagram_story", "linkedin"],
    "supporting_messages": [
        "Tested to 2,400 Pa wind load.",
        "Specified on projects up to 28 storeys.",
    ],
    "success_criteria": ["Specification pack requests from named practices."],
}

#: The feedback that drives the seeded revision, so the demo has real history.
REVISION_FEEDBACK = "Everything is good except the environment — make it feel more local to Mumbai."

#: Channels the demo ships final assets for.
DEMO_CHANNELS = (Channel.INSTAGRAM_POST, Channel.INSTAGRAM_STORY, Channel.LINKEDIN)


# --------------------------------------------------------------------------
# Generated imagery (deterministic, so the demo looks the same every time)
# --------------------------------------------------------------------------
def logo_png() -> bytes:
    """A wordmark. Generated rather than committed, and never a stand-in for a
    real brand's mark — this brand is fictional."""
    image = Image.new("RGBA", (640, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.text((8, 34), "NORTHLINE", font=ImageFont.load_default(size=104), fill=(255, 255, 255))
    draw.rectangle([10, 168, 520, 180], fill=(228, 87, 46, 255))
    return _png(image)


def reference_png(index: int) -> bytes:
    """A reference image with a distinct composition, so the style analyser has
    something real to describe and the three references are not identical."""
    palettes = [((31, 41, 51), (228, 87, 46)), ((247, 247, 245), (31, 41, 51))]
    ground, accent = palettes[index % len(palettes)]
    image = Image.new("RGB", (1024, 1024), ground)
    draw = ImageDraw.Draw(image)
    if index % 3 == 0:
        for x in range(0, 1024, 128):
            draw.rectangle([x, 200, x + 64, 900], fill=accent)
    elif index % 3 == 1:
        draw.ellipse([180, 180, 844, 844], fill=accent)
    else:
        draw.polygon([(120, 900), (512, 160), (904, 900)], fill=accent)
    return _png(image)


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# --------------------------------------------------------------------------
@dataclass
class Seeded:
    organization_id: uuid.UUID
    brand_id: uuid.UUID
    campaign_id: uuid.UUID
    final_assets: int


def _principal(user: User, organization: Organization) -> Principal:
    return Principal(
        user=PrincipalUser(id=str(user.id), email=user.email),
        organization_id=str(organization.id),
        role=Role.ADMIN,
    )


def _require_mocks(settings: Settings) -> None:
    live = {
        "LLM_PROVIDER": settings.llm_provider,
        "IMAGE_PROVIDER": settings.image_provider,
        "EMBEDDING_PROVIDER": settings.embedding_provider,
    }
    offenders = [f"{k}={v}" for k, v in live.items() if v != "mock"]
    if offenders:
        raise SystemExit(
            "seed_demo refuses to run against a live provider: "
            + ", ".join(offenders)
            + "\nThe demo dataset is not worth API credit. Set these to `mock` and re-run."
        )


# --------------------------------------------------------------------------
# Teardown
# --------------------------------------------------------------------------
async def drop(session: AsyncSession, organization_id: uuid.UUID) -> int:
    """Delete the demo brand and everything that hangs off it.

    Scoped to the demo brand by name rather than truncating tables, so a
    developer's own work in the same organization survives a `--reset`.
    """
    brands = (
        (
            await session.execute(
                select(BrandProfileRow).where(
                    BrandProfileRow.organization_id == organization_id,
                    BrandProfileRow.name == DEMO_BRAND,
                )
            )
        )
        .scalars()
        .all()
    )
    if not brands:
        return 0
    ids = [b.id for b in brands]
    # Campaigns first: the cascade runs from the campaign down, and a brand
    # delete would otherwise be blocked by its campaigns' restrict FKs.
    await session.execute(delete(CampaignRow).where(CampaignRow.brand_profile_id.in_(ids)))
    await session.execute(delete(BrandProfileRow).where(BrandProfileRow.id.in_(ids)))
    await session.commit()
    return len(ids)


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
async def build(session: AsyncSession, settings: Settings) -> Seeded:
    user, organization = await ensure_dev_workspace(session, settings)
    await session.commit()
    principal = _principal(user, organization)
    organization_id = organization.id

    storage = build_storage_provider(settings)
    llm = build_llm_provider(settings)
    embeddings = build_embedding_provider(settings)

    project = await _project(session, organization_id)

    say("brand", "creating the brand and its Brand Brain")
    brand_id = await _brand(session, principal, settings, storage, llm, embeddings)

    say("campaign", "running the discovery interview")
    campaign_id = await _campaign(
        session, principal, settings, storage, llm, embeddings, brand_id, project.id
    )

    say("references", "analysing reference images and saving preferences")
    await _references(session, principal, settings, storage, llm, embeddings, campaign_id)

    say("creative", "generating directions and passing both human gates")
    await _creative(session, principal, settings, storage, llm, embeddings, campaign_id)

    say("generation", "compiling prompts and generating plates")
    await _generate(session, principal, settings, storage, llm, embeddings, campaign_id)

    say("evaluation", "scoring the plates and selecting one")
    await _evaluate(session, principal, settings, storage, llm, embeddings, campaign_id)

    say("guardian", "running brand checks and one full revision round")
    await _revise(session, principal, settings, storage, llm, embeddings, campaign_id)

    say("generation", "regenerating from the revised specification")
    await _generate(session, principal, settings, storage, llm, embeddings, campaign_id)

    say("evaluation", "re-evaluating against v2 and selecting the winner")
    await _evaluate(
        session, principal, settings, storage, llm, embeddings, campaign_id, prefer_version=2
    )

    say("guardian", "brand-checking the revised creatives")
    await _check(session, principal, settings, storage, llm, embeddings, campaign_id)

    say("composition", "composing and rendering the final assets")
    rendered = await _compose(session, principal, settings, storage, campaign_id)

    return Seeded(
        organization_id=organization_id,
        brand_id=brand_id,
        campaign_id=campaign_id,
        final_assets=rendered,
    )


async def _project(session: AsyncSession, organization_id: uuid.UUID) -> Project:
    from app.repositories.projects import ProjectRepository

    repo = ProjectRepository(session, organization_id)
    for row in (await repo.list_page(limit=50)).items:
        if row.name == DEMO_PROJECT:
            return row
    row = await repo.create(
        name=DEMO_PROJECT, description="Seeded demonstration data.", created_by=None
    )
    await session.commit()
    return row


async def _brand(
    session: AsyncSession,
    principal: Principal,
    settings: Settings,
    storage: StorageProvider,
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
) -> uuid.UUID:
    """Brand, logo, guidelines document, and the facts a human accepted."""
    from app.domain.brand import FactStatus
    from app.repositories.brands import BrandAssetRepository, BrandFactRepository
    from app.services.brand_documents import BrandDocumentService
    from app.services.brands import BrandService
    from app.services.uploads import storage_key_for

    organization_id = uuid.UUID(principal.organization_id)
    brands = BrandService(session, principal)
    brand = await brands.create(BRAND_FIELDS)
    brand_id = uuid.UUID(brand.id)

    # The palette and the prohibited claims are brand truth a human confirmed,
    # so they are written as confirmed fields rather than left as proposals.
    await brands.update(
        brand_id,
        {
            "colors": [
                {"name": "Graphite", "hex": "#1F2933", "role": "primary"},
                {"name": "Ember", "hex": "#E4572E", "role": "accent"},
                {"name": "Paper", "hex": "#F7F7F5", "role": "neutral"},
            ],
            "prohibited_claims": ["indestructible", "maintenance-free", "permanent"],
            "voice": {
                "tone_attributes": ["precise", "calm", "technical"],
                "person": "first person plural",
                "writing_rules": ["Describe what a system does and what it was tested to."],
                "avoid": ["superlatives", "hype", "exclamation marks"],
            },
            "products": [
                {
                    "name": "FS-9",
                    "category": "Unitised aluminium rainscreen system",
                    "description": "Tested to 2,400 Pa wind load; anodised and PVDF finishes.",
                    "key_features": ["2,400 Pa wind load", "unitised installation"],
                    "differentiators": ["specified on projects up to 28 storeys"],
                }
            ],
        },
    )
    await session.commit()

    key = storage_key_for(
        organization_id=organization_id, brand_id=brand_id, kind="assets", extension="png"
    )
    data = logo_png()
    await storage.put(key, data, mime_type="image/png")
    assets = BrandAssetRepository(session, organization_id)
    await assets.create(
        brand_id=brand_id,
        kind="logo",
        storage_key=key,
        filename="northline-logo.png",
        mime_type="image/png",
        size_bytes=len(data),
    )
    await session.commit()

    documents = BrandDocumentService(
        session, organization_id, storage=storage, llm=llm, embeddings=embeddings
    )
    document = await documents.create_text_document(
        brand_id=brand_id, title="Brand and communication guidelines", content=BRAND_DOCUMENT
    )
    await session.commit()
    await documents.process(document.id)
    await session.commit()

    # Accept every proposal, so the demo's Brand Brain is confirmed knowledge
    # rather than a queue of things nobody decided.
    facts = BrandFactRepository(session, organization_id)
    accepted = 0
    for fact in await facts.list_for_brand(brand_id, status=FactStatus.PROPOSED.value):
        await facts.set_status(fact, FactStatus.ACCEPTED.value)
        accepted += 1
    await session.commit()
    say("brand", f"accepted {accepted} extracted brand facts")
    return brand_id


async def _campaign(
    session: AsyncSession,
    principal: Principal,
    settings: Settings,
    storage: StorageProvider,
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    brand_id: uuid.UUID,
    project_id: uuid.UUID,
) -> uuid.UUID:
    service = CampaignDiscoveryService(
        session, principal, settings=settings, llm=llm, embeddings=embeddings
    )
    campaign = await service.create(brand_id=brand_id, title=DEMO_CAMPAIGN, project_id=project_id)
    await session.commit()

    turn = await service.start(campaign.id)
    await session.commit()
    # Bounded by the interview budget rather than by the answer list, so a
    # question this script has no answer for cannot spin forever.
    for _ in range(settings.max_interview_turns + 2):
        if turn.interview_complete or turn.question is None:
            break
        reply = INTERVIEW_ANSWERS.get(turn.question.field, DEFAULT_ANSWER)
        turn = await service.answer(campaign.id, reply)
        await session.commit()

    if turn.specification is None:
        raise SystemExit(
            "The interview did not produce a Campaign Specification. "
            "The demo cannot be seeded from a half-finished discovery."
        )

    edited = await service.update_specification(campaign.id, dict(SPECIFICATION_EDITS))
    await session.commit()
    say("campaign", f"human edits applied — specification v{edited.version}")

    await service.confirm_specification(campaign.id)
    await session.commit()
    say("campaign", f"specification confirmed after {turn.turn} turns")
    return campaign.id


async def _references(
    session: AsyncSession,
    principal: Principal,
    settings: Settings,
    storage: StorageProvider,
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    campaign_id: uuid.UUID,
) -> None:
    from app.domain.common import StyleFamily
    from app.domain.reference import CreativePreferences
    from app.repositories.campaigns import CampaignReferenceRepository
    from app.services.creative_context import CreativeContextService
    from app.services.reference_intelligence import ReferenceIntelligenceService
    from app.services.uploads import storage_key_for

    organization_id = uuid.UUID(principal.organization_id)
    references = CampaignReferenceRepository(session, organization_id)
    notes = [
        "The rhythm of the bays is the whole idea.",
        "One accent colour, nothing else.",
        "Hard light, no atmosphere.",
    ]
    reference_ids: list[str] = []
    for index, note in enumerate(notes):
        data = reference_png(index)
        key = storage_key_for(
            organization_id=organization_id,
            brand_id=campaign_id,
            kind="references",
            extension="png",
        )
        await storage.put(key, data, mime_type="image/png")
        row = await references.create(
            campaign_id=campaign_id,
            storage_key=key,
            filename=f"reference-{index + 1}.png",
            mime_type="image/png",
            size_bytes=len(data),
            note=note,
            content_sha256=None,
        )
        reference_ids.append(str(row.id))
    await session.commit()

    intelligence = ReferenceIntelligenceService(session, organization_id, storage=storage, llm=llm)
    analysed = await intelligence.analyze_campaign(campaign_id)
    await session.commit()
    say("references", f"analysed {len(analysed)} references")

    context = CreativeContextService(
        session, organization_id, storage=storage, llm=llm, embeddings=embeddings
    )
    campaign = await session.get(CampaignRow, campaign_id)
    assert campaign is not None
    await context.save_preferences(
        campaign,
        CreativePreferences(
            selected_styles=[StyleFamily.TECHNICAL, StyleFamily.MINIMAL],
            liked_reference_ids=reference_ids[:2],
            disliked_reference_ids=[],
            color_preference=["graphite ground", "one ember accent"],
            avoid=["stock photography", "people shaking hands"],
            free_text="Should look like a datasheet that happens to be beautiful.",
        ),
    )
    await session.commit()


async def _creative(
    session: AsyncSession,
    principal: Principal,
    settings: Settings,
    storage: StorageProvider,
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    campaign_id: uuid.UUID,
) -> None:
    service = CreativeStageService(
        session, principal, settings=settings, llm=llm, embeddings=embeddings, storage=storage
    )
    turn = await service.start(campaign_id)
    await session.commit()

    if turn.gate == "strategy_gate":
        assert turn.direction_set is not None
        ordinal = turn.direction_set.recommended_ordinal
        directions = turn.direction_set.directions
        chosen = directions[ordinal - 1].id if ordinal else directions[0].id
        turn = await service.decide_strategy(
            campaign_id, decision=Decision.APPROVE, direction_id=chosen, feedback=None
        )
        await session.commit()

    if turn.gate == "specification_gate":
        turn = await service.decide_specification(
            campaign_id, decision=Decision.APPROVE, feedback=None
        )
        await session.commit()

    if not turn.approved:
        raise SystemExit("The creative stage did not reach an approved specification.")
    say("creative", "Creative Specification v1 approved")


async def _generate(
    session: AsyncSession,
    principal: Principal,
    settings: Settings,
    storage: StorageProvider,
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    campaign_id: uuid.UUID,
) -> None:
    service = GenerationService(
        session, principal, settings=settings, storage=storage, llm=llm, embeddings=embeddings
    )
    await service.compile_prompts(campaign_id)
    await session.commit()
    view, _batch = await service.start(campaign_id)
    await session.commit()
    batch = view.batch
    pending = [
        uuid.UUID(job.id)
        for job in (batch.jobs if batch else [])
        if job.status in (JobStatus.PENDING, JobStatus.RUNNING)
    ]
    # Sequential on one session, deliberately: `run_batch_in_background` opens a
    # session per job because gathered tasks cannot share one (ADR-012), and a
    # script has no reason to introduce that concurrency.
    await service.run_jobs(pending)
    await session.commit()
    done = await service.current(campaign_id)
    say("generation", done.batch.outcome() if done.batch else "no batch")


async def _evaluate(
    session: AsyncSession,
    principal: Principal,
    settings: Settings,
    storage: StorageProvider,
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    campaign_id: uuid.UUID,
    *,
    prefer_version: int | None = None,
) -> None:
    service = EvaluationService(
        session, principal, settings=settings, storage=storage, llm=llm, embeddings=embeddings
    )
    _view, claimed = await service.start(campaign_id)
    await session.commit()
    await service.run_evaluations(claimed)
    await session.commit()

    summary = (await service.current(campaign_id)).summary
    recommended = summary.recommendation.generated_asset_id if summary.recommendation else None
    target = recommended or (summary.ranked[0].generated_asset_id if summary.ranked else None)
    if prefer_version is not None:
        # After a revision a person selects from what the revision produced —
        # they just asked for the change. The ranking is advice across every
        # asset; this narrows it to the current plan's assets and still takes
        # the best one, rather than overriding the evaluator's order.
        newest = await _assets_for_version(session, campaign_id, prefer_version)
        ranked_newest = [r for r in summary.ranked if r.generated_asset_id in newest]
        if ranked_newest:
            target = ranked_newest[0].generated_asset_id
    say("evaluation", summary.outcome())
    if target:
        await service.select(campaign_id, asset_id=uuid.UUID(target), note="Seeded selection.")
        await session.commit()
        say("evaluation", f"selected asset {target[:8]}…")


async def _assets_for_version(
    session: AsyncSession, campaign_id: uuid.UUID, version: int
) -> set[str]:
    """Which generated assets came from a given Creative Specification version."""
    from app.db.models import GeneratedAssetRow

    rows = (
        (
            await session.execute(
                select(GeneratedAssetRow.id).where(
                    GeneratedAssetRow.campaign_id == campaign_id,
                    GeneratedAssetRow.specification_version == version,
                )
            )
        )
        .scalars()
        .all()
    )
    return {str(row) for row in rows}


async def _check(
    session: AsyncSession,
    principal: Principal,
    settings: Settings,
    storage: StorageProvider,
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    campaign_id: uuid.UUID,
) -> None:
    """Run the Brand Guardian over every creative that has not been checked.

    Called again after regeneration, because that is what a person does: a
    revised creative that nobody brand-checked is not approved, and the
    overview says so rather than inheriting the old verdict.
    """
    service = RevisionStageService(
        session, principal, settings=settings, storage=storage, llm=llm, embeddings=embeddings
    )
    view, claimed = await service.start_guardian(campaign_id, asset_ids=None)
    await session.commit()
    await service.run_guardian_checks(claimed)
    await session.commit()
    say("guardian", f"{len(view.results)} brand checks completed")


async def _revise(
    session: AsyncSession,
    principal: Principal,
    settings: Settings,
    storage: StorageProvider,
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    campaign_id: uuid.UUID,
) -> None:
    service = RevisionStageService(
        session, principal, settings=settings, storage=storage, llm=llm, embeddings=embeddings
    )
    await _check(session, principal, settings, storage, llm, embeddings, campaign_id)

    await service.propose_revision(campaign_id, feedback=REVISION_FEEDBACK, source_asset_id=None)
    await session.commit()
    await service.approve_delta(campaign_id)
    await session.commit()
    await service.approve_revised_specification(campaign_id)
    await session.commit()
    say("revision", "Creative Specification v2 approved; v1 untouched")


async def _compose(
    session: AsyncSession,
    principal: Principal,
    settings: Settings,
    storage: StorageProvider,
    campaign_id: uuid.UUID,
) -> int:
    service = CompositionService(session, principal, settings=settings, storage=storage)
    rendered = 0
    base = DEMO_CHANNELS[0]
    await service.compose(campaign_id, channel=base)
    await session.commit()
    for channel in DEMO_CHANNELS:
        if channel is not base:
            await service.add_variant(campaign_id, channel=channel, source=base)
            await session.commit()
        asset = await service.render_final(campaign_id, channel=channel)
        await session.commit()
        rendered += 1
        say("composition", f"{channel.value} v{asset.version} · {asset.width}x{asset.height}")
    return rendered


def say(stage: str, message: str) -> None:
    print(f"  {stage:<12} {message}", flush=True)


# --------------------------------------------------------------------------
async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="delete the demo data, then rebuild")
    parser.add_argument("--drop", action="store_true", help="delete the demo data and stop")
    args = parser.parse_args()

    settings = get_settings()
    _require_mocks(settings)
    # Three plates per round rather than the production default of one. A
    # ranking of one asset is not a ranking, and the evaluation and
    # recommendation screens are a large part of what the demo is showing.
    settings = settings.model_copy(update={"generation_images_per_job": 3})
    await ensure_checkpoint_tables(settings)

    factory = build_sessionmaker(settings)
    async with factory() as session:
        user, organization = await ensure_dev_workspace(session, settings)
        await session.commit()

        if args.reset or args.drop:
            removed = await drop(session, organization.id)
            print(f"removed {removed} demo brand(s) and everything under them")
            if args.drop:
                return 0

        existing = (
            await session.execute(
                select(BrandProfileRow).where(
                    BrandProfileRow.organization_id == organization.id,
                    BrandProfileRow.name == DEMO_BRAND,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            print(f"demo data already present (brand {existing.id}). Use --reset to rebuild.")
            return 0

        print(f"seeding the demo campaign as {user.email} in {organization.slug}\n")
        seeded = await build(session, settings)

    print(
        "\ndone."
        f"\n  organization  {seeded.organization_id}"
        f"\n  brand         {seeded.brand_id}"
        f"\n  campaign      {seeded.campaign_id}"
        f"\n  final assets  {seeded.final_assets}"
        f"\n\nopen  http://localhost:3000/app/campaigns/{seeded.campaign_id}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
