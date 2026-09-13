"""Reference Intelligence.

Turns creative inspiration into structured style characteristics a later stage
can compose *from* — never a design it can copy.

The IP boundary is enforced in three places rather than trusted once: the
schema has no field that could hold reproducible content
(`ReferenceAnalysis.forbids_reproduction`), the prompt states the rule to the
model, and `sanitise_analysis` strips anything that comes back looking like
verbatim source content. A model that ignores the instruction should still not
be able to smuggle a headline through.

Processing states are explicit, and a provider failure is never recorded as
success:

    PENDING -> ANALYZING -> COMPLETED
                   |
                   v
                FAILED
"""

from __future__ import annotations

import re
import uuid
from collections import Counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CampaignReferenceRow
from app.domain.common import StyleFamily
from app.domain.reference import (
    AggregateReferenceStyle,
    ColorProfile,
    Composition,
    Lighting,
    ReferenceAnalysis,
    VisualDensity,
)
from app.logging import get_logger
from app.providers.base import ImageRef, LLMProvider, ProviderError, StorageProvider
from app.repositories.campaigns import CampaignReferenceRepository

log = get_logger(__name__)

ANALYSIS_SYSTEM = (
    "You describe the visual LANGUAGE of a reference image so a different "
    "design can be created in a similar spirit. You never reproduce the "
    "reference. Do not transcribe its text, name its brands or logos, "
    "identify its typeface, or describe its layout precisely enough to "
    "recreate it. Describe qualities, not content."
)

#: Anything matching these is source content, not a style quality. Stripped
#: from model output before it is stored.
_QUOTED = re.compile(r"[\"“”'‘’][^\"“”'‘’]{8,}[\"“”'‘’]")
_TRADEMARK = re.compile(r"\b\w+(?:®|™)")


def build_analysis_prompt(reference_id: str, note: str | None) -> str:
    forbidden = "\n".join(f"- {rule}" for rule in ReferenceAnalysis.forbids_reproduction())
    lines = [
        f"REFERENCE ID: {reference_id}",
        "Describe this reference's visual language as structured characteristics.",
        f"NEVER include:\n{forbidden}",
    ]
    if note:
        lines.append(f"THE USER SAID THEY LIKE: {note}")
    lines.append(
        "State what is NOT transferable in `not_transferable`, so the boundary "
        "is visible to the person reviewing this."
    )
    return "\n\n".join(lines)


def sanitise_analysis(analysis: ReferenceAnalysis) -> ReferenceAnalysis:
    """Strip anything that reads as copied source content.

    Belt and braces behind the prompt: a model that quotes the reference's
    headline back at us must not have it persisted into the creative context.
    """

    def clean(text: str | None) -> str | None:
        if not text:
            return text
        stripped = _TRADEMARK.sub("", _QUOTED.sub("", text))
        return " ".join(stripped.split()) or None

    data = analysis.model_dump()
    for field in ("subject_treatment", "summary"):
        data[field] = clean(data.get(field))
    for field in ("style_takeaways", "mood", "not_transferable"):
        data[field] = [c for c in (clean(v) for v in data.get(field, [])) if c]
    if data.get("layout", {}).get("hierarchy"):
        data["layout"]["hierarchy"] = clean(data["layout"]["hierarchy"])
    return ReferenceAnalysis.model_validate(data)


def aggregate(analyses: list[ReferenceAnalysis]) -> AggregateReferenceStyle:
    """What the references say *together*.

    Disagreement is surfaced as a tension rather than averaged away: three
    references that disagree about lighting is information the user should
    see, not a mean nobody chose.
    """
    if not analyses:
        return AggregateReferenceStyle()

    styles = Counter(s for a in analyses for s in a.style_families)
    compositions = Counter(a.composition for a in analyses if a.composition)
    lightings = Counter(a.lighting for a in analyses if a.lighting)
    densities = Counter(a.visual_density for a in analyses if a.visual_density)

    def majority[T](counter: Counter[T]) -> T | None:
        """Only report agreement when a clear majority actually agrees."""
        if not counter:
            return None
        value, count = counter.most_common(1)[0]
        return value if count > len(analyses) / 2 else None

    tensions: list[str] = []
    if len(lightings) > 1 and majority(lightings) is None:
        tensions.append(
            "References disagree on lighting: " + ", ".join(sorted(x.value for x in lightings))
        )
    if len(compositions) > 1 and majority(compositions) is None:
        tensions.append(
            "References disagree on composition: "
            + ", ".join(sorted(x.value for x in compositions))
        )
    if len(densities) > 1 and majority(densities) is None:
        tensions.append("References range from sparse to dense.")

    count = len(analyses)
    return AggregateReferenceStyle(
        dominant_styles=[s for s, _ in styles.most_common(4)],
        shared_palette=list(dict.fromkeys(c for a in analyses for c in a.color.dominant_palette))[
            :8
        ],
        shared_takeaways=list(dict.fromkeys(t for a in analyses for t in a.style_takeaways))[:8],
        tensions=tensions,
        common_composition=majority(compositions),
        common_lighting=majority(lightings),
        common_density=majority(densities),
        average_color=ColorProfile(
            dominant_palette=list(
                dict.fromkeys(c for a in analyses for c in a.color.dominant_palette)
            )[:6],
            brightness=round(sum(a.color.brightness for a in analyses) / count, 2),
            saturation=round(sum(a.color.saturation for a in analyses) / count, 2),
            contrast=round(sum(a.color.contrast for a in analyses) / count, 2),
            temperature=Counter(
                a.color.temperature for a in analyses if a.color.temperature
            ).most_common(1)[0][0]
            if any(a.color.temperature for a in analyses)
            else None,
        ),
        reference_count=count,
    )


