"""Campaign discovery endpoints.

Thin, like every other router: resolve scope, call the service, map to a typed
response. Campaign resolution goes through `CampaignDiscoveryService`, which
uses the organization-scoped repository — so another organization's campaign id
is a 404 here exactly as a project or brand id is.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile, status
from fastapi.responses import Response

from app.api.deps import (
    EmbeddingsDep,
    EvaluationRunnerDep,
    GenerationRunnerDep,
    GuardianRunnerDep,
    LLMDep,
    MediaLinkDep,
    PrincipalDep,
    SessionDep,
    SettingsDep,
    StorageDep,
    media_access,
)
from app.api.media_links import MediaKind, MediaLink
from app.api.routers.composition import final_asset_view
from app.api.schemas import (
    AnswerRequest,
    CampaignList,
    CampaignMessageView,
    CampaignOverviewView,
    CampaignReferenceView,
    CampaignSummary,
    ConversationView,
    CreateCampaignRequest,
    CreativeContextView,
    CreativeStageView,
    DimensionScoreView,
    DiscoveryTurnResponse,
    EditFieldChangeRequest,
    EditRevisionDeltaRequest,
    EvaluationDetailView,
    EvaluationView,
    FieldChangeView,
    GeneratedAssetView,
    GenerationJobView,
    GenerationView,
    GuardianCheckView,
    GuardianResultView,
    GuardianView,
    ModelPromptView,
    PreferencesView,
    ProposeRevisionRequest,
    RankedAssetView,
    RecommendationView,
    ReferenceList,
    RevisionDeltaView,
    RevisionRecordView,
    RevisionView,
    SelectCreativeRequest,
    SetPreferencesRequest,
    SpecificationDecisionRequest,
    SpecificationDiffView,
    StageStateView,
    StartEvaluationRequest,
    StartGuardianRequest,
    StrategyDecisionRequest,
    StyleOption,
    StyleOptionList,
    UpdateCreativeSpecificationRequest,
    UpdateSpecificationRequest,
)
from app.db.models import (
    BrandGuardianResultRow,
    CampaignReferenceRow,
    CampaignRow,
    CreativeEvaluationRow,
    GeneratedAssetRow,
    SpecificationRevisionRow,
)
from app.db.session import sessionmaker_for
from app.domain.campaign import CampaignBrief
from app.domain.common import Channel, JobStatus
from app.domain.creative import CreativeSpecification
from app.domain.evaluation import DIMENSION_WEIGHTS, EVALUATOR_VERSION, CreativeEvaluation
from app.domain.generation import AssetKind
from app.domain.guardian import BrandGuardianResult, GuardianVerdict
from app.domain.reference import ReferenceAnalysis, ReferenceStatus
from app.domain.revision import FieldChange, RevisionDelta, RevisionStatus
from app.domain.workspace import Principal
from app.errors import Conflict, NotFound, ValidationFailed
from app.repositories.campaigns import (
    CampaignMessageRepository,
    CampaignReferenceRepository,
    CampaignRepository,
    CampaignSpecificationRepository,
)
from app.repositories.evaluation import CreativeEvaluationRepository
from app.repositories.generation import GeneratedAssetRepository
from app.services.campaigns import CampaignDiscoveryService, DiscoveryTurn
from app.services.creative_context import CreativeContextService
from app.services.creative_stage import CreativeStageService, CreativeTurn
from app.services.evaluation_stage import EvaluationService
from app.services.evaluation_stage import EvaluationView as ServiceEvaluationView
from app.services.generation import GenerationService
from app.services.generation import GenerationView as ServiceGenerationView
from app.services.overview import CampaignOverviewService
from app.services.reference_intelligence import ReferenceIntelligenceService
from app.services.revision_stage import GuardianView as ServiceGuardianView
from app.services.revision_stage import RevisionStageService
from app.services.revision_stage import RevisionView as ServiceRevisionView
from app.services.uploads import IMAGE_MIMES, storage_key_for, validate_upload

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

#: The visual calibration picker. Plain language so someone without design
#: vocabulary can choose (PRODUCT_SPEC §10).
STYLE_OPTIONS: tuple[dict[str, str], ...] = (
    {
        "style": "premium",
        "label": "Premium",
        "description": "Restrained, considered, expensive-feeling.",
    },
    {"style": "minimal", "label": "Minimal", "description": "Lots of space, very few elements."},
    {
        "style": "technical",
        "label": "Technical",
        "description": "Precise, diagrammatic, engineering-led.",
    },
    {
        "style": "cinematic",
        "label": "Cinematic",
        "description": "Dramatic light, depth, a sense of scene.",
    },
    {
        "style": "bold",
        "label": "Bold",
        "description": "High contrast, big type, impossible to miss.",
    },
    {"style": "festive", "label": "Festive", "description": "Warm, celebratory, occasion-led."},
    {
        "style": "local_cultural",
        "label": "Local / cultural",
        "description": "Rooted in a specific place and its visual language.",
    },
    {
        "style": "editorial",
        "label": "Editorial",
        "description": "Magazine-like: strong grid, considered typography.",
    },
)


def _uuid(raw: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise NotFound(f"{what} not found.") from exc


def _summary(row: CampaignRow) -> CampaignSummary:
    return CampaignSummary(
        id=str(row.id),
        organization_id=str(row.organization_id),
        brand_id=str(row.brand_profile_id),
        project_id=str(row.project_id) if row.project_id else None,
        title=row.title,
        status=row.status,
        created_at=row.created_at,
    )


def _turn(turn: DiscoveryTurn) -> DiscoveryTurnResponse:
    return DiscoveryTurnResponse(
        campaign_id=turn.campaign_id,
        status=turn.status,
        question=turn.question,
        missing=turn.missing,
        turn=turn.turn,
        interview_complete=turn.interview_complete,
        specification=turn.specification,
        known=turn.inputs,
    )


def _reference(row: CampaignReferenceRow, link: MediaLink) -> CampaignReferenceView:
    return CampaignReferenceView(
        id=str(row.id),
        filename=row.filename,
        mime_type=row.mime_type,
        bytes=row.bytes,
        note=row.note,
        # Served through the API so scope is checked on read; the browser never
        # addresses storage directly. Signed and short-lived, because an
        # `<img src>` cannot carry the headers that normally prove scope.
        url=link.reference(row.campaign_id, row.id),
        status=ReferenceStatus(row.status),
        analysis=ReferenceAnalysis.model_validate(row.analysis) if row.analysis else None,
        error=row.error,
        accepted=row.accepted_at is not None,
    )


def _service(
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> CampaignDiscoveryService:
    return CampaignDiscoveryService(
        session, principal, settings=settings, llm=llm, embeddings=embeddings
    )


# ------------------------------------------------------------------------ CRUD
@router.get("", response_model=CampaignList)
async def list_campaigns(
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    brand_id: str | None = None,
) -> CampaignList:
    service = _service(principal, session, settings, llm, embeddings)
    rows = await service.campaigns.list_all(brand_id=_uuid(brand_id, "Brand") if brand_id else None)
    return CampaignList(items=[_summary(r) for r in rows])


@router.post("", response_model=CampaignSummary, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CreateCampaignRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> CampaignSummary:
    service = _service(principal, session, settings, llm, embeddings)
    row = await service.create(
        brand_id=_uuid(body.brand_id, "Brand"),
        title=body.title,
        project_id=_uuid(body.project_id, "Project") if body.project_id else None,
    )
    return _summary(row)


@router.get("/{campaign_id}", response_model=CampaignSummary)
async def get_campaign(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> CampaignSummary:
    service = _service(principal, session, settings, llm, embeddings)
    return _summary(await service.get_row(_uuid(campaign_id, "Campaign")))


# ------------------------------------------------------------------- discovery
@router.post("/{campaign_id}/discovery/start", response_model=DiscoveryTurnResponse)
async def start_discovery(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> DiscoveryTurnResponse:
    """Start or re-enter the interview.

    Safe to call again after a refresh: the graph resumes from its checkpoint
    rather than starting over.
    """
    service = _service(principal, session, settings, llm, embeddings)
    return _turn(await service.start(_uuid(campaign_id, "Campaign")))


@router.post("/{campaign_id}/discovery/answer", response_model=DiscoveryTurnResponse)
async def answer_question(
    campaign_id: str,
    body: AnswerRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> DiscoveryTurnResponse:
    service = _service(principal, session, settings, llm, embeddings)
    return _turn(await service.answer(_uuid(campaign_id, "Campaign"), body.answer))


@router.get("/{campaign_id}/conversation", response_model=ConversationView)
async def get_conversation(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> ConversationView:
    service = _service(principal, session, settings, llm, embeddings)
    campaign = await service.get_row(_uuid(campaign_id, "Campaign"))
    repo = CampaignMessageRepository(session, uuid.UUID(principal.organization_id))
    return ConversationView(
        items=[
            CampaignMessageView(
                id=str(m.id),
                role=m.role,
                content=m.content,
                targets_field=m.targets_field,
                created_at=m.created_at,
            )
            for m in await repo.list_for_campaign(campaign.id)
        ]
    )


# --------------------------------------------------------------- specification
@router.get("/{campaign_id}/specification", response_model=CampaignBrief)
async def get_specification(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> CampaignBrief:
    service = _service(principal, session, settings, llm, embeddings)
    campaign = await service.get_row(_uuid(campaign_id, "Campaign"))
    repo = CampaignSpecificationRepository(session, uuid.UUID(principal.organization_id))
    latest = await repo.latest(campaign.id)
    if latest is None:
        raise NotFound("This campaign has no specification yet.")
    return CampaignBrief.model_validate(latest.payload)


@router.patch("/{campaign_id}/specification", response_model=CampaignBrief)
async def update_specification(
    campaign_id: str,
    body: UpdateSpecificationRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> CampaignBrief:
    edits = body.model_dump(exclude_unset=True, mode="json")
    if not edits:
        raise ValidationFailed("Nothing to update.", details={"field": "body"})
    service = _service(principal, session, settings, llm, embeddings)
    return await service.update_specification(_uuid(campaign_id, "Campaign"), edits)


@router.post("/{campaign_id}/specification/confirm", response_model=CampaignBrief)
async def confirm_specification(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> CampaignBrief:
    """Close discovery. Milestone 3 stops here — nothing creative runs."""
    service = _service(principal, session, settings, llm, embeddings)
    return await service.confirm_specification(_uuid(campaign_id, "Campaign"))


# ------------------------------------------------------------------ references
@router.get("/{campaign_id}/references", response_model=ReferenceList)
async def list_references(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> ReferenceList:
    service = _service(principal, session, settings, llm, embeddings)
    campaign = await service.get_row(_uuid(campaign_id, "Campaign"))
    repo = CampaignReferenceRepository(session, uuid.UUID(principal.organization_id))
    return ReferenceList(
        items=[_reference(r, link) for r in await repo.list_for_campaign(campaign.id)]
    )


@router.post(
    "/{campaign_id}/references",
    response_model=CampaignReferenceView,
    status_code=status.HTTP_201_CREATED,
)
async def upload_reference(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    storage: StorageDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    file: UploadFile = File(...),
    note: str | None = Form(default=None),
) -> CampaignReferenceView:
    """Persist a reference image.

    Stored and nothing more — style analysis is Milestone 4's job, and doing it
    here would be inventing an interpretation nobody asked for yet.
    """
    service = _service(principal, session, settings, llm, embeddings)
    campaign = await service.get_row(_uuid(campaign_id, "Campaign"))
    upload = validate_upload(
        await file.read(),
        declared_mime=file.content_type,
        filename=file.filename,
        allowed=frozenset(IMAGE_MIMES),
        max_bytes=settings.max_upload_bytes,
    )
    organization_id = uuid.UUID(principal.organization_id)
    key = storage_key_for(
        organization_id=organization_id,
        brand_id=campaign.id,
        kind="references",
        extension=upload.filename.rsplit(".", 1)[-1] if "." in upload.filename else "bin",
    )
    await storage.put(key, upload.data, mime_type=upload.mime_type)
    repo = CampaignReferenceRepository(session, organization_id)
    row = await repo.create(
        campaign_id=campaign.id,
        storage_key=key,
        filename=upload.filename,
        mime_type=upload.mime_type,
        size_bytes=upload.size_bytes,
        note=note,
        content_sha256=upload.sha256,
    )
    # Analyse inline: a single image is fast on any provider, and a reference
    # the user cannot immediately see the reading of is a worse experience
    # than a brief wait. Failure is a recorded state, never an exception.
    intelligence = ReferenceIntelligenceService(session, organization_id, storage=storage, llm=llm)
    analysed = await intelligence.analyze(row.id)
    return _reference(analysed or row, link)


@router.get("/{campaign_id}/references/{reference_id}/content")
async def get_reference_content(
    campaign_id: str,
    reference_id: str,
    principal: Annotated[Principal, Depends(media_access(MediaKind.REFERENCE, "reference_id"))],
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> Response:
    """Serve reference bytes. The storage key comes from a scope-checked row.

    The caller proves themselves with the usual headers or with a signed link
    bound to this reference; either way `principal` is a real, membership-
    checked principal by the time the body runs, and the lookup below is
    unchanged."""
    service = _service(principal, session, settings, llm, embeddings)
    campaign = await service.get_row(_uuid(campaign_id, "Campaign"))
    repo = CampaignReferenceRepository(session, uuid.UUID(principal.organization_id))
    row = await repo.get(_uuid(reference_id, "Reference"))
    if row is None or row.campaign_id != campaign.id:
        raise NotFound("Reference not found.")
    return Response(content=await storage.get(row.storage_key), media_type=row.mime_type)


@router.post(
    "/{campaign_id}/references/{reference_id}/analyze", response_model=CampaignReferenceView
)
async def reanalyze_reference(
    campaign_id: str,
    reference_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    storage: StorageDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> CampaignReferenceView:
    """Re-run the analysis for one reference.

    `force` is set: the caller is explicitly asking for a fresh reading, which
    is the one case where paying for another multimodal call is the point.
    """
    service = _service(principal, session, settings, llm, embeddings)
    campaign = await service.get_row(_uuid(campaign_id, "Campaign"))
    organization_id = uuid.UUID(principal.organization_id)
    repo = CampaignReferenceRepository(session, organization_id)
    row = await repo.get(_uuid(reference_id, "Reference"))
    if row is None or row.campaign_id != campaign.id:
        raise NotFound("Reference not found.")

    intelligence = ReferenceIntelligenceService(session, organization_id, storage=storage, llm=llm)
    return _reference(await intelligence.analyze(row.id, force=True) or row, link)


@router.post(
    "/{campaign_id}/references/{reference_id}/accept", response_model=CampaignReferenceView
)
async def accept_reference_analysis(
    campaign_id: str,
    reference_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> CampaignReferenceView:
    """A human agrees with the extracted characteristics."""
    service = _service(principal, session, settings, llm, embeddings)
    campaign = await service.get_row(_uuid(campaign_id, "Campaign"))
    repo = CampaignReferenceRepository(session, uuid.UUID(principal.organization_id))
    row = await repo.get(_uuid(reference_id, "Reference"))
    if row is None or row.campaign_id != campaign.id:
        raise NotFound("Reference not found.")
    if row.status != ReferenceStatus.COMPLETED.value:
        raise ValidationFailed(
            "This reference has not been analysed yet.", details={"field": "reference_id"}
        )
    return _reference(await repo.accept(row), link)


# --------------------------------------------------------------- preferences
@router.get("/{campaign_id}/preferences/options", response_model=StyleOptionList)
async def list_style_options(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> StyleOptionList:
    """The visual directions a user can pick between.

    Described in plain language so someone without design vocabulary can
    choose (PRODUCT_SPEC §10).
    """
    service = _service(principal, session, settings, llm, embeddings)
    await service.get_row(_uuid(campaign_id, "Campaign"))
    return StyleOptionList(items=[StyleOption(**option) for option in STYLE_OPTIONS])


@router.get("/{campaign_id}/preferences", response_model=PreferencesView)
async def get_preferences(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> PreferencesView:
    service = _service(principal, session, settings, llm, embeddings)
    campaign = await service.get_row(_uuid(campaign_id, "Campaign"))
    context = CreativeContextService(
        session,
        uuid.UUID(principal.organization_id),
        storage=storage,
        llm=llm,
        embeddings=embeddings,
    )
    preferences = await context.preferences_for(campaign)
    return PreferencesView(
        preferences=preferences,
        profile=preferences.style_profile.top(5),
        summary=preferences.style_profile.describe(),
    )


@router.put("/{campaign_id}/preferences", response_model=PreferencesView)
async def set_preferences(
    campaign_id: str,
    body: SetPreferencesRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> PreferencesView:
    """Store the user's picks. Weights are derived, never supplied."""
    from app.domain.reference import CreativePreferences

    service = _service(principal, session, settings, llm, embeddings)
    campaign = await service.get_row(_uuid(campaign_id, "Campaign"))
    context = CreativeContextService(
        session,
        uuid.UUID(principal.organization_id),
        storage=storage,
        llm=llm,
        embeddings=embeddings,
    )
    saved = await context.save_preferences(
        campaign,
        CreativePreferences(
            selected_styles=body.selected_styles,
            liked_reference_ids=body.liked_reference_ids,
            disliked_reference_ids=body.disliked_reference_ids,
            color_preference=body.color_preference,
            avoid=body.avoid,
            free_text=body.free_text,
        ),
    )
    return PreferencesView(
        preferences=saved,
        profile=saved.style_profile.top(5),
        summary=saved.style_profile.describe(),
    )


