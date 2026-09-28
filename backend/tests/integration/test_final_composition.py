"""Final composition end to end: layout, render, edit, variants, export.

The centrepiece is `TestHistoryIsNeverOverwritten`: compose → render → edit →
re-render, asserting that layout v1 still exists unchanged, that final asset v1
still carries its own bytes and its own provenance, and that the v1 asset points
at layout v1 rather than at the version that replaced it. An asset that has gone
to a client has to stay exactly what it was, and that test is what proves it.

`TestTheEditorRefusesRatherThanBreaks` is the other half: every way a human can
ask for something the brand does not allow, answered with a typed error and a
sentence, never with a quietly broken poster.

Nothing here reaches a live provider, and no image model is called at all —
composition is deterministic Pillow work.
"""

from __future__ import annotations

import io
import tempfile
import uuid

import pytest
from PIL import Image

from app.config import Settings, get_settings
from app.db.models import (
    BrandAssetRow,
    BrandProfileRow,
    CampaignRow,
    CanonicalPromptRow,
    CreativeSpecificationRow,
    GeneratedAssetRow,
    GenerationJobRow,
    ModelPromptRow,
)
from app.domain.common import CHANNEL_DIMENSIONS, Channel, JobStatus, Role, utc_now
from app.domain.creative import CreativeSpecification, NegativeConstraints
from app.domain.layout import RENDERER_VERSION, LayoutSpec
from app.domain.prompt import CanonicalPrompt, ModelPrompt
from app.domain.workspace import Principal, User
from app.errors import Conflict, NotFound, ValidationFailed
from app.providers.base import ImageRequest
from app.providers.local.storage import LocalStorageProvider
from app.providers.mock.image import MockImageProvider
from app.repositories.composition import FinalAssetRepository, LayoutSpecRepository
from app.services.composition_stage import CompositionService
from tests.integration.factories import make_org

pytestmark = pytest.mark.integration

_STORAGE_ROOT = tempfile.mkdtemp(prefix="campaign-os-composition-")


def _settings(**overrides) -> Settings:
    base = get_settings().model_dump()
    base.update({"image_provider": "mock", "image_providers": "", "mock_failure_mode": "none"})
    base.update(overrides)
    return Settings(**base)


def _principal(workspace) -> Principal:
    return Principal(
        user=User(id=str(workspace.user.id), email=workspace.user.email),
        organization_id=str(workspace.org.id),
        role=Role.ADMIN,
    )


def _principal_for_org(user, org) -> Principal:
    return Principal(
        user=User(id=str(user.id), email=user.email),
        organization_id=str(org.id),
        role=Role.ADMIN,
    )


@pytest.fixture
def storage() -> LocalStorageProvider:
    return LocalStorageProvider(_STORAGE_ROOT)


def _service(session, principal: Principal, storage) -> CompositionService:
    return CompositionService(session, principal, settings=_settings(), storage=storage)


def _specification(campaign_id: uuid.UUID, version: int = 1) -> CreativeSpecification:
    return CreativeSpecification(
        campaign_id=str(campaign_id),
        direction_id=str(uuid.uuid4()),
        version=version,
        concept="The facade, read as engineering",
        visual_story="A single bay at the hour the light rakes across it",
        emotional_angle="engineering confidence",
        headline="Built to outlast the building it clads",
        subhead="Tested to 2,400 Pa wind load",
        cta="Request the specification pack",
        visual_metaphor="machined precision standing for permanence",
        composition="tight orthographic framing",
        focal_point="the joint between two panels",
        subject="a single bay of the FS-9 facade system",
        environment="a modern construction site",
        lighting="hard directional studio light",
        palette=["#1F2933", "#E4572E"],
        product_integration="the system is the subject, not a prop",
        brand_integration="colour and restraint, not a badge",
        negative_constraints=NegativeConstraints(forbidden_elements=["stock handshakes"]),
    )


