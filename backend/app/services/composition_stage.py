"""Final composition orchestration.

Builds a layout from approved material, renders it, stores the result, and
applies the constrained edits a human makes to it.

**The layout is the source of truth.** Everything a user changes is a change to
data; the PNG is an output, regenerated from it. That is what makes an edit
reversible, a channel variant free, and a render reproducible.

**Edits are constrained, not free.** The editor may move, resize, restyle, hide
and rewrite — but the call to action and the legal line carry approved words,
and changing them is checked against the approved plan rather than accepted.
An invalid edit is a typed error, never a silently accepted brand violation.

**Nothing historical is overwritten.** An edit writes a new layout version; a
render writes a new final asset. An asset that has gone to a client stays
exactly what it was.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import BrandAssetRow, CampaignRow, FinalAssetRow, GeneratedAssetRow
from app.domain.brand import BrandProfile
from app.domain.common import Channel
from app.domain.creative import CreativeSpecification
from app.domain.creative_context import BrandGuardrails
from app.domain.layout import (
    HEX,
    PROTECTED_ROLES,
    RENDERER_VERSION,
    Box,
    ElementType,
    LayoutElement,
    LayoutReport,
    LayoutSpec,
    TextStyle,
    validate_layout,
)
from app.domain.workspace import Principal
from app.errors import Conflict, NotFound, ValidationFailed
from app.logging import get_logger
from app.providers.base import StorageProvider
from app.providers.local.storage import StorageObjectNotFound
from app.repositories.brands import BrandAssetRepository, BrandRepository
from app.repositories.campaigns import CampaignRepository
from app.repositories.composition import FinalAssetRepository, LayoutSpecRepository
from app.repositories.creative import CreativeSpecificationRepository
from app.repositories.evaluation import CreativeSelectionRepository
from app.repositories.generation import GeneratedAssetRepository
from app.services.layout_builder import adapt_to_channel, build_layout
from app.services.renderer import RenderError, RenderInputs, render

log = get_logger(__name__)

#: The channel a campaign composes first when it has not chosen one.
DEFAULT_CHANNEL = Channel.INSTAGRAM_POST

#: Channels this release composes for.
#:
#: The print sizes exist in `CHANNEL_DIMENSIONS` and the layout engine can lay
#: them out, but print *production* — CMYK, bleed, crop marks, PDF — is not
#: built, and handing someone an RGB PNG at A3 and calling it print-ready would
#: be a lie about what this does. Screen channels only, said out loud.
COMPOSABLE_CHANNELS: tuple[Channel, ...] = (
    Channel.INSTAGRAM_POST,
    Channel.INSTAGRAM_STORY,
    Channel.LINKEDIN,
    Channel.FACEBOOK,
    Channel.WEB_BANNER,
)


def _assert_composable(channel: Channel) -> None:
    if channel not in COMPOSABLE_CHANNELS:
        raise ValidationFailed(
            f"{channel.value} is a print size, and print production is not part of "
            "this release. Compose a screen channel instead.",
            details={
                "channel": channel.value,
                "composable": [c.value for c in COMPOSABLE_CHANNELS],
            },
        )


@dataclass(frozen=True)
class CompositionView:
    """Where final composition stands, in one read."""

    campaign_id: str
    channel: Channel
    layout: LayoutSpec | None
    report: LayoutReport | None
    final_assets: list[FinalAssetRow]
    #: Channels that already have a layout — what "variants" would extend.
    composed_channels: list[str]
    source_asset_id: str | None
    can_compose: bool
    blocked_reason: str | None


class CompositionService:
    """Layouts, renders, edits and variants."""

    def __init__(
        self,
        session: AsyncSession,
        principal: Principal,
        *,
        settings: Settings,
        storage: StorageProvider,
    ) -> None:
        """No `llm`, no `embeddings` — deliberately.

        Composition calls no model. Every other stage service takes both, and
        leaving them here for symmetry would suggest this one might reach for a
        model given the chance. The constructor is the cheapest place to say
        that it cannot (ADR-014).
        """
        self.session = session
        self.principal = principal
        self.settings = settings
        self.storage = storage
        self.organization_id = uuid.UUID(principal.organization_id)

        self.campaigns = CampaignRepository(session, self.organization_id)
        self.brands = BrandRepository(session, self.organization_id)
        self.brand_assets = BrandAssetRepository(session, self.organization_id)
        self.assets = GeneratedAssetRepository(session, self.organization_id)
        self.specifications = CreativeSpecificationRepository(session, self.organization_id)
        self.selections = CreativeSelectionRepository(session, self.organization_id)
        self.layouts = LayoutSpecRepository(session, self.organization_id)
        self.finals = FinalAssetRepository(session, self.organization_id)

    # ------------------------------------------------------------ reading
    async def current(
        self, campaign_id: uuid.UUID, *, channel: Channel = DEFAULT_CHANNEL
    ) -> CompositionView:
        campaign = await self._campaign(campaign_id)
        row = await self.layouts.latest(campaign.id, channel)
        layout = LayoutSpec.model_validate(row.payload) if row else None
        plate = await self._plate_row(campaign)

        return CompositionView(
            campaign_id=str(campaign.id),
            channel=channel,
            layout=layout,
            report=validate_layout(layout) if layout else None,
            final_assets=await self.finals.for_campaign(campaign.id),
            composed_channels=await self.layouts.channels(campaign.id),
            source_asset_id=str(plate.id) if plate else None,
            can_compose=plate is not None,
            blocked_reason=(
                None
                if plate is not None
                else "Generate and select a creative before composing the final asset."
            ),
        )

    # ----------------------------------------------------------- composing
    async def compose(
        self, campaign_id: uuid.UUID, *, channel: Channel = DEFAULT_CHANNEL
    ) -> CompositionView:
        """Build the default layout for a channel from approved material.

        Idempotent: a channel that already has a layout keeps it, because
        rebuilding would discard a human's edits without being asked.
        """
        # Campaign first: a campaign this organization cannot see is a 404
        # whatever channel was asked for. Validating the channel ahead of the
        # scope check would answer a different question than the caller asked.
        campaign = await self._campaign(campaign_id)
        _assert_composable(channel)
        if await self.layouts.latest(campaign.id, channel) is not None:
            return await self.current(campaign_id, channel=channel)

        specification, plate, logo_key = await self._materials(campaign)
        layout = build_layout(
            campaign_id=str(campaign.id),
            channel=channel,
            specification=specification,
            guardrails=(await self._guardrails(campaign)),
            plate_storage_key=plate.storage_key,
            logo_storage_key=logo_key,
            source_asset_id=str(plate.id),
            version=1,
        )
        await self.layouts.create(
            campaign_id=campaign.id,
            channel=channel,
            version=1,
            payload=layout.model_dump(mode="json"),
            source_asset_id=plate.id,
            specification_version=specification.version,
        )
        log.info("layout_composed", campaign_id=str(campaign.id), channel=channel.value)
        return await self.current(campaign_id, channel=channel)

    async def add_variant(
        self, campaign_id: uuid.UUID, *, channel: Channel, source: Channel = DEFAULT_CHANNEL
    ) -> CompositionView:
        """The same composition, re-laid for another frame.

        A re-layout, never a regeneration: the plate, the copy and the logo are
        identical, and only the geometry moves.
        """
        campaign = await self._campaign(campaign_id)
        _assert_composable(channel)
        if channel is source:
            raise ValidationFailed(
                "A variant needs a different channel from its source.",
                details={"field": "channel"},
            )
        source_row = await self.layouts.latest(campaign.id, source)
        if source_row is None:
            raise Conflict(f"Compose the {source.value} layout before deriving a variant.")
        if await self.layouts.latest(campaign.id, channel) is not None:
            return await self.current(campaign_id, channel=channel)

        variant = adapt_to_channel(LayoutSpec.model_validate(source_row.payload), channel)
        await self.layouts.create(
            campaign_id=campaign.id,
            channel=channel,
            version=1,
            payload=variant.model_dump(mode="json"),
            source_asset_id=source_row.source_asset_id,
            specification_version=source_row.specification_version,
        )
        log.info(
            "variant_composed",
            campaign_id=str(campaign.id),
            channel=channel.value,
            source=source.value,
        )
        return await self.current(campaign_id, channel=channel)

    # ------------------------------------------------------------- editing
    async def edit(
        self, campaign_id: uuid.UUID, *, channel: Channel, edits: dict[str, Any]
    ) -> CompositionView:
        """Apply constrained edits as a new layout version.

        Rejected rather than trimmed when an edit is invalid: a partially
        applied change would leave a user looking at a composition that is not
        the one they asked for.
        """
        campaign = await self._campaign(campaign_id)
        row = await self.layouts.latest(campaign.id, channel)
        if row is None:
            raise Conflict(f"There is no {channel.value} layout to edit.")

        current = LayoutSpec.model_validate(row.payload)
        specification = await self._approved_specification(campaign.id)
        revised = _apply_edits(current, edits, specification)

        report = validate_layout(revised)
        if not report.can_render():
            raise ValidationFailed(
                "; ".join(issue.detail for issue in report.blocking),
                details={"issues": [issue.model_dump(mode="json") for issue in report.blocking]},
            )

        version = await self.layouts.next_version(campaign.id, channel)
        revised = LayoutSpec.model_validate(
            revised.model_dump(exclude={"id"}) | {"version": version}
        )
        await self.layouts.create(
            campaign_id=campaign.id,
            channel=channel,
            version=version,
            payload=revised.model_dump(mode="json"),
            source_asset_id=row.source_asset_id,
            specification_version=row.specification_version,
        )
        log.info(
            "layout_edited",
            campaign_id=str(campaign.id),
            channel=channel.value,
            version=version,
        )
        return await self.current(campaign_id, channel=channel)

    # ----------------------------------------------------------- rendering
    async def render_final(
        self, campaign_id: uuid.UUID, *, channel: Channel, fmt: str = "PNG"
    ) -> FinalAssetRow:
        """Render the current layout and store it as a new final asset."""
        campaign = await self._campaign(campaign_id)
        row = await self.layouts.latest(campaign.id, channel)
        if row is None:
            raise Conflict(f"Compose the {channel.value} layout before rendering it.")

        layout = LayoutSpec.model_validate(row.payload)
        inputs = await self._render_inputs(campaign, layout)

        try:
            image = render(layout, inputs, fmt=fmt)
        except RenderError as exc:
            # A composition problem stated in the user's terms, not a crash.
            raise ValidationFailed(str(exc), details={"channel": channel.value}) from exc

        version = await self.finals.next_version(campaign.id, channel)
        key = final_asset_key(
            organization_id=self.organization_id,
            campaign_id=campaign.id,
            channel=channel,
            version=version,
            mime_type=image.mime_type,
        )
        await self.storage.put(key, image.data, mime_type=image.mime_type)

        final = await self.finals.create(
            campaign_id=campaign.id,
            channel=channel,
            version=version,
            layout_spec_id=row.id,
            layout_version=row.version,
            # Frozen: a later edit to the layout must not change what this
            # asset claims to be.
            layout_snapshot=layout.model_dump(mode="json"),
            source_asset_id=row.source_asset_id,
            specification_version=row.specification_version,
            renderer_version=RENDERER_VERSION,
            storage_key=key,
            mime_type=image.mime_type,
            width=image.width,
            height=image.height,
            size_bytes=len(image.data),
            rendered_by=uuid.UUID(self.principal.user.id),
        )
        log.info(
            "final_asset_rendered",
            campaign_id=str(campaign.id),
            channel=channel.value,
            version=version,
            layout_version=row.version,
        )
        return final

    async def final_assets(
        self, campaign_id: uuid.UUID, *, channel: Channel | None = None
    ) -> list[FinalAssetRow]:
        """Every rendered deliverable, newest first.

        Old versions stay in the list: the history is what proves a re-render
        did not silently replace what a client already has.
        """
        campaign = await self._campaign(campaign_id)
        if channel is None:
            return await self.finals.for_campaign(campaign.id)
        return await self.finals.for_channel(campaign.id, channel)

    async def scoped_final(self, campaign_id: uuid.UUID, asset_id: uuid.UUID) -> FinalAssetRow:
        """A final asset that belongs to this organization *and* this campaign.

        Both checks matter: the repository scope stops another tenant's asset,
        and the campaign comparison stops an id from one campaign being read
        through another campaign's URL.
        """
        campaign = await self._campaign(campaign_id)
        row = await self.finals.get(asset_id)
        if row is None or row.campaign_id != campaign.id:
            raise NotFound("Final asset not found.")
        return row

    # ------------------------------------------------------------ internals
    async def _campaign(self, campaign_id: uuid.UUID) -> CampaignRow:
        row = await self.campaigns.get(campaign_id)
        if row is None:
            raise NotFound("Campaign not found.")
        return row

    async def _materials(
        self, campaign: CampaignRow
    ) -> tuple[CreativeSpecification, GeneratedAssetRow, str | None]:
        specification = await self._approved_specification(campaign.id)
        plate = await self._plate_row(campaign)
        if plate is None:
            raise Conflict("Generate and select a creative before composing the final asset.")
        logo = await self._logo_row(campaign)
        return specification, plate, logo.storage_key if logo else None

    async def _approved_specification(self, campaign_id: uuid.UUID) -> CreativeSpecification:
        latest = await self.specifications.latest(campaign_id)
        if latest is None or latest.approved_at is None:
            raise Conflict("Approve a Creative Specification before composing.")
        return CreativeSpecification.model_validate(latest.payload)

    async def _plate_row(self, campaign: CampaignRow) -> GeneratedAssetRow | None:
        """The plate to compose on.

        The human's selection where they made one — the whole point of
        Milestone 7's selection step — and the newest generated plate
        otherwise, so a campaign that skipped selection can still compose.
        """
        selection = await self.selections.current(campaign.id)
        if selection is not None:
            chosen = await self.assets.get(selection.generated_asset_id)
            if chosen is not None and chosen.campaign_id == campaign.id:
                return chosen
        assets = await self.assets.for_campaign(campaign.id)
        return assets[0] if assets else None

    async def _logo_row(self, campaign: CampaignRow) -> BrandAssetRow | None:
        """The brand's approved logo, or nothing.

        Never a placeholder: a poster with an invented mark looks finished and
        cannot be used.
        """
        assets = await self.brand_assets.list_for_brand(campaign.brand_profile_id)
        logos = [asset for asset in assets if asset.kind in ("logo", "logo_mono")]
        return logos[0] if logos else None

    async def _font_row(self, campaign: CampaignRow) -> BrandAssetRow | None:
        assets = await self.brand_assets.list_for_brand(campaign.brand_profile_id)
        fonts = [asset for asset in assets if asset.kind == "font"]
        return fonts[0] if fonts else None

    async def _guardrails(self, campaign: CampaignRow) -> BrandGuardrails:
        row = await self.brands.get(campaign.brand_profile_id)
        if row is None:
            return BrandGuardrails()
        return BrandGuardrails.from_brand(BrandProfile.model_validate(row.payload))

    async def _render_inputs(self, campaign: CampaignRow, layout: LayoutSpec) -> RenderInputs:
        """Fetch the bytes the renderer draws from.

        A missing plate degrades to the flat brand ground rather than failing:
        export has to survive a storage hiccup. A missing *logo* does not
        degrade — the renderer refuses, because a poster without the mark it
        was designed around is not a deliverable.
        """
        plate = await self._maybe_bytes(layout.plate_storage_key)
        logo_key = next(
            (
                element.storage_key
                for element in layout.elements
                if element.type is ElementType.LOGO and element.visible
            ),
            None,
        )
        font_row = await self._font_row(campaign)
        return RenderInputs(
            plate=plate,
            logo=await self._maybe_bytes(logo_key),
            font=await self._maybe_bytes(font_row.storage_key if font_row else None),
        )

    async def _maybe_bytes(self, key: str | None) -> bytes | None:
        if not key:
            return None
        try:
            return await self.storage.get(key)
        except StorageObjectNotFound:
            log.warning("composition_asset_missing", key=key)
            return None


def final_asset_key(
    *,
    organization_id: uuid.UUID,
    campaign_id: uuid.UUID,
    channel: Channel,
    version: int,
    mime_type: str,
) -> str:
    """The storage key for a rendered deliverable.

    Entirely generated: no part comes from anything a user typed, so a filename
    can never traverse a path or collide with another tenant's object. The
    organization prefix is defence in depth — access control stays in the
    scoped repositories — and makes a mis-scoped read obvious in logs.
    """
    extension = {"image/png": "png", "image/jpeg": "jpg"}.get(mime_type, "bin")
    return (
        f"org-{organization_id}/campaign-{campaign_id}/final/"
        f"{channel.value}-v{version}-{uuid.uuid4().hex}.{extension}"
    )


# ---------------------------------------------------------------------------
# The constrained editor
# ---------------------------------------------------------------------------
#: What an edit may change about any element. Anything else is refused rather
#: than ignored — this is a composition tool, not a design system.
EDITABLE_ELEMENT_FIELDS: frozenset[str] = frozenset(
    {"content", "visible", "x", "y", "width", "height", "size", "align", "color", "uppercase"}
)

#: Position and visibility apply to everything the layout draws.
_COMMON_FIELDS: frozenset[str] = frozenset({"visible", "x", "y", "width", "height"})

#: The rest only mean something on text. Offering them on a logo would be a
#: control that quietly does nothing.
_TEXT_FIELDS: frozenset[str] = frozenset({"content", "size", "align", "color", "uppercase"})

_ALIGNMENTS: frozenset[str] = frozenset({"left", "center", "right"})


def _editable_fields(element: LayoutElement) -> frozenset[str]:
    if element.type is ElementType.TEXT and element.text_style is not None:
        return _COMMON_FIELDS | _TEXT_FIELDS
    return _COMMON_FIELDS


def _apply_edits(
    layout: LayoutSpec, edits: dict[str, Any], specification: CreativeSpecification
) -> LayoutSpec:
    """Apply a human's changes to a copy of the layout.

    Pure: returns a new spec and never mutates the one passed in, so the caller
    can validate the result before deciding to store it.

    Every rejection is a typed `ValidationFailed` carrying a sentence a user can
    act on. A change the editor cannot honour is refused, never dropped — a
    silently ignored edit reads as "applied" and is the worst outcome here.
    """
    revised = LayoutSpec.model_validate(layout.model_dump(mode="json"))
    by_id = {element.id: element for element in revised.elements}

    for element_id, changes in (edits.get("elements") or {}).items():
        element = by_id.get(element_id)
        if element is None:
            raise ValidationFailed(
                "That element is not part of this layout.", details={"element_id": element_id}
            )

        allowed = _editable_fields(element)
        unknown = set(changes) - allowed
        if unknown:
            raise ValidationFailed(
                f"These properties cannot be edited on this element: {', '.join(sorted(unknown))}.",
                details={"element_id": element_id, "editable": sorted(allowed)},
            )

        if "content" in changes:
            content = str(changes["content"])
            _guard_content(element.role, content, specification)
            element.content = content
        if "visible" in changes:
            _guard_visibility(element, bool(changes["visible"]))
            element.visible = bool(changes["visible"])

        _move(element, changes, element_id=element_id)
        _restyle(element, changes, element_id=element_id)

    if "background_color" in edits:
        revised.background_color = _colour(str(edits["background_color"]))
    return revised


def _move(element: LayoutElement, changes: dict[str, Any], *, element_id: str) -> None:
    """Reposition within the canvas.

    `Box` refuses a rectangle that leaves the artboard, and that refusal becomes
    a 400 rather than a 500: moving something off the edge is a normal thing for
    a user to try, not a bug.
    """
    geometry = {name: changes[name] for name in ("x", "y", "width", "height") if name in changes}
    if not geometry:
        return
    try:
        # Rebuilt rather than copied: `model_copy` skips validators, and the
        # canvas check is the whole point of going through the model.
        element.box = Box.model_validate(
            element.box.model_dump() | {name: float(value) for name, value in geometry.items()}
        )
    except PydanticValidationError as exc:
        raise ValidationFailed(
            "That position would put the element outside the canvas.",
            details={"element_id": element_id, "fields": sorted(geometry)},
        ) from exc


def _restyle(element: LayoutElement, changes: dict[str, Any], *, element_id: str) -> None:
    style = element.text_style
    if style is None:
        return
    update: dict[str, Any] = {}
    if "size" in changes:
        update["size"] = float(changes["size"])
    if "align" in changes:
        align = str(changes["align"])
        if align not in _ALIGNMENTS:
            raise ValidationFailed(
                "Text can be aligned left, center or right.",
                details={"element_id": element_id, "align": align},
            )
        update["align"] = align
    if "color" in changes:
        update["color"] = _colour(str(changes["color"]))
    if "uppercase" in changes:
        update["uppercase"] = bool(changes["uppercase"])
    if not update:
        return
    try:
        element.text_style = TextStyle.model_validate(style.model_dump() | update)
    except PydanticValidationError as exc:
        raise ValidationFailed(
            "That text style is out of range.",
            details={"element_id": element_id, "fields": sorted(update)},
        ) from exc


def _colour(value: str) -> str:
    """A colour the renderer can actually draw.

    Checked here so a malformed hex is a sentence rather than a Pillow failure
    halfway through a render.
    """
    if not re.fullmatch(HEX, value):
        raise ValidationFailed(
            "Colours must be hex values such as #1A1A1A.", details={"color": value}
        )
    return value


def _guard_content(role: str | None, content: str, specification: CreativeSpecification) -> None:
    """Approved words stay approved.

    The call to action and the legal line are campaign facts a human already
    signed off. The editor may move, resize, recolour or hide them; putting
    different words in them is a change to the approved plan, and that belongs
    to the revision loop, not to a layout tweak.
    """
    if not content.strip():
        raise ValidationFailed("Text cannot be empty. Hide the element instead.")
    if role not in PROTECTED_ROLES:
        return
    if role == "cta" and content.strip() != specification.cta.strip():
        raise ValidationFailed(
            "The call to action is an approved campaign fact. Change it through a "
            "revision rather than in the layout.",
            details={"role": role, "approved": specification.cta},
        )
    if role == "legal":
        raise ValidationFailed(
            "The legal line comes from the Brand Brain and cannot be edited here.",
            details={"role": role},
        )


def _guard_visibility(element: LayoutElement, visible: bool) -> None:
    """The logo cannot be switched off.

    Every other element is the user's to show or hide. A branded asset without
    the brand is not one of the things this tool makes.
    """
    if not visible and element.type is ElementType.LOGO:
        raise ValidationFailed(
            "The logo cannot be hidden on a final branded asset.",
            details={"element_id": element.id},
        )
