"""Final composition: layouts, renders, channel variants and export.

Separate from `campaigns.py` for the same reason `brand_brain.py` is separate
from `brands.py` — this is its own stage with its own vocabulary, and the
campaign router is already long.

Two shapes worth knowing before reading:

* **The layout is what you edit; the PNG is what you get.** Every mutating
  route here changes the `LayoutSpec` and writes a new version. Rendering is a
  separate, repeatable step that reads a layout and produces a file.
* **Nothing is overwritten.** An edit is a new layout version, a render is a
  new final asset. Old versions keep their bytes and their provenance forever,
  because an asset that has gone to a client has to stay what it was.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response

from app.api.authz import EditCampaignDep
from app.api.deps import (
    MediaLinkDep,
    PrincipalDep,
    SessionDep,
    SettingsDep,
    StorageDep,
    media_access,
)
from app.api.media_links import MediaKind, MediaLink
from app.api.schemas import (
    ComposeRequest,
    CompositionView,
    FinalAssetList,
    FinalAssetView,
    LayoutEditRequest,
    RenderRequest,
    VariantRequest,
)
from app.db.models import FinalAssetRow
from app.domain.common import Channel
from app.domain.layout import FinalAssetKind
from app.domain.workspace import Principal
from app.errors import NotFound
from app.services.composition_stage import (
    COMPOSABLE_CHANNELS,
    DEFAULT_CHANNEL,
    CompositionService,
)
from app.services.composition_stage import CompositionView as ServiceCompositionView

router = APIRouter(prefix="/campaigns", tags=["composition"])

#: Extension by mime type, for the download filename. Generated from the stored
#: mime type, never from anything a user typed.
_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg"}


def _uuid(raw: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise NotFound(f"{what} not found.") from exc


def _service(
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> CompositionService:
    return CompositionService(session, principal, settings=settings, storage=storage)


def final_asset_view(row: FinalAssetRow, link: MediaLink) -> FinalAssetView:
    """Shared with the campaign overview, so the two cannot describe the same
    row differently."""
    return FinalAssetView(
        id=str(row.id),
        campaign_id=str(row.campaign_id),
        channel=Channel(row.channel),
        kind=FinalAssetKind(row.kind),
        version=row.version,
        width=row.width,
        height=row.height,
        mime_type=row.mime_type,
        size_bytes=row.bytes,
        # Signed and short-lived: the download link and the preview are both
        # fetched by the browser, which cannot send the scope headers.
        url=link.final_asset(row.campaign_id, row.id),
        download_url=link.final_asset(row.campaign_id, row.id, download=True),
        source_asset_id=str(row.source_asset_id) if row.source_asset_id else None,
        specification_version=row.specification_version,
        layout_version=row.layout_version,
        renderer_version=row.renderer_version,
        created_at=row.created_at,
    )


def _view(view: ServiceCompositionView, link: MediaLink) -> CompositionView:
    composed = [Channel(value) for value in view.composed_channels]
    return CompositionView(
        campaign_id=view.campaign_id,
        channel=view.channel,
        layout=view.layout,
        report=view.report,
        final_assets=[final_asset_view(row, link) for row in view.final_assets],
        composed_channels=composed,
        available_channels=[c for c in COMPOSABLE_CHANNELS if c not in composed],
        can_compose=view.can_compose,
        blocked_reason=view.blocked_reason,
    )


# -------------------------------------------------------------------- reading
@router.get("/{campaign_id}/composition", response_model=CompositionView)
async def get_composition(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    storage: StorageDep,
    channel: Channel = DEFAULT_CHANNEL,
) -> CompositionView:
    """The current layout for a channel, its geometry report, and every final
    asset the campaign has rendered so far."""
    service = _service(principal, session, settings, storage)
    return _view(await service.current(_uuid(campaign_id, "Campaign"), channel=channel), link)


# ------------------------------------------------------------------ composing
@router.post(
    "/{campaign_id}/composition",
    response_model=CompositionView,
    status_code=status.HTTP_201_CREATED,
)
async def compose(
    campaign_id: str,
    body: ComposeRequest,
    principal: EditCampaignDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> CompositionView:
    """Build the default layout from the approved specification, the selected
    plate and the brand's approved logo.

    Idempotent: a channel that already has a layout keeps it. Rebuilding would
    throw away a human's edits without being asked.
    """
    service = _service(principal, session, settings, storage)
    view = await service.compose(_uuid(campaign_id, "Campaign"), channel=body.channel)
    await session.commit()
    return _view(view, link)


@router.post(
    "/{campaign_id}/composition/variants",
    response_model=CompositionView,
    status_code=status.HTTP_201_CREATED,
)
async def add_variant(
    campaign_id: str,
    body: VariantRequest,
    principal: EditCampaignDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> CompositionView:
    """Re-lay an existing composition into another channel's frame.

    The plate, the approved copy and the logo are identical to the source; only
    the geometry moves. Nothing is regenerated and no model is called.
    """
    service = _service(principal, session, settings, storage)
    view = await service.add_variant(
        _uuid(campaign_id, "Campaign"), channel=body.channel, source=body.source
    )
    await session.commit()
    return _view(view, link)


# -------------------------------------------------------------------- editing
@router.patch("/{campaign_id}/composition", response_model=CompositionView)
async def edit_composition(
    campaign_id: str,
    body: LayoutEditRequest,
    principal: EditCampaignDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    storage: StorageDep,
    channel: Channel = DEFAULT_CHANNEL,
) -> CompositionView:
    """Apply a constrained edit as a new layout version.

    Refused with a `400` and a sentence the UI can show when an edit would move
    something off the canvas, empty a text element, hide the logo or rewrite an
    approved call to action. Never partially applied — a half-applied edit
    leaves a user looking at a composition nobody asked for.
    """
    service = _service(principal, session, settings, storage)
    edits: dict[str, object] = {
        "elements": {key: value.changes() for key, value in body.elements.items()}
    }
    if body.background_color is not None:
        edits["background_color"] = body.background_color
    view = await service.edit(_uuid(campaign_id, "Campaign"), channel=channel, edits=edits)
    await session.commit()
    return _view(view, link)


# ------------------------------------------------------------------ rendering
@router.post(
    "/{campaign_id}/composition/render",
    response_model=FinalAssetView,
    status_code=status.HTTP_201_CREATED,
)
async def render_composition(
    campaign_id: str,
    body: RenderRequest,
    principal: EditCampaignDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> FinalAssetView:
    """Render the current layout into a new final asset.

    Synchronous on purpose. Composition is deterministic Pillow work measured in
    milliseconds, not a model call — a job row and a polling loop would be
    machinery with nothing to wait for.
    """
    service = _service(principal, session, settings, storage)
    row = await service.render_final(
        _uuid(campaign_id, "Campaign"), channel=body.channel, fmt=body.format
    )
    view = final_asset_view(row, link)
    await session.commit()
    return view


# --------------------------------------------------------------------- export
@router.get("/{campaign_id}/final-assets", response_model=FinalAssetList)
async def list_final_assets(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    storage: StorageDep,
    channel: Channel | None = None,
) -> FinalAssetList:
    """Every rendered deliverable, newest first. Old versions stay listed —
    history is the point."""
    service = _service(principal, session, settings, storage)
    rows = await service.final_assets(_uuid(campaign_id, "Campaign"), channel=channel)
    return FinalAssetList(items=[final_asset_view(row, link) for row in rows], total=len(rows))


@router.get("/{campaign_id}/final-assets/{asset_id}", response_model=FinalAssetView)
async def get_final_asset(
    campaign_id: str,
    asset_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> FinalAssetView:
    service = _service(principal, session, settings, storage)
    row = await service.scoped_final(_uuid(campaign_id, "Campaign"), _uuid(asset_id, "Final asset"))
    return final_asset_view(row, link)


@router.get("/{campaign_id}/final-assets/{asset_id}/content")
async def get_final_asset_content(
    campaign_id: str,
    asset_id: str,
    principal: Annotated[Principal, Depends(media_access(MediaKind.FINAL_ASSET, "asset_id"))],
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    download: bool = Query(default=False, description="Send as a file attachment."),
) -> Response:
    """Serve the rendered bytes, optionally as a download.

    The storage key comes from a scope-checked row and the filename is built
    from the row's own channel, version and mime type — nothing in either comes
    from the request, so no path can be traversed and no tenant's object can be
    addressed through another tenant's URL.
    """
    service = _service(principal, session, settings, storage)
    row = await service.scoped_final(_uuid(campaign_id, "Campaign"), _uuid(asset_id, "Final asset"))
    headers = {}
    if download:
        extension = _EXTENSIONS.get(row.mime_type, "bin")
        headers["Content-Disposition"] = (
            f'attachment; filename="{row.channel}-v{row.version}.{extension}"'
        )
    return Response(
        content=await storage.get(row.storage_key), media_type=row.mime_type, headers=headers
    )