async def _seed(
    session,
    org,
    storage,
    *,
    with_logo: bool = True,
    approved: bool = True,
    plate_mime: str = "image/png",
    plate_colour: tuple[int, int, int] | None = None,
):
    """A campaign with an approved specification, a selected plate and a logo —
    everything final composition needs and nothing it does not."""
    brand = BrandProfileRow(
        organization_id=org.id,
        name=f"Northline {uuid.uuid4().hex[:6]}",
        payload={
            "id": str(uuid.uuid4()),
            "organization_id": str(org.id),
            "name": "Northline",
            "colors": [
                {"name": "Graphite", "hex": "#1F2933", "role": "primary"},
                {"name": "Ember", "hex": "#E4572E", "role": "accent"},
            ],
        },
    )
    session.add(brand)
    await session.flush()

    if with_logo:
        logo_key = f"org-{org.id}/brand-{brand.id}/logo-{uuid.uuid4().hex}.png"
        await storage.put(logo_key, _png(320, 120), mime_type="image/png")
        session.add(
            BrandAssetRow(
                organization_id=org.id,
                brand_profile_id=brand.id,
                kind="logo",
                storage_key=logo_key,
                filename="logo.png",
                mime_type="image/png",
                bytes=0,
            )
        )

    campaign_id = uuid.uuid4()
    campaign = CampaignRow(
        id=campaign_id,
        organization_id=org.id,
        brand_profile_id=brand.id,
        title="FS-9 launch",
        status="SPECIFICATION_CONFIRMED",
        thread_id=str(campaign_id),
        draft_inputs={},
    )
    session.add(campaign)
    await session.flush()

    specification = _specification(campaign_id)
    session.add(
        CreativeSpecificationRow(
            organization_id=org.id,
            campaign_id=campaign_id,
            direction_id=uuid.UUID(specification.direction_id),
            version=1,
            payload=specification.model_dump(mode="json"),
            approved_at=utc_now() if approved else None,
        )
    )
    await session.flush()

    plate = await _plate(
        session,
        org,
        campaign,
        specification,
        storage,
        plate_mime=plate_mime,
        plate_colour=plate_colour,
    )
    return campaign, specification, plate


def _png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (31, 41, 51)).save(buffer, format="PNG")
    return buffer.getvalue()


async def _plate(
    session,
    org,
    campaign,
    specification,
    storage,
    *,
    plate_mime: str = "image/png",
    plate_colour: tuple[int, int, int] | None = None,
) -> GeneratedAssetRow:
    # A complete `CanonicalPrompt`, not a stub: the overview read model
    # validates this payload back into the model, and a fixture that only
    # half-fills it fails there for a reason that has nothing to do with the
    # thing under test.
    prompt_payload = CanonicalPrompt(
        campaign_id=str(campaign.id),
        specification_id=specification.id,
        specification_version=1,
        version=1,
        subject=specification.subject,
        environment=specification.environment,
        composition=specification.composition,
        lighting=specification.lighting,
        palette=list(specification.palette),
    ).model_dump(mode="json")
    canonical = CanonicalPromptRow(
        organization_id=org.id,
        campaign_id=campaign.id,
        specification_id=uuid.UUID(specification.id),
        specification_version=1,
        version=1,
        payload=prompt_payload,
        source_fingerprint=uuid.uuid4().hex,
    )
    session.add(canonical)
    await session.flush()
    prompt = ModelPromptRow(
        organization_id=org.id,
        campaign_id=campaign.id,
        canonical_prompt_id=canonical.id,
        provider="mock",
        model="mock-image-1",
        version=1,
        payload=ModelPrompt(
            campaign_id=str(campaign.id),
            canonical_prompt_id=prompt_payload["id"],
            specification_id=specification.id,
            specification_version=1,
            provider="mock",
            model="mock-image-1",
            version=1,
            text=specification.subject,
        ).model_dump(mode="json"),
    )
    session.add(prompt)
    await session.flush()
    job = GenerationJobRow(
        organization_id=org.id,
        campaign_id=campaign.id,
        model_prompt_id=prompt.id,
        specification_id=uuid.UUID(specification.id),
        specification_version=1,
        batch_id=uuid.uuid4(),
        provider="mock",
        model="mock-image-1",
        status=JobStatus.COMPLETED.value,
        idempotency_key=f"key-{uuid.uuid4()}",
    )
    session.add(job)
    await session.flush()

    (image,) = await MockImageProvider().generate(
        ImageRequest(prompt=f"plate for {campaign.id}", aspect_ratio="1:1")
    )
    # Gemini only ever returns JPEG; the mock renders PNG. Re-encoding the
    # mock's own pixels keeps the two cases identical apart from the format.
    data = image.data
    if plate_colour is not None:
        # A flat, known colour, so a test can prove the plate's own pixels
        # reached the canvas rather than only that something was drawn.
        buffer = io.BytesIO()
        Image.new("RGB", (image.width, image.height), plate_colour).save(buffer, format="PNG")
        data = buffer.getvalue()
    if plate_mime == "image/jpeg":
        buffer = io.BytesIO()
        with Image.open(io.BytesIO(data)) as decoded:
            decoded.convert("RGB").save(buffer, format="JPEG", quality=95)
        data = buffer.getvalue()
    extension = "jpg" if plate_mime == "image/jpeg" else "png"
    key = f"org-{org.id}/campaign-{campaign.id}/generated/{uuid.uuid4().hex}.{extension}"
    await storage.put(key, data, mime_type=plate_mime)
    row = GeneratedAssetRow(
        organization_id=org.id,
        campaign_id=campaign.id,
        generation_job_id=job.id,
        model_prompt_id=prompt.id,
        specification_id=uuid.UUID(specification.id),
        specification_version=1,
        provider="mock",
        model="mock-image-1",
        kind="VISUAL_PLATE",
        storage_key=key,
        mime_type=plate_mime,
        width=image.width,
        height=image.height,
        meta={},
    )
    session.add(row)
    await session.flush()
    return row