class ReferenceIntelligenceService:
    """Analyse references and aggregate their style."""

    def __init__(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        *,
        storage: StorageProvider,
        llm: LLMProvider,
    ) -> None:
        self.session = session
        self.organization_id = organization_id
        self.storage = storage
        self.llm = llm
        self.references = CampaignReferenceRepository(session, organization_id)

    async def analyze(
        self, reference_id: uuid.UUID, *, force: bool = False
    ) -> CampaignReferenceRow | None:
        """Analyse one reference. Never raises: a failure is a recorded state.

        Returns None when the reference is not in this organization — the
        scoped repository simply finds nothing.
        """
        row = await self.references.get(reference_id)
        if row is None:
            return None
        if row.status == "COMPLETED" and row.analysis and not force:
            # Already understood; a re-analysis would cost a call for nothing.
            return row

        await self.references.set_status(row, "ANALYZING")
        try:
            data = await self.storage.get(row.storage_key)
        except ProviderError as exc:
            return await self._fail(row, "The stored image could not be read.", exc.detail)

        try:
            analysis = await self.llm.structured(
                build_analysis_prompt(str(row.id), row.note),
                ReferenceAnalysis,
                system=ANALYSIS_SYSTEM,
                images=(ImageRef(data=data, mime_type=row.mime_type),),
            )
        except ProviderError as exc:
            # A provider failure must never leave the reference looking
            # successful (§Error handling).
            return await self._fail(
                row, "This reference could not be analysed. Try again in a moment.", exc.detail
            )

        cleaned = sanitise_analysis(analysis.model_copy(update={"reference_id": str(row.id)}))
        return await self.references.set_status(
            row, "COMPLETED", analysis=cleaned.model_dump(mode="json")
        )

    async def analyze_campaign(self, campaign_id: uuid.UUID) -> list[CampaignReferenceRow]:
        """Analyse everything not yet understood for one campaign."""
        rows = await self.references.list_for_campaign(campaign_id)
        out: list[CampaignReferenceRow] = []
        for row in rows:
            out.append(await self.analyze(row.id) or row)
        return out

    async def analyses_for_campaign(self, campaign_id: uuid.UUID) -> list[ReferenceAnalysis]:
        """Every completed analysis, validated on read."""
        rows = await self.references.list_for_campaign(campaign_id)
        return [
            ReferenceAnalysis.model_validate(row.analysis)
            for row in rows
            if row.status == "COMPLETED" and row.analysis
        ]

    async def aggregate_for_campaign(self, campaign_id: uuid.UUID) -> AggregateReferenceStyle:
        return aggregate(await self.analyses_for_campaign(campaign_id))

    async def _fail(
        self, row: CampaignReferenceRow, message: str, detail: str | None
    ) -> CampaignReferenceRow:
        log.warning("reference_analysis_failed", reference_id=str(row.id), detail=detail)
        return await self.references.set_status(row, "FAILED", error=message)


def styles_from_analyses(analyses: list[ReferenceAnalysis]) -> list[StyleFamily]:
    """Every style family the references exhibit, most common first."""
    counter = Counter(s for a in analyses for s in a.style_families)
    return [style for style, _ in counter.most_common()]


__all__ = [
    "ANALYSIS_SYSTEM",
    "AggregateReferenceStyle",
    "Composition",
    "Lighting",
    "ReferenceIntelligenceService",
    "VisualDensity",
    "aggregate",
    "build_analysis_prompt",
    "sanitise_analysis",
    "styles_from_analyses",
]