# ----------------------------------------------------------- creative context
@router.get("/{campaign_id}/creative-context", response_model=CreativeContextView)
async def get_creative_context(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> CreativeContextView:
    """Brand + specification + reference style + preferences, assembled.

    This is what the Creative Director will consume in Milestone 5.
    """
    service = _service(principal, session, settings, llm, embeddings)
    campaign = await service.get_row(_uuid(campaign_id, "Campaign"))
    builder = CreativeContextService(
        session,
        uuid.UUID(principal.organization_id),
        storage=storage,
        llm=llm,
        embeddings=embeddings,
    )
    context = await builder.build(campaign)
    return CreativeContextView(
        context=context, summary=context.summarise(), ready=context.is_ready()
    )


# --------------------------------------------------------------- creative stage
def _creative(
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> CreativeStageService:
    return CreativeStageService(
        session, principal, settings=settings, llm=llm, embeddings=embeddings, storage=storage
    )


def _creative_view(turn: CreativeTurn) -> CreativeStageView:
    return CreativeStageView(
        campaign_id=turn.campaign_id,
        gate=turn.gate,
        direction_set=turn.direction_set,
        selected_direction_id=turn.selected_direction_id,
        specification=turn.specification,
        diversity=turn.diversity,
        approved=turn.approved,
        gaps=turn.gaps,
        channels=turn.channels,
    )


@router.get("/{campaign_id}/creative", response_model=CreativeStageView)
async def get_creative_stage(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> CreativeStageView:
    """Read-only: where the creative stage stands."""
    service = _creative(principal, session, settings, llm, embeddings, storage)
    return _creative_view(await service.current(_uuid(campaign_id, "Campaign")))


@router.post("/{campaign_id}/creative/start", response_model=CreativeStageView)
async def start_creative_stage(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> CreativeStageView:
    """Generate creative directions.

    Safe to call again: an existing stage is resumed from its checkpoint
    rather than restarted.
    """
    service = _creative(principal, session, settings, llm, embeddings, storage)
    return _creative_view(await service.start(_uuid(campaign_id, "Campaign")))


@router.post("/{campaign_id}/creative/strategy", response_model=CreativeStageView)
async def decide_strategy(
    campaign_id: str,
    body: StrategyDecisionRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> CreativeStageView:
    """Gate 1 — approve a direction, reject the set, or request changes."""
    service = _creative(principal, session, settings, llm, embeddings, storage)
    return _creative_view(
        await service.decide_strategy(
            _uuid(campaign_id, "Campaign"),
            decision=body.decision,
            direction_id=body.direction_id,
            feedback=body.feedback,
        )
    )


@router.patch("/{campaign_id}/creative/specification", response_model=CreativeSpecification)
async def edit_creative_specification(
    campaign_id: str,
    body: UpdateCreativeSpecificationRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> CreativeSpecification:
    edits = body.model_dump(exclude_unset=True, mode="json")
    if not edits:
        raise ValidationFailed("Nothing to update.", details={"field": "body"})
    service = _creative(principal, session, settings, llm, embeddings, storage)
    return await service.edit_specification(_uuid(campaign_id, "Campaign"), edits)


@router.post("/{campaign_id}/creative/specification/decide", response_model=CreativeStageView)
async def decide_specification(
    campaign_id: str,
    body: SpecificationDecisionRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> CreativeStageView:
    """Gate 2 — approve the execution plan.

    Milestone 5 stops here. Nothing is generated on approval; Milestone 6
    picks the approved specification up from the database.
    """
    service = _creative(principal, session, settings, llm, embeddings, storage)
    return _creative_view(
        await service.decide_specification(
            _uuid(campaign_id, "Campaign"), decision=body.decision, feedback=body.feedback
        )
    )


# ------------------------------------------------------------------ generation
def _generation(
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> GenerationService:
    return GenerationService(
        session, principal, settings=settings, storage=storage, llm=llm, embeddings=embeddings
    )


def _generation_view(
    view: ServiceGenerationView, campaign_id: str, link: MediaLink
) -> GenerationView:
    batch = view.batch
    return GenerationView(
        campaign_id=view.campaign_id,
        batch_id=view.batch_id,
        canonical_prompt=view.canonical_prompt,
        prompts=[
            ModelPromptView(
                id=prompt.id,
                provider=prompt.provider,
                model=prompt.model,
                version=prompt.version,
                text=prompt.text,
                negative_text=prompt.negative_text,
                aspect_ratio=prompt.aspect_ratio,
                specification_version=prompt.specification_version,
                trace=prompt.trace(),
            )
            for prompt in view.prompts
        ],
        jobs=[
            GenerationJobView(
                id=job.id,
                provider=job.provider,
                model=job.model,
                status=job.status,
                attempt=job.attempt,
                can_retry=job.can_retry(),
                error_message=job.error.message if job.error else None,
                error_code=job.error.code if job.error else None,
                started_at=job.started_at,
                finished_at=job.finished_at,
                created_at=job.created_at,
            )
            for job in (batch.jobs if batch else [])
        ],
        assets=[
            GeneratedAssetView(
                id=asset.id,
                generation_job_id=asset.generation_job_id,
                provider=asset.provider,
                model=asset.model,
                kind=asset.kind,
                width=asset.width,
                height=asset.height,
                mime_type=asset.mime_type,
                # A path, not a storage URL: the bytes are served through the
                # API so the organization scope is checked on every read. The
                # signature is how a browser proves that scope on an `<img>`.
                url=link.generated_asset(campaign_id, asset.id),
                specification_version=asset.specification_version,
                created_at=asset.created_at,
            )
            for asset in (batch.assets if batch else [])
        ],
        outcome=batch.outcome() if batch else "Nothing generated yet.",
        complete=batch.is_complete() if batch else False,
        specification_version=view.specification_version,
        can_generate=view.can_generate,
        blocked_reason=view.blocked_reason,
    )


@router.get("/{campaign_id}/generation", response_model=GenerationView)
async def get_generation(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> GenerationView:
    """Read-only: compiled prompts, job states and the plates so far.

    This is the polling endpoint — the frontend calls it while any job is
    still running (API_SPEC §Polling contract).
    """
    service = _generation(principal, session, settings, llm, embeddings, storage)
    return _generation_view(
        await service.current(_uuid(campaign_id, "Campaign")), campaign_id, link
    )


@router.post("/{campaign_id}/generation/compile", response_model=GenerationView)
async def compile_prompts(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> GenerationView:
    """Compile the approved specification into prompts, without generating.

    Deliberately separate from starting a batch: a user can read exactly what
    each provider will be asked before any credit is spent.
    """
    service = _generation(principal, session, settings, llm, embeddings, storage)
    return _generation_view(
        await service.compile_prompts(_uuid(campaign_id, "Campaign")), campaign_id, link
    )


@router.post("/{campaign_id}/generation/start", response_model=GenerationView, status_code=202)
async def start_generation(
    campaign_id: str,
    background: BackgroundTasks,
    runner: GenerationRunnerDep,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> GenerationView:
    """Start one generation job per configured provider.

    Returns 202 with the jobs still `PENDING`: the providers are called after
    the response is sent, so the request never blocks on an image model. The
    frontend polls `GET /generation` until every job is terminal.
    """
    service = _generation(principal, session, settings, llm, embeddings, storage)
    view, batch_id = await service.start(_uuid(campaign_id, "Campaign"))

    # Commit before scheduling. The background task opens its own session, and
    # without this it can start before the request's transaction commits and
    # find no jobs at all — they stay PENDING forever. Committing here also
    # means the rows are durable before anything is told to run them, so a
    # crash in between loses nothing that was not already recorded.
    await session.commit()

    pending = [
        uuid.UUID(job.id)
        for job in (view.batch.jobs if view.batch else [])
        if job.status is JobStatus.PENDING
    ]
    if pending:
        background.add_task(
            runner,
            sessionmaker_for(settings.database_url),
            principal=principal,
            settings=settings,
            storage=storage,
            llm=llm,
            embeddings=embeddings,
            job_ids=pending,
        )
    return _generation_view(view, campaign_id, link)


@router.post(
    "/{campaign_id}/generation/jobs/{job_id}/retry",
    response_model=GenerationView,
    status_code=202,
)
async def retry_generation_job(
    campaign_id: str,
    job_id: str,
    background: BackgroundTasks,
    runner: GenerationRunnerDep,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> GenerationView:
    """Re-run one failed job as a new attempt.

    A new attempt is a new charge — which is what the user is asking for.
    Retrying anything but a failure is a conflict.
    """
    service = _generation(principal, session, settings, llm, embeddings, storage)
    campaign_uuid = _uuid(campaign_id, "Campaign")
    new_job_id = await service.retry(campaign_uuid, _uuid(job_id, "Generation job"))
    # Durable before it is scheduled — same reason as `start_generation`.
    await session.commit()
    background.add_task(
        runner,
        sessionmaker_for(settings.database_url),
        principal=principal,
        settings=settings,
        storage=storage,
        llm=llm,
        embeddings=embeddings,
        job_ids=[new_job_id],
    )
    return _generation_view(await service.current(campaign_uuid), campaign_id, link)


@router.get("/{campaign_id}/assets", response_model=GenerationView)
async def list_generated_assets(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> GenerationView:
    """The gallery. Same shape as `GET /generation` so one client type covers
    both, and a plate always arrives with the job that produced it."""
    service = _generation(principal, session, settings, llm, embeddings, storage)
    return _generation_view(
        await service.current(_uuid(campaign_id, "Campaign")), campaign_id, link
    )


@router.get("/{campaign_id}/assets/{asset_id}", response_model=GeneratedAssetView)
async def get_generated_asset(
    campaign_id: str,
    asset_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
) -> GeneratedAssetView:
    """One plate's metadata."""
    asset = await _scoped_asset(principal, session, campaign_id, asset_id)
    return GeneratedAssetView(
        id=str(asset.id),
        generation_job_id=str(asset.generation_job_id),
        provider=asset.provider,
        model=asset.model,
        kind=AssetKind(asset.kind),
        width=asset.width,
        height=asset.height,
        mime_type=asset.mime_type,
        url=link.generated_asset(campaign_id, asset.id),
        specification_version=asset.specification_version,
        created_at=asset.created_at,
    )


@router.get("/{campaign_id}/assets/{asset_id}/content")
async def get_generated_asset_content(
    campaign_id: str,
    asset_id: str,
    principal: Annotated[Principal, Depends(media_access(MediaKind.GENERATED_ASSET, "asset_id"))],
    session: SessionDep,
    storage: StorageDep,
) -> Response:
    """Serve the bytes. The storage key comes from a scope-checked row, never
    from the request — the same rule as campaign references.

    Reachable by headers or by a signed link bound to this asset, because an
    `<img src>` can send neither header."""
    asset = await _scoped_asset(principal, session, campaign_id, asset_id)
    return Response(content=await storage.get(asset.storage_key), media_type=asset.mime_type)


async def _scoped_asset(
    principal: Principal, session: SessionDep, campaign_id: str, asset_id: str
) -> GeneratedAssetRow:
    """An asset that belongs to this organization *and* to this campaign.

    Both checks matter: the repository scope stops another tenant's asset, and
    the campaign comparison stops an asset id from one campaign being read
    through another campaign's URL.
    """
    organization_id = uuid.UUID(principal.organization_id)
    campaign = await CampaignRepository(session, organization_id).get(
        _uuid(campaign_id, "Campaign")
    )
    if campaign is None:
        raise NotFound("Campaign not found.")
    asset = await GeneratedAssetRepository(session, organization_id).get(_uuid(asset_id, "Asset"))
    if asset is None or asset.campaign_id != campaign.id:
        raise NotFound("Asset not found.")
    return asset


# ------------------------------------------------------------------ evaluation
def _evaluation(
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> EvaluationService:
    return EvaluationService(
        session, principal, settings=settings, storage=storage, llm=llm, embeddings=embeddings
    )


def _dimension_views(evaluation: CreativeEvaluation) -> list[DimensionScoreView]:
    return [
        DimensionScoreView(
            dimension=result.dimension,
            label=result.dimension.value.replace("_", " ").capitalize(),
            score=result.score,
            note=result.note,
            weight=DIMENSION_WEIGHTS.get(result.dimension, 0.0),
        )
        for result in evaluation.dimensions
    ]


def _detail_view(row: CreativeEvaluationRow) -> EvaluationDetailView:
    """One evaluation row, whatever state it is in.

    A pending or failed row renders with no scores rather than being omitted —
    a missing card is a silent gap, and the UI must never have one.
    """
    status = JobStatus(row.status)
    evaluation = (
        CreativeEvaluation.model_validate(row.payload)
        if row.payload and status is JobStatus.COMPLETED
        else None
    )
    error = row.error or {}
    return EvaluationDetailView(
        id=str(row.id),
        generated_asset_id=str(row.generated_asset_id),
        status=status,
        evaluator_version=row.evaluator_version,
        evaluator_model=row.evaluator_model,
        specification_version=row.specification_version,
        dimensions=_dimension_views(evaluation) if evaluation else [],
        overall_score=evaluation.overall_score if evaluation else None,
        disposition=evaluation.disposition if evaluation else None,
        disposition_reasons=list(evaluation.disposition_reasons) if evaluation else [],
        strengths=list(evaluation.strengths) if evaluation else [],
        concerns=list(evaluation.concerns) if evaluation else [],
        rationale=evaluation.rationale if evaluation else "",
        error_message=str(error.get("message")) if error.get("message") else None,
        error_code=str(error.get("code")) if error.get("code") else None,
        can_retry=status is JobStatus.FAILED,
        evaluated_at=evaluation.evaluated_at if evaluation else None,
    )


async def _evaluation_view(
    view: ServiceEvaluationView,
    campaign_id: str,
    principal: Principal,
    session: SessionDep,
    link: MediaLink,
) -> EvaluationView:
    """Join the ranking to the plates it describes, in one response."""
    organization_id = uuid.UUID(principal.organization_id)
    rows = await CreativeEvaluationRepository(session, organization_id).for_campaign(
        uuid.UUID(view.campaign_id), evaluator_version=EVALUATOR_VERSION
    )
    assets = {
        str(row.id): row
        for row in await GeneratedAssetRepository(session, organization_id).for_campaign(
            uuid.UUID(view.campaign_id)
        )
    }

    summary = view.summary
    return EvaluationView(
        campaign_id=view.campaign_id,
        evaluator_version=summary.evaluator_version,
        ranked=[
            RankedAssetView(
                rank=row.rank,
                generated_asset_id=row.generated_asset_id,
                evaluation_id=row.evaluation_id,
                overall_score=row.overall_score,
                disposition=row.disposition,
                reason=row.reason,
                recommended=row.recommended,
                asset=(
                    _asset_view(assets[row.generated_asset_id], campaign_id, link)
                    if row.generated_asset_id in assets
                    else None
                ),
            )
            for row in summary.ranked
        ],
        recommendation=(
            RecommendationView(**summary.recommendation.model_dump())
            if summary.recommendation
            else None
        ),
        evaluations=[_detail_view(row) for row in rows],
        outcome=summary.outcome(),
        in_flight=view.in_flight,
        unevaluated_asset_ids=view.unevaluated_asset_ids,
        selected_asset_id=summary.selected_asset_id,
        can_evaluate=view.can_evaluate,
        blocked_reason=view.blocked_reason,
    )


def _asset_view(row: GeneratedAssetRow, campaign_id: str, link: MediaLink) -> GeneratedAssetView:
    return GeneratedAssetView(
        id=str(row.id),
        generation_job_id=str(row.generation_job_id),
        provider=row.provider,
        model=row.model,
        kind=AssetKind(row.kind),
        width=row.width,
        height=row.height,
        mime_type=row.mime_type,
        url=link.generated_asset(campaign_id, row.id),
        specification_version=row.specification_version,
        created_at=row.created_at,
    )


@router.get("/{campaign_id}/evaluation", response_model=EvaluationView)
async def get_evaluation(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> EvaluationView:
    """Read-only: scores, ranking, recommendation and the current selection.

    The polling endpoint — the client calls it while `in_flight` is non-zero
    (API_SPEC §Polling contract).
    """
    service = _evaluation(principal, session, settings, llm, embeddings, storage)
    view = await service.current(_uuid(campaign_id, "Campaign"))
    return await _evaluation_view(view, campaign_id, principal, session, link)


@router.post("/{campaign_id}/evaluation/start", response_model=EvaluationView, status_code=202)
async def start_evaluation(
    campaign_id: str,
    body: StartEvaluationRequest,
    background: BackgroundTasks,
    runner: EvaluationRunnerDep,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> EvaluationView:
    """Evaluate the campaign's generated plates.

    Returns 202 with every evaluation still `PENDING`: the model is called
    after the response is sent, so the request never blocks on it. The client
    polls `GET /evaluation` until `in_flight` reaches zero.
    """
    service = _evaluation(principal, session, settings, llm, embeddings, storage)
    campaign_uuid = _uuid(campaign_id, "Campaign")
    asset_ids = (
        [_uuid(value, "Generated asset") for value in body.asset_ids]
        if body.asset_ids is not None
        else None
    )
    view, claimed = await service.start(campaign_uuid, asset_ids=asset_ids)

    # Durable before it is scheduled: the background task opens its own
    # session, and without this it can start before this transaction commits
    # and find nothing to do (the Milestone 6 defect).
    await session.commit()
    if claimed:
        background.add_task(
            runner,
            sessionmaker_for(settings.database_url),
            principal=principal,
            settings=settings,
            storage=storage,
            llm=llm,
            embeddings=embeddings,
            evaluation_ids=claimed,
        )
    return await _evaluation_view(view, campaign_id, principal, session, link)


@router.post(
    "/{campaign_id}/evaluation/{evaluation_id}/retry",
    response_model=EvaluationView,
    status_code=202,
)
async def retry_evaluation(
    campaign_id: str,
    evaluation_id: str,
    background: BackgroundTasks,
    runner: EvaluationRunnerDep,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> EvaluationView:
    """Re-run one failed evaluation. Retrying anything else is a conflict."""
    service = _evaluation(principal, session, settings, llm, embeddings, storage)
    campaign_uuid = _uuid(campaign_id, "Campaign")
    claimed = await service.retry(campaign_uuid, _uuid(evaluation_id, "Evaluation"))
    await session.commit()
    background.add_task(
        runner,
        sessionmaker_for(settings.database_url),
        principal=principal,
        settings=settings,
        storage=storage,
        llm=llm,
        embeddings=embeddings,
        evaluation_ids=[claimed],
    )
    return await _evaluation_view(
        await service.current(campaign_uuid), campaign_id, principal, session, link
    )


@router.post("/{campaign_id}/evaluation/select", response_model=EvaluationView)
async def select_creative(
    campaign_id: str,
    body: SelectCreativeRequest,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> EvaluationView:
    """Record the human's final choice.

    Any asset in the campaign may be chosen. The ranking is advice; the person
    is the decision-maker, and one who disagrees with the recommendation must
    still be able to act.
    """
    service = _evaluation(principal, session, settings, llm, embeddings, storage)
    campaign_uuid = _uuid(campaign_id, "Campaign")
    view = await service.select(
        campaign_uuid,
        _uuid(body.generated_asset_id, "Generated asset"),
        note=body.note,
    )
    return await _evaluation_view(view, campaign_id, principal, session, link)


# ------------------------------------------------------- guardian and revision
def _revision(
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> RevisionStageService:
    return RevisionStageService(
        session, principal, settings=settings, storage=storage, llm=llm, embeddings=embeddings
    )


def _label_of(name: str) -> str:
    return name.replace("_", " ").capitalize()


def _guardian_result_view(
    row: BrandGuardianResultRow,
    campaign_id: str,
    asset: GeneratedAssetRow | None,
    link: MediaLink,
) -> GuardianResultView:
    """One row, whatever state it is in.

    A pending or failed check renders with no verdict rather than being
    omitted — a missing card is a silent gap, and an outage must never look
    like brand approval.
    """
    status = JobStatus(row.status)
    result = (
        BrandGuardianResult.model_validate(row.payload)
        if row.payload and status is JobStatus.COMPLETED
        else None
    )
    error = row.error or {}
    return GuardianResultView(
        id=str(row.id),
        generated_asset_id=str(row.generated_asset_id),
        status=status,
        guardian_version=row.guardian_version,
        guardian_model=row.guardian_model,
        specification_version=row.specification_version,
        verdict=result.verdict if result else None,
        checks=[
            GuardianCheckView(
                check=check.check,
                label=_label_of(check.check.value),
                status=check.status,
                severity=check.severity,
                detail=check.detail,
                suggested_fix=check.suggested_fix,
                deterministic=check.deterministic,
            )
            for check in (result.checks if result else [])
        ],
        critical_issues=list(result.critical_issues) if result else [],
        warnings=list(result.warnings) if result else [],
        summary=result.summary if result else "",
        error_message=str(error.get("message")) if error.get("message") else None,
        error_code=str(error.get("code")) if error.get("code") else None,
        can_retry=status is JobStatus.FAILED,
        evaluated_at=result.evaluated_at if result else None,
        asset=_asset_view(asset, campaign_id, link) if asset is not None else None,
    )


async def _guardian_view(
    view: ServiceGuardianView,
    campaign_id: str,
    principal: Principal,
    session: SessionDep,
    link: MediaLink,
) -> GuardianView:
    organization_id = uuid.UUID(principal.organization_id)
    assets = {
        str(row.id): row
        for row in await GeneratedAssetRepository(session, organization_id).for_campaign(
            uuid.UUID(view.campaign_id)
        )
    }
    return GuardianView(
        campaign_id=view.campaign_id,
        guardian_version=view.guardian_version,
        results=[
            _guardian_result_view(row, campaign_id, assets.get(str(row.generated_asset_id)), link)
            for row in view.results
        ],
        in_flight=view.in_flight,
        unchecked_asset_ids=view.unchecked_asset_ids,
        can_check=view.can_check,
        blocked_reason=view.blocked_reason,
    )


def _change_views(
    items: list[FieldChange], source: CreativeSpecification | None
) -> list[FieldChangeView]:
    """Each change with the value it replaces, so the UI shows before and after."""
    return [
        FieldChangeView(
            field=item.field,
            label=_label_of(item.field),
            action=item.action,
            reason=item.reason,
            new_value=item.new_value,
            current_value=_render(getattr(source, item.field, None)) if source else None,
        )
        for item in items
    ]


def _render(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _delta_view(delta: RevisionDelta, source: CreativeSpecification | None) -> RevisionDeltaView:
    return RevisionDeltaView(
        iteration=delta.iteration,
        user_feedback=delta.user_feedback,
        interpretation=delta.interpretation,
        keep=list(delta.keep),
        change=_change_views(delta.change, source),
        add=_change_views(delta.add, source),
        remove=_change_views(delta.remove, source),
        explicit_unlocks=list(delta.explicit_unlocks),
        rationale=delta.rationale,
    )


def _record_view(
    row: SpecificationRevisionRow, source: CreativeSpecification | None
) -> RevisionRecordView:
    return RevisionRecordView(
        id=str(row.id),
        iteration=row.iteration,
        status=RevisionStatus(row.status),
        user_feedback=row.user_feedback,
        delta=_delta_view(RevisionDelta.model_validate(row.delta), source),
        changed_fields=list(row.changed_fields or []),
        from_version=row.from_version,
        to_version=row.to_version,
        source_asset_id=str(row.source_asset_id) if row.source_asset_id else None,
        created_at=row.created_at,
    )


def _revision_view(view: ServiceRevisionView) -> RevisionView:
    source = view.source_specification
    revised = view.revised_specification
    diff: list[SpecificationDiffView] = []
    if source is not None and revised is not None and view.current is not None:
        for name in view.current.changed_fields or []:
            diff.append(
                SpecificationDiffView(
                    field=name,
                    label=_label_of(name),
                    before=_render(getattr(source, name, None)) or "—",
                    after=_render(getattr(revised, name, None)) or "—",
                )
            )
    return RevisionView(
        campaign_id=view.campaign_id,
        current=_record_view(view.current, source) if view.current is not None else None,
        history=[_record_view(row, source) for row in view.history],
        diff=diff,
        can_revise=view.can_revise,
        blocked_reason=view.blocked_reason,
    )


# -------------------------------------------------------------- command centre
@router.get("/{campaign_id}/overview", response_model=CampaignOverviewView)
async def get_overview(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    storage: StorageDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
) -> CampaignOverviewView:
    """Every stage of one campaign, in one call.

    A read model composed from the services that own each stage — it stores
    nothing and derives no state of its own, so it cannot drift from the
    screens it summarises.
    """
    service = CampaignOverviewService(
        session, principal, settings=settings, storage=storage, llm=llm, embeddings=embeddings
    )
    view = await service.overview(_uuid(campaign_id, "Campaign"))
    summary = view.evaluation
    return CampaignOverviewView(
        campaign_id=view.campaign_id,
        title=view.title,
        status=view.status,
        brand_id=view.brand_id,
        brand_name=view.brand_name,
        stages=[
            StageStateView(key=s.key, label=s.label, state=s.state, detail=s.detail)
            for s in view.stages
        ],
        campaign_specification_version=view.campaign_specification_version,
        creative_specification_version=view.creative_specification_version,
        creative_specification_approved=view.creative_specification_approved,
        latest_batch_assets=view.latest_batch_assets,
        failed_generations=view.failed_generations,
        recommended_asset_id=view.recommended_asset_id,
        recommended_score=view.recommended_score,
        recommended_reason=view.recommended_reason,
        selected_asset_id=view.selected_asset_id,
        ranked=[
            RankedAssetView(
                rank=r.rank,
                generated_asset_id=r.generated_asset_id,
                evaluation_id=r.evaluation_id,
                overall_score=r.overall_score,
                disposition=r.disposition,
                reason=r.reason,
                recommended=r.recommended,
            )
            for r in (summary.ranked if summary else [])
        ],
        guardian_verdict=GuardianVerdict(view.guardian_verdict) if view.guardian_verdict else None,
        guardian_checked=view.guardian_checked,
        revision_rounds=view.revision_rounds,
        composed_channels=[Channel(c) for c in view.composed_channels],
        available_channels=[Channel(c) for c in view.available_channels],
        final_assets=[final_asset_view(row, link) for row in view.final_assets],
        latest_layout_version=view.latest_layout_version,
        next_stage=view.next_stage,
        next_action=view.next_action,
    )


@router.get("/{campaign_id}/guardian", response_model=GuardianView)
async def get_guardian(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> GuardianView:
    """Read-only: every brand check and its verdict. The polling endpoint."""
    service = _revision(principal, session, settings, llm, embeddings, storage)
    view = await service.guardian_state(_uuid(campaign_id, "Campaign"))
    return await _guardian_view(view, campaign_id, principal, session, link)


@router.post("/{campaign_id}/guardian/start", response_model=GuardianView, status_code=202)
async def start_guardian(
    campaign_id: str,
    body: StartGuardianRequest,
    background: BackgroundTasks,
    runner: GuardianRunnerDep,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> GuardianView:
    """Brand-check the campaign's plates.

    Returns 202 with every check `PENDING`; the client polls until `in_flight`
    is zero.
    """
    service = _revision(principal, session, settings, llm, embeddings, storage)
    campaign_uuid = _uuid(campaign_id, "Campaign")
    asset_ids = (
        [_uuid(value, "Generated asset") for value in body.asset_ids]
        if body.asset_ids is not None
        else None
    )
    view, claimed = await service.start_guardian(campaign_uuid, asset_ids=asset_ids)

    # Durable before it is scheduled — the background task opens its own session.
    await session.commit()
    if claimed:
        background.add_task(
            runner,
            sessionmaker_for(settings.database_url),
            principal=principal,
            settings=settings,
            storage=storage,
            llm=llm,
            embeddings=embeddings,
            result_ids=claimed,
        )
    return await _guardian_view(view, campaign_id, principal, session, link)


@router.post(
    "/{campaign_id}/guardian/{result_id}/retry", response_model=GuardianView, status_code=202
)
async def retry_guardian(
    campaign_id: str,
    result_id: str,
    background: BackgroundTasks,
    runner: GuardianRunnerDep,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> GuardianView:
    """Re-run one failed brand check."""
    service = _revision(principal, session, settings, llm, embeddings, storage)
    campaign_uuid = _uuid(campaign_id, "Campaign")
    claimed = await service.retry_guardian(campaign_uuid, _uuid(result_id, "Brand check"))
    await session.commit()
    background.add_task(
        runner,
        sessionmaker_for(settings.database_url),
        principal=principal,
        settings=settings,
        storage=storage,
        llm=llm,
        embeddings=embeddings,
        result_ids=[claimed],
    )
    return await _guardian_view(
        await service.guardian_state(campaign_uuid), campaign_id, principal, session, link
    )


@router.get("/{campaign_id}/revision", response_model=RevisionView)
async def get_revision(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> RevisionView:
    """The open revision, the history, and the before/after diff."""
    service = _revision(principal, session, settings, llm, embeddings, storage)
    return _revision_view(await service.revision_state(_uuid(campaign_id, "Campaign")))


@router.post("/{campaign_id}/revision", response_model=RevisionView, status_code=201)
async def propose_revision(
    campaign_id: str,
    body: ProposeRevisionRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> RevisionView:
    """Turn feedback into a reviewable plan.

    Nothing is applied here: the delta is a proposal the human reads, edits and
    approves. Feedback too vague to act on comes back as a 400 asking for more,
    rather than a confident revision of something nobody requested.
    """
    service = _revision(principal, session, settings, llm, embeddings, storage)
    campaign_uuid = _uuid(campaign_id, "Campaign")
    await service.propose_revision(
        campaign_uuid,
        feedback=body.feedback,
        source_asset_id=(
            _uuid(body.source_asset_id, "Generated asset") if body.source_asset_id else None
        ),
    )
    return _revision_view(await service.revision_state(campaign_uuid))


@router.patch("/{campaign_id}/revision/delta", response_model=RevisionView)
async def edit_revision_delta(
    campaign_id: str,
    body: EditRevisionDeltaRequest,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> RevisionView:
    """Replace the proposal with the human's edited version."""
    service = _revision(principal, session, settings, llm, embeddings, storage)
    campaign_uuid = _uuid(campaign_id, "Campaign")
    state = await service.revision_state(campaign_uuid)
    if state.current is None:
        raise Conflict("There is no open revision to edit.")

    try:
        delta = RevisionDelta(
            iteration=state.current.iteration,
            user_feedback=state.current.user_feedback,
            interpretation=body.interpretation,
            keep=body.keep,
            change=[_to_change(item) for item in body.change],
            add=[_to_change(item) for item in body.add],
            remove=[_to_change(item) for item in body.remove],
            # The unlocks stay as the planner determined them from the user's
            # own words. An edit may not grant itself permission.
            explicit_unlocks=RevisionDelta.model_validate(state.current.delta).explicit_unlocks,
            rationale=body.rationale,
        )
    except ValueError as exc:
        raise ValidationFailed(str(exc), details={"field": "delta"}) from exc

    await service.edit_delta(campaign_uuid, delta=delta)
    return _revision_view(await service.revision_state(campaign_uuid))


def _to_change(item: EditFieldChangeRequest) -> FieldChange:
    return FieldChange(
        field=item.field, action=item.action, reason=item.reason, new_value=item.new_value
    )


@router.post("/{campaign_id}/revision/approve-delta", response_model=RevisionView)
async def approve_revision_delta(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> RevisionView:
    """Gate 1 — apply the approved delta and create the next version.

    Deterministic: what runs is exactly the plan the human just read.
    """
    service = _revision(principal, session, settings, llm, embeddings, storage)
    campaign_uuid = _uuid(campaign_id, "Campaign")
    await service.approve_delta(campaign_uuid)
    return _revision_view(await service.revision_state(campaign_uuid))


@router.post("/{campaign_id}/revision/approve", response_model=RevisionView)
async def approve_revised_specification(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> RevisionView:
    """Gate 2 — approve the revised specification.

    Only now may regeneration start, through the existing
    `POST /generation/start`. Milestone 8 adds no second generation path.
    """
    service = _revision(principal, session, settings, llm, embeddings, storage)
    campaign_uuid = _uuid(campaign_id, "Campaign")
    await service.approve_revised_specification(campaign_uuid)
    return _revision_view(await service.revision_state(campaign_uuid))


@router.post("/{campaign_id}/revision/reject", response_model=RevisionView)
async def reject_revision(
    campaign_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    llm: LLMDep,
    embeddings: EmbeddingsDep,
    storage: StorageDep,
) -> RevisionView:
    """Discard the proposal. The specification never changed, and the record
    that the question was asked survives."""
    service = _revision(principal, session, settings, llm, embeddings, storage)
    campaign_uuid = _uuid(campaign_id, "Campaign")
    await service.reject_revision(campaign_uuid)
    return _revision_view(await service.revision_state(campaign_uuid))