def _element_id(layout: LayoutSpec, role: str) -> str:
    element = layout.by_role(role)
    assert element is not None, f"the default layout has no {role}"
    return element.id


# ===========================================================================
class TestComposingFromApprovedMaterial:
    async def test_compose_builds_a_layout_from_the_approved_specification(
        self, session, workspace, storage
    ) -> None:
        campaign, specification, plate = await _seed(session, workspace.org, storage)
        service = _service(session, _principal(workspace), storage)

        view = await service.compose(campaign.id)

        assert view.layout is not None
        layout = view.layout
        assert layout.version == 1
        assert layout.channel is Channel.INSTAGRAM_POST
        assert (layout.width, layout.height) == CHANNEL_DIMENSIONS[Channel.INSTAGRAM_POST]
        assert layout.plate_storage_key == plate.storage_key
        assert layout.source_asset_id == str(plate.id)

        headline = layout.by_role("headline")
        cta = layout.by_role("cta")
        assert headline is not None and cta is not None
        assert headline.content == specification.headline, "copy comes from the approved plan"
        assert cta.content == specification.cta
        assert view.report is not None and view.report.can_render()

    async def test_composing_twice_keeps_the_first_layout(
        self, session, workspace, storage
    ) -> None:
        """Idempotent on purpose: rebuilding would silently discard an edit."""
        campaign, _, _ = await _seed(session, workspace.org, storage)
        service = _service(session, _principal(workspace), storage)

        first = await service.compose(campaign.id)
        await service.edit(
            campaign.id,
            channel=Channel.INSTAGRAM_POST,
            edits={"elements": {_element_id(first.layout, "headline"): {"y": 0.30}}},
        )
        again = await service.compose(campaign.id)

        assert again.layout is not None
        assert again.layout.version == 2, "compose did not rebuild over the edit"

    async def test_composing_without_an_approved_specification_is_refused(
        self, session, workspace, storage
    ) -> None:
        campaign, _, _ = await _seed(session, workspace.org, storage, approved=False)
        service = _service(session, _principal(workspace), storage)

        with pytest.raises(Conflict, match="Approve a Creative Specification"):
            await service.compose(campaign.id)

    async def test_a_print_channel_is_refused_with_a_reason(
        self, session, workspace, storage
    ) -> None:
        """Print production is not in this release, and the refusal says so
        rather than handing someone an RGB PNG at A3."""
        campaign, _, _ = await _seed(session, workspace.org, storage)
        service = _service(session, _principal(workspace), storage)

        with pytest.raises(ValidationFailed, match="print production"):
            await service.compose(campaign.id, channel=Channel.PRINT_A3)


