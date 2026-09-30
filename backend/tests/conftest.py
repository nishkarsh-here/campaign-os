"""Test session setup.

Every test runs offline against mock providers (TESTING.md). The environment is
set before anything imports `app.config`, and `Settings` itself refuses a live
provider under `APP_ENV=test` — so this cannot be bypassed by accident.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "test")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["IMAGE_PROVIDER"] = "mock"
os.environ["EMBEDDING_PROVIDER"] = "mock"
os.environ["STORAGE_PROVIDER"] = "local"
os.environ["SEARCH_PROVIDER"] = "none"
# Checkpoint deserialization is allowlisted (app/graph/serde.py); strict mode
# turns an unregistered domain type into a test failure, not a silent risk.
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"

import pytest  # noqa: E402


def production_settings(**overrides: object):
    """A `Settings` that `APP_ENV=production` actually accepts.

    Production refuses more than missing credentials: a database URL still on
    localhost, wildcard or plaintext CORS, and `DEMO_MODE` are each a deploy
    that comes up looking healthy (`Settings._refuse_unsafe_production`). Tests
    about *one* production guard were building the rest by default and tripping
    over the others, so the shape lives here once.

    Nothing reaches a network: the hosts are fictional and every provider is
    mock.
    """
    from app.config import Settings

    base: dict[str, object] = {
        "app_env": "production",
        "database_url": "postgresql+asyncpg://user@db.example.com:5432/campaign_os",
        "database_url_sync": "postgresql://user@db.example.com:5432/campaign_os",
        "cors_origins": "https://app.example.com",
        "media_url_secret": "test-signing-key",
        "llm_provider": "mock",
        "image_provider": "mock",
        "embedding_provider": "mock",
        "storage_provider": "local",
        "search_provider": "none",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


from app.domain import (  # noqa: E402
    BrandColor,
    BrandProfile,
    CampaignBrief,
    Channel,
    CreativeDirection,
    CreativeSpecification,
    StyleFamily,
)


@pytest.fixture
def brand() -> BrandProfile:
    return BrandProfile(
        id="brand-1",
        organization_id="org-1",
        name="Northline Materials",
        positioning="Engineered building materials for architects who specify for the long term.",
        colors=[
            BrandColor(name="Graphite", hex="#1F2933", role="primary"),
            BrandColor(name="Signal", hex="#E4572E", role="accent"),
        ],
        preferred_styles=[StyleFamily.PREMIUM, StyleFamily.TECHNICAL],
        approved_claims=["Tested to IS 456 standards"],
        prohibited_claims=["indestructible", "lifetime guarantee"],
    )


@pytest.fixture
def brief() -> CampaignBrief:
    return CampaignBrief(
        campaign_id="camp-1",
        title="Premium launch — Maharashtra architects",
        objective="Establish the new façade system as the premium specification choice.",
        audience="Practising architects and specifiers in Maharashtra",
        product="Northline FS-9 façade system",
        key_message="Engineered to outlast the building it clads.",
        cta="Request a specification pack",
        channels=[Channel.INSTAGRAM_POST, Channel.LINKEDIN],
        region="Maharashtra, India",
        tone=["modern", "trustworthy"],
    )


@pytest.fixture
def direction() -> CreativeDirection:
    return CreativeDirection(
        campaign_id="camp-1",
        ordinal=1,
        title="Built to Outlast",
        big_idea="The building ages; the façade does not.",
        strategic_rationale="Speaks to specifiers' real fear: callbacks a decade later.",
        emotional_angle="Quiet confidence",
        headline="Specified once. Standing decades.",
        cta="Request a specification pack",
        visual_metaphor="Weathered context against an unweathered façade",
        composition="Low angle, façade filling two thirds of frame",
        subject="A completed façade on a Pune office building",
        environment="Late monsoon light, wet street below",
        lighting="Directional late-afternoon sun, long shadows",
        brand_integration="Graphite and signal-orange accent in the built environment",
        product_integration="The façade system is the hero, shown in situ",
    )


@pytest.fixture
def specification(direction: CreativeDirection) -> CreativeSpecification:
    return CreativeSpecification(
        campaign_id="camp-1",
        direction_id=direction.id,
        concept=direction.big_idea,
        emotional_angle=direction.emotional_angle,
        headline=direction.headline,
        cta=direction.cta,
        visual_metaphor=direction.visual_metaphor,
        composition=direction.composition,
        subject=direction.subject,
        environment=direction.environment,
        lighting=direction.lighting,
        product_integration=direction.product_integration,
        brand_integration=direction.brand_integration,
        locked_fields=["headline", "cta", "product_integration"],
    )