class TestRendering:
    async def test_render_produces_a_real_branded_asset(self, session, workspace, storage) -> None:
        campaign, specification, plate = await _seed(session, workspace.org, storage)
        service = _service(session, _principal(workspace), storage)
        await service.compose(campaign.id)

        final = await service.render_final(campaign.id, channel=Channel.INSTAGRAM_POST)

        assert final.kind == "FINAL_BRANDED_ASSET", "a plate is not a final asset"
        assert final.version == 1
        assert (final.width, final.height) == CHANNEL_DIMENSIONS[Channel.INSTAGRAM_POST]
        assert final.renderer_version == RENDERER_VERSION
        assert final.source_asset_id == plate.id
        assert final.specification_version == specification.version
        assert final.layout_version == 1

        stored = await storage.get(final.storage_key)
        image = Image.open(io.BytesIO(stored))
        assert image.size == (final.width, final.height)
        assert image.format == "PNG"

    async def test_a_jpeg_plate_composes_and_renders(self, session, workspace, storage) -> None:
        """M9 compatibility with what Gemini actually returns.

        The image model only produces JPEG, so every real plate arriving from
        it is one. Composition must be indifferent to that — and the *output*
        must stay PNG, because the layer code draws is lossless and the
        `LayoutSpec`, not the image, is the source of truth (ADR-014).
        """
        campaign, specification, plate = await _seed(
            session, workspace.org, storage, plate_mime="image/jpeg"
        )
        assert plate.mime_type == "image/jpeg", "the fixture really is a JPEG plate"
        service = _service(session, _principal(workspace), storage)

        view = await service.compose(campaign.id)
        assert view.layout is not None
        assert view.layout.plate_storage_key == plate.storage_key
        assert view.report is not None and view.report.can_render()

        final = await service.render_final(campaign.id, channel=Channel.INSTAGRAM_POST)

        assert final.source_asset_id == plate.id
        assert final.specification_version == specification.version
        assert final.mime_type == "image/png"
        stored = await storage.get(final.storage_key)
        with Image.open(io.BytesIO(stored)) as image:
            assert image.format == "PNG"
            assert image.size == CHANNEL_DIMENSIONS[Channel.INSTAGRAM_POST]

    async def test_a_jpeg_plates_own_pixels_reach_the_canvas(
        self, session, workspace, storage
    ) -> None:
        """Not just 'it did not crash'. A composition that silently dropped
        the plate would still be a valid PNG of the right size — and still be
        full of colour, because the text and the scrim supply plenty of it. So
        assert the plate's *own* colour is what the canvas is made of."""
        campaign, _, _ = await _seed(
            session, workspace.org, storage, plate_mime="image/jpeg", plate_colour=(200, 30, 40)
        )
        service = _service(session, _principal(workspace), storage)
        await service.compose(campaign.id)
        final = await service.render_final(campaign.id, channel=Channel.INSTAGRAM_POST)

        with Image.open(io.BytesIO(await storage.get(final.storage_key))) as image:
            # Top corner: above the scrim and clear of every text box.
            red, green, blue = image.convert("RGB").getpixel((8, 8))
        # Not exact: the plate is JPEG-encoded and then resized to the frame.
        assert abs(red - 200) <= 4 and abs(green - 30) <= 4 and abs(blue - 40) <= 4

    async def test_the_storage_key_is_generated_not_derived_from_input(
        self, session, workspace, storage
    ) -> None:
        campaign, _, _ = await _seed(session, workspace.org, storage)
        service = _service(session, _principal(workspace), storage)
        await service.compose(campaign.id)

        final = await service.render_final(campaign.id, channel=Channel.INSTAGRAM_POST)

        assert final.storage_key.startswith(f"org-{workspace.org.id}/campaign-{campaign.id}/final/")
        assert ".." not in final.storage_key

    async def test_jpeg_export_is_available(self, session, workspace, storage) -> None:
        campaign, _, _ = await _seed(session, workspace.org, storage)
        service = _service(session, _principal(workspace), storage)
        await service.compose(campaign.id)

        final = await service.render_final(campaign.id, channel=Channel.INSTAGRAM_POST, fmt="JPEG")

        assert final.mime_type == "image/jpeg"
        assert Image.open(io.BytesIO(await storage.get(final.storage_key))).format == "JPEG"

    async def test_rendering_before_composing_is_refused(self, session, workspace, storage) -> None:
        campaign, _, _ = await _seed(session, workspace.org, storage)
        service = _service(session, _principal(workspace), storage)

        with pytest.raises(Conflict, match="Compose"):
            await service.render_final(campaign.id, channel=Channel.INSTAGRAM_POST)


class TestHistoryIsNeverOverwritten:
    """The most important test in Milestone 9.

    Compose → render → edit → re-render, proving at every step that the earlier
    layout and the earlier file are still exactly what they were.
    """

    async def test_an_edit_and_a_rerender_leave_v1_intact(
        self, session, workspace, storage
    ) -> None:
        campaign, _, _ = await _seed(session, workspace.org, storage)
        principal = _principal(workspace)
        service = _service(session, principal, storage)
        layouts = LayoutSpecRepository(session, uuid.UUID(principal.organization_id))
        finals = FinalAssetRepository(session, uuid.UUID(principal.organization_id))

        composed = await service.compose(campaign.id)
        layout_v1 = composed.layout
        assert layout_v1 is not None
        v1_snapshot = layout_v1.model_dump(mode="json")

        final_v1 = await service.render_final(campaign.id, channel=Channel.INSTAGRAM_POST)
        v1_bytes = await storage.get(final_v1.storage_key)
        v1_key = final_v1.storage_key

        # --- the human moves the headline -------------------------------
        headline_id = _element_id(layout_v1, "headline")
        edited = await service.edit(
            campaign.id,
            channel=Channel.INSTAGRAM_POST,
            edits={"elements": {headline_id: {"y": 0.18, "size": 0.10}}},
        )
        assert edited.layout is not None
        assert edited.layout.version == 2, "an edit is a new version, never a mutation"

        # --- layout v1 is untouched -------------------------------------
        stored_v1 = await layouts.by_version(campaign.id, Channel.INSTAGRAM_POST, 1)
        assert stored_v1 is not None
        assert stored_v1.payload == v1_snapshot, "the historical layout changed"

        # --- only what was asked for moved ------------------------------
        before = {e.id: e.model_dump(mode="json") for e in layout_v1.elements}
        after = {e.id: e.model_dump(mode="json") for e in edited.layout.elements}
        assert set(before) == set(after), "an edit must not add or drop elements"
        changed = [key for key in before if before[key] != after[key]]
        assert changed == [headline_id], f"unexpected elements changed: {changed}"
        assert after[headline_id]["box"]["y"] == pytest.approx(0.18)
        assert after[headline_id]["text_style"]["size"] == pytest.approx(0.10)
        assert after[headline_id]["content"] == before[headline_id]["content"]

        # --- the second render is a second asset ------------------------
        final_v2 = await service.render_final(campaign.id, channel=Channel.INSTAGRAM_POST)
        assert final_v2.version == 2
        assert final_v2.id != final_v1.id
        assert final_v2.storage_key != v1_key, "a re-render must not overwrite the file"
        assert final_v2.layout_version == 2

        # --- and v1 is still exactly what it was ------------------------
        kept = await finals.for_channel(campaign.id, Channel.INSTAGRAM_POST)
        assert [row.version for row in kept] == [2, 1], "history was dropped"
        reloaded = next(row for row in kept if row.version == 1)
        assert reloaded.layout_version == 1, "v1 was repointed at the newer layout"
        assert reloaded.storage_key == v1_key
        assert await storage.get(v1_key) == v1_bytes, "the exported bytes changed"

    async def test_renders_in_one_transaction_are_still_ordered_by_age(
        self, session, workspace, storage
    ) -> None:
        """Guards the fix, not the symptom.

        Postgres `now()` is transaction-start time, so a server default would
        give two renders the same `created_at` and "newest first" would order
        them arbitrarily. The repository stamps the value itself.
        """
        campaign, _, _ = await _seed(session, workspace.org, storage)
        service = _service(session, _principal(workspace), storage)
        await service.compose(campaign.id)
        await service.add_variant(campaign.id, channel=Channel.LINKEDIN)

        first = await service.render_final(campaign.id, channel=Channel.INSTAGRAM_POST)
        second = await service.render_final(campaign.id, channel=Channel.LINKEDIN)

        assert second.created_at > first.created_at
        listed = await service.final_assets(campaign.id)
        assert [row.id for row in listed] == [second.id, first.id], "newest first is not real"

    async def test_the_snapshot_is_frozen_at_render_time(self, session, workspace, storage) -> None:
        """The asset carries the recipe inline, so a later edit cannot change
        what an already-exported file claims to be."""
        campaign, _, _ = await _seed(session, workspace.org, storage)
        service = _service(session, _principal(workspace), storage)
        composed = await service.compose(campaign.id)
        assert composed.layout is not None

        final_v1 = await service.render_final(campaign.id, channel=Channel.INSTAGRAM_POST)
        snapshot = dict(final_v1.layout_snapshot)

        await service.edit(
            campaign.id,
            channel=Channel.INSTAGRAM_POST,
            edits={"elements": {_element_id(composed.layout, "headline"): {"y": 0.42}}},
        )

        assert final_v1.layout_snapshot == snapshot
        assert LayoutSpec.model_validate(final_v1.layout_snapshot).version == 1


class TestTheEditorRefusesRatherThanBreaks:
    """Every refusal is a typed error carrying a sentence a user can act on."""

    async def _composed(self, session, workspace, storage):
        campaign, specification, _ = await _seed(session, workspace.org, storage)
        service = _service(session, _principal(workspace), storage)
        view = await service.compose(campaign.id)
        assert view.layout is not None
        return service, campaign, specification, view.layout

    async def test_a_safe_move_is_accepted(self, session, workspace, storage) -> None:
        service, campaign, _, layout = await self._composed(session, workspace, storage)

        view = await service.edit(
            campaign.id,
            channel=Channel.INSTAGRAM_POST,
            edits={"elements": {_element_id(layout, "subhead"): {"x": 0.10}}},
        )

        assert view.layout is not None
        assert view.report is not None and view.report.can_render()

    async def test_rewriting_the_approved_cta_is_refused(self, session, workspace, storage) -> None:
        service, campaign, specification, layout = await self._composed(session, workspace, storage)

        with pytest.raises(ValidationFailed, match="approved campaign fact"):
            await service.edit(
                campaign.id,
                channel=Channel.INSTAGRAM_POST,
                edits={"elements": {_element_id(layout, "cta"): {"content": "Buy now"}}},
            )

        assert layout.by_role("cta").content == specification.cta

    async def test_moving_an_element_off_the_canvas_is_refused(
        self, session, workspace, storage
    ) -> None:
        service, campaign, _, layout = await self._composed(session, workspace, storage)

        with pytest.raises(ValidationFailed, match="outside the canvas"):
            await service.edit(
                campaign.id,
                channel=Channel.INSTAGRAM_POST,
                edits={"elements": {_element_id(layout, "headline"): {"x": 0.95, "width": 0.5}}},
            )

    async def test_hiding_the_logo_is_refused(self, session, workspace, storage) -> None:
        service, campaign, _, layout = await self._composed(session, workspace, storage)
        logo = next(e for e in layout.elements if e.type.value == "logo")

        with pytest.raises(ValidationFailed, match="logo cannot be hidden"):
            await service.edit(
                campaign.id,
                channel=Channel.INSTAGRAM_POST,
                edits={"elements": {logo.id: {"visible": False}}},
            )

    async def test_emptying_a_text_element_is_refused(self, session, workspace, storage) -> None:
        service, campaign, _, layout = await self._composed(session, workspace, storage)

        with pytest.raises(ValidationFailed, match="cannot be empty"):
            await service.edit(
                campaign.id,
                channel=Channel.INSTAGRAM_POST,
                edits={"elements": {_element_id(layout, "headline"): {"content": "   "}}},
            )

    async def test_an_unsupported_property_is_refused_not_ignored(
        self, session, workspace, storage
    ) -> None:
        """A silently dropped edit reads as "applied", which is worse than a
        refusal — this is a composition tool, not a design system."""
        service, campaign, _, layout = await self._composed(session, workspace, storage)

        with pytest.raises(ValidationFailed, match="cannot be edited"):
            await service.edit(
                campaign.id,
                channel=Channel.INSTAGRAM_POST,
                edits={"elements": {_element_id(layout, "headline"): {"rotation": 45}}},
            )

    async def test_a_text_property_on_a_logo_is_refused(self, session, workspace, storage) -> None:
        service, campaign, _, layout = await self._composed(session, workspace, storage)
        logo = next(e for e in layout.elements if e.type.value == "logo")

        with pytest.raises(ValidationFailed, match="cannot be edited"):
            await service.edit(
                campaign.id,
                channel=Channel.INSTAGRAM_POST,
                edits={"elements": {logo.id: {"uppercase": True}}},
            )

    async def test_an_unknown_element_is_refused(self, session, workspace, storage) -> None:
        service, campaign, _, _ = await self._composed(session, workspace, storage)

        with pytest.raises(ValidationFailed, match="not part of this layout"):
            await service.edit(
                campaign.id,
                channel=Channel.INSTAGRAM_POST,
                edits={"elements": {str(uuid.uuid4()): {"x": 0.1}}},
            )

    async def test_a_malformed_colour_is_refused(self, session, workspace, storage) -> None:
        service, campaign, _, layout = await self._composed(session, workspace, storage)

        with pytest.raises(ValidationFailed, match="hex"):
            await service.edit(
                campaign.id,
                channel=Channel.INSTAGRAM_POST,
                edits={"elements": {_element_id(layout, "headline"): {"color": "off-white"}}},
            )

    async def test_a_refused_edit_writes_no_version(self, session, workspace, storage) -> None:
        """Rejected whole, never partially applied."""
        service, campaign, _, layout = await self._composed(session, workspace, storage)
        layouts = LayoutSpecRepository(session, campaign.organization_id)

        with pytest.raises(ValidationFailed):
            await service.edit(
                campaign.id,
                channel=Channel.INSTAGRAM_POST,
                edits={
                    "elements": {
                        _element_id(layout, "subhead"): {"x": 0.12},
                        _element_id(layout, "cta"): {"content": "Buy now"},
                    }
                },
            )

        assert await layouts.next_version(campaign.id, Channel.INSTAGRAM_POST) == 2


class TestChannelVariants:
    async def test_a_variant_reuses_the_channel_dimension_table(
        self, session, workspace, storage
    ) -> None:
        campaign, specification, plate = await _seed(session, workspace.org, storage)
        service = _service(session, _principal(workspace), storage)
        await service.compose(campaign.id)

        view = await service.add_variant(campaign.id, channel=Channel.LINKEDIN)

        assert view.layout is not None
        assert (view.layout.width, view.layout.height) == CHANNEL_DIMENSIONS[Channel.LINKEDIN]
        assert view.layout.plate_storage_key == plate.storage_key, "the plate is reused"
        assert view.layout.by_role("headline").content == specification.headline
        assert view.layout.by_role("cta").content == specification.cta
        assert view.report is not None and view.report.can_render()

    async def test_two_variants_render_at_their_own_sizes(
        self, session, workspace, storage
    ) -> None:
        campaign, _, _ = await _seed(session, workspace.org, storage)
        service = _service(session, _principal(workspace), storage)
        await service.compose(campaign.id)

        for channel in (Channel.INSTAGRAM_STORY, Channel.LINKEDIN):
            await service.add_variant(campaign.id, channel=channel)
            final = await service.render_final(campaign.id, channel=channel)
            assert (final.width, final.height) == CHANNEL_DIMENSIONS[channel]
            image = Image.open(io.BytesIO(await storage.get(final.storage_key)))
            assert image.size == CHANNEL_DIMENSIONS[channel]

        view = await service.current(campaign.id)
        assert set(view.composed_channels) == {
            Channel.INSTAGRAM_POST.value,
            Channel.INSTAGRAM_STORY.value,
            Channel.LINKEDIN.value,
        }

    async def test_a_variant_needs_a_source(self, session, workspace, storage) -> None:
        campaign, _, _ = await _seed(session, workspace.org, storage)
        service = _service(session, _principal(workspace), storage)

        with pytest.raises(Conflict, match="Compose"):
            await service.add_variant(campaign.id, channel=Channel.LINKEDIN)

    async def test_a_variant_of_itself_is_refused(self, session, workspace, storage) -> None:
        campaign, _, _ = await _seed(session, workspace.org, storage)
        service = _service(session, _principal(workspace), storage)
        await service.compose(campaign.id)

        with pytest.raises(ValidationFailed, match="different channel"):
            await service.add_variant(campaign.id, channel=Channel.INSTAGRAM_POST)


class TestAnInvalidLayoutIsReportedNotRendered:
    async def test_a_broken_layout_refuses_to_render(self, session, workspace, storage) -> None:
        """The deliberate invalid case.

        A layout whose elements overlap and leave the safe area is caught while
        it is still numbers. The user gets the reason; no broken poster is
        written to storage and no asset row is created.
        """
        campaign, _, _ = await _seed(session, workspace.org, storage)
        principal = _principal(workspace)
        service = _service(session, principal, storage)
        layouts = LayoutSpecRepository(session, uuid.UUID(principal.organization_id))
        finals = FinalAssetRepository(session, uuid.UUID(principal.organization_id))

        composed = await service.compose(campaign.id)
        assert composed.layout is not None

        # Stack the headline directly on top of the CTA, outside the safe area.
        broken = composed.layout.model_dump(mode="json")
        for element in broken["elements"]:
            if element["role"] in ("headline", "cta"):
                element["box"] |= {"x": 0.0, "y": 0.90, "width": 0.9, "height": 0.09}
        await layouts.create(
            campaign_id=campaign.id,
            channel=Channel.INSTAGRAM_POST,
            version=2,
            payload=broken | {"version": 2},
            source_asset_id=None,
            specification_version=1,
        )

        view = await service.current(campaign.id)
        assert view.report is not None
        assert not view.report.can_render()
        assert view.report.blocking, "a broken layout must say what is wrong"

        with pytest.raises(ValidationFailed) as raised:
            await service.render_final(campaign.id, channel=Channel.INSTAGRAM_POST)
        assert "cannot be rendered" in str(raised.value)

        assert await finals.for_channel(campaign.id, Channel.INSTAGRAM_POST) == []


class TestTenancy:
    async def test_another_organizations_composition_is_invisible(
        self, session, workspace, storage
    ) -> None:
        theirs = await make_org(session)
        their_campaign, _, _ = await _seed(session, theirs, storage)
        their_service = _service(session, _principal_for_org(workspace.user, theirs), storage)
        await their_service.compose(their_campaign.id)
        await their_service.render_final(their_campaign.id, channel=Channel.INSTAGRAM_POST)

        mine = _service(session, _principal(workspace), storage)

        with pytest.raises(NotFound):
            await mine.current(their_campaign.id)
        with pytest.raises(NotFound):
            await mine.compose(their_campaign.id)
        with pytest.raises(NotFound):
            await mine.edit(
                their_campaign.id, channel=Channel.INSTAGRAM_POST, edits={"elements": {}}
            )
        with pytest.raises(NotFound):
            await mine.render_final(their_campaign.id, channel=Channel.INSTAGRAM_POST)

    async def test_scope_is_checked_before_the_channel_is_judged(
        self, session, workspace, storage
    ) -> None:
        """A campaign this organization cannot see is a 404 whatever channel is
        asked for — otherwise the answer depends on an argument the caller
        controls rather than on what they are allowed to see."""
        theirs = await make_org(session)
        their_campaign, _, _ = await _seed(session, theirs, storage)
        mine = _service(session, _principal(workspace), storage)

        with pytest.raises(NotFound):
            await mine.compose(their_campaign.id, channel=Channel.PRINT_A3)
        with pytest.raises(NotFound):
            await mine.add_variant(their_campaign.id, channel=Channel.PRINT_A4)

    async def test_a_final_asset_id_cannot_be_read_through_another_campaign(
        self, session, workspace, storage
    ) -> None:
        """Both checks matter: the repository scope stops another tenant, and
        the campaign comparison stops one campaign's URL reading another's."""
        first, _, _ = await _seed(session, workspace.org, storage)
        second, _, _ = await _seed(session, workspace.org, storage)
        service = _service(session, _principal(workspace), storage)
        await service.compose(first.id)
        final = await service.render_final(first.id, channel=Channel.INSTAGRAM_POST)

        assert (await service.scoped_final(first.id, final.id)).id == final.id
        with pytest.raises(NotFound):
            await service.scoped_final(second.id, final.id)

    async def test_another_organizations_final_asset_is_invisible(
        self, session, workspace, storage
    ) -> None:
        theirs = await make_org(session)
        their_campaign, _, _ = await _seed(session, theirs, storage)
        their_service = _service(session, _principal_for_org(workspace.user, theirs), storage)
        await their_service.compose(their_campaign.id)
        their_final = await their_service.render_final(
            their_campaign.id, channel=Channel.INSTAGRAM_POST
        )

        mine, _, _ = await _seed(session, workspace.org, storage)
        service = _service(session, _principal(workspace), storage)

        with pytest.raises(NotFound):
            await service.scoped_final(mine.id, their_final.id)
