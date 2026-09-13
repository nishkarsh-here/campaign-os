"""Deterministic mock LLM.

`structured()` must return a valid instance of whatever Pydantic schema it is
handed, without a network call and without inventing a different shape on every
run. It does that by synthesising a value for each field from the schema itself,
seeded by a hash of the prompt — so the same prompt always produces the same
result and tests can assert on it.

`BrandExtraction` gets a purpose-built path, because the demo should show
plausible brand intelligence rather than filler. Everything it produces is
marked `PROPOSED` with `ProvenanceKind.INFERRED`, which is exactly what a real
extraction would be until a human accepts it.
"""

from __future__ import annotations

import enum
import hashlib
import re
import types
import typing
from typing import Any, NamedTuple, TypeVar

from pydantic import BaseModel

from app.domain.brand import (
    BrandExtraction,
    ExtractedFact,
    FactStatus,
    Provenance,
    ProvenanceKind,
)
from app.providers.base import (
    ContentBlocked,
    ImageRef,
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)

TModel = TypeVar("TModel", bound=BaseModel)

#: Cues the extractor looks for. A real model infers; this one matches, which
#: is enough to make the pipeline and the demo behave believably offline.
_CUES: tuple[tuple[str, str, str], ...] = (
    ("positioning", r"position(?:ing|ed)?[^.\n]*[.\n]", "How the brand positions itself"),
    (
        "audience_description",
        r"(?:audience|customers?|architects?|specifiers?)[^.\n]*[.\n]",
        "Who the brand is speaking to",
    ),
    ("voice.tone_attributes", r"(?:tone|voice)[^.\n]*[.\n]", "How the brand sounds"),
    ("values", r"value[s]?[^.\n]*[.\n]", "What the brand stands for"),
    (
        "prohibited_claims",
        r"(?:never|avoid|do not|don't|prohibited)[^.\n]*[.\n]",
        "A claim the brand forbids",
    ),
    (
        "approved_claims",
        r"(?:certified|tested|compliant|approved)[^.\n]*[.\n]",
        "A claim the brand has approved",
    ),
    (
        "visual_donts",
        r"(?:never (?:use|place|stretch)|do not (?:use|place|stretch))[^.\n]*[.\n]",
        "A visual restriction",
    ),
    ("logo_rules", r"logo[^.\n]*[.\n]", "A rule about the logo"),
)


def _seed(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode(), digest_size=8).digest(), "big")


class MockLLMProvider:
    """Offline, deterministic, and able to fail on demand."""

    name = "mock"

    def __init__(self, failure_mode: str = "none") -> None:
        self._failure_mode = failure_mode

    def _maybe_fail(self) -> None:
        match self._failure_mode:
            case "timeout":
                raise ProviderTimeout("The model timed out.", provider=self.name)
            case "rate_limit":
                raise ProviderRateLimited("Model rate limit reached.", provider=self.name)
            case "malformed":
                # What a real model does when it returns unusable JSON — the
                # single most common failure in this class of system (ADR-009).
                raise ProviderInvalidResponse(
                    "The model returned a response we could not use.", provider=self.name
                )
            case "blocked":
                raise ContentBlocked(
                    "That request was blocked by a safety filter.", provider=self.name
                )
            case "unavailable":
                raise ProviderUnavailable("The model service is unavailable.", provider=self.name)

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        images: tuple[ImageRef, ...] = (),
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        self._maybe_fail()
        return f"[mock] {prompt.strip()[:200]}"

    async def structured(
        self,
        prompt: str,
        schema: type[TModel],
        *,
        system: str | None = None,
        images: tuple[ImageRef, ...] = (),
        temperature: float = 0.4,
    ) -> TModel:
        self._maybe_fail()
        if schema is BrandExtraction:
            return typing.cast(TModel, _brand_extraction(prompt))
        if schema.__name__ == "ProposedQuestion":
            return typing.cast(TModel, _proposed_question(schema, prompt))
        if schema.__name__ == "AnswerExtraction":
            return typing.cast(TModel, _answer_extraction(schema, prompt))
        if schema.__name__ == "ReferenceAnalysis":
            return typing.cast(TModel, _reference_analysis(schema, prompt, images))
        if schema.__name__ == "ProposedDirectionSet":
            return typing.cast(TModel, _proposed_directions(schema, prompt))
        if schema.__name__ == "ProposedSpecification":
            return typing.cast(TModel, _proposed_specification(schema, prompt))
        if schema.__name__ == "ProposedEvaluation":
            return typing.cast(TModel, _proposed_evaluation(schema, prompt, images))
        if schema.__name__ == "ProposedGuardianReview":
            return typing.cast(TModel, _proposed_guardian_review(schema, prompt, images))
        if schema.__name__ == "ProposedRevision":
            return typing.cast(TModel, _proposed_revision(schema, prompt))
        return _synthesise(schema, _seed(prompt))


# --------------------------------------------------------------------------
# Brand extraction
# --------------------------------------------------------------------------
def _brand_extraction(prompt: str) -> BrandExtraction:
    facts: list[ExtractedFact] = []
    seen: set[tuple[str, str]] = set()

    for field_path, pattern, rationale in _CUES:
        for match in re.finditer(pattern, prompt, flags=re.IGNORECASE):
            sentence = " ".join(match.group(0).split()).strip(" .")
            if len(sentence) < 12 or len(sentence) > 400:
                continue
            key = (field_path, sentence.lower())
            if key in seen:
                continue
            seen.add(key)
            facts.append(
                ExtractedFact(
                    field=field_path,
                    value=sentence[:2000],
                    # Deterministic, and never high: this is an inference, and
                    # the UI should present it as one.
                    confidence=0.55 + (_seed(sentence) % 30) / 100,
                    provenance=Provenance(
                        kind=ProvenanceKind.INFERRED,
                        quote=sentence[:600],
                    ),
                    status=FactStatus.PROPOSED,
                    rationale=rationale,
                )
            )
            if len(facts) >= 40:
                break

    covered = {f.field for f in facts}
    unknown = [field for field, _, _ in _CUES if field not in covered]
    summary = (
        f"Found {len(facts)} candidate brand fact(s) across "
        f"{len(covered)} field(s). Nothing here is confirmed until you accept it."
        if facts
        else "No brand facts could be identified in the supplied sources."
    )
    return BrandExtraction(summary=summary, facts=facts, unknown_fields=unknown)


# --------------------------------------------------------------------------
# Generic schema synthesis — so any future node's schema works offline too
# --------------------------------------------------------------------------
def _synthesise[M: BaseModel](schema: type[M], seed: int) -> M:
    values: dict[str, Any] = {}
    for name, field in schema.model_fields.items():
        if not field.is_required():
            continue
        values[name] = _value_for(field.annotation, seed + _seed(name))
    return schema.model_validate(values)


def _value_for(annotation: Any, seed: int) -> Any:
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if origin in (types.UnionType, typing.Union):
        concrete = [a for a in args if a is not type(None)]
        return _value_for(concrete[0], seed) if concrete else None
    if origin in (list, set, tuple):
        return [_value_for(args[0], seed)] if args else []
    if origin is dict:
        return {}
    if isinstance(annotation, type):
        if issubclass(annotation, enum.Enum):
            members = list(annotation)
            return members[seed % len(members)]
        if issubclass(annotation, BaseModel):
            return _synthesise(annotation, seed)
        if issubclass(annotation, bool):
            return bool(seed % 2)
        if issubclass(annotation, int):
            return seed % 5 + 1
        if issubclass(annotation, float):
            return round((seed % 100) / 100, 2)
        if issubclass(annotation, str):
            return f"mock-{seed % 10000}"
    return f"mock-{seed % 10000}"


# --------------------------------------------------------------------------
# Campaign discovery (Milestone 3)
#
# The interviewer's prompt states the field to ask about and the suggested
# wording, so the mock can answer it faithfully without a model. That is not a
# shortcut around the guardrail — the guardrail is what makes the real model
# safe, and these mocks let its behaviour be tested deterministically.
# --------------------------------------------------------------------------
def _between(text: str, marker: str) -> str:
    for line in text.split("\n"):
        if line.startswith(marker):
            return line[len(marker) :].strip()
    return ""


def _proposed_question(schema: type[Any], prompt: str) -> Any:
    field = _between(prompt, "NEXT FIELD TO ASK ABOUT:") or "campaign_objective"
    wording = _between(prompt, "SUGGESTED WORDING:") or "Tell me more about this campaign."
    why = _between(prompt, "WHY IT MATTERS:") or "It shapes the rest of the campaign."

    # When the brand already answers this, ask whether the campaign differs —
    # the behaviour the milestone specifies.
    brand_line = next(
        (line for line in prompt.split("\n") if line.startswith("THE BRAND ALREADY SAYS")), ""
    )
    if brand_line:
        known = brand_line.split("=", 1)[-1].split(".")[0].strip().strip("'\"")
        wording = (
            f"Your brand usually says {known}. Should this campaign keep that, "
            "or is it aimed somewhere different?"
        )
    return schema.model_validate(
        {"field": field, "question": wording, "why": why, "priority": "HIGH"}
    )


#: Cues that map a natural reply onto a campaign field, in priority order.
_ANSWER_CUES: tuple[tuple[str, str], ...] = (
    (
        "campaign_objective",
        r"\b(awareness|launch|lead generation|engagement|retention|conversion)\b",
    ),
    ("channels", r"\b(instagram|linkedin|facebook|banner|print|story)\w*\b"),
    ("target_audience", r"\b(architect|contractor|specifier|developer|engineer|designer)\w*\b"),
    ("region", r"\b(maharashtra|india|pune|mumbai|delhi|europe|uk|usa)\b"),
)

_NOT_APPLICABLE = re.compile(
    r"\b(not applicable|n/?a|doesn'?t apply|does not apply"
    r"|no (?:specific )?(?:offer|deadline|restriction))\b",
    re.IGNORECASE,
)
_HEDGED = re.compile(r"\b(i think|probably|maybe|might be|i guess|possibly)\b", re.IGNORECASE)


def _answer_extraction(schema: type[Any], prompt: str) -> Any:
    reply = _between(prompt, "USER REPLY:")
    asked = ""
    for line in prompt.split("\n"):
        if line.startswith("QUESTION ASKED (about field"):
            asked = line.split("'")[1] if "'" in line else ""
            break

    if _NOT_APPLICABLE.search(reply):
        return schema.model_validate(
            {"updates": [{"field": asked, "value": "", "not_applicable": True}]}
        )

    # A hedged reply is an inference, not a statement — the distinction the
    # milestone calls out with "I think this is mainly for architects".
    certainty = "inferred" if _HEDGED.search(reply) else "stated"

    updates: list[dict[str, Any]] = []
    if asked:
        updates.append({"field": asked, "value": reply[:2000], "certainty": certainty})
    for field, pattern in _ANSWER_CUES:
        if field == asked:
            continue
        found = re.findall(pattern, reply, flags=re.IGNORECASE)
        if found:
            updates.append(
                {
                    "field": field,
                    "value": ", ".join(dict.fromkeys(f.lower() for f in found)),
                    # Volunteered alongside the answer: read, not stated outright.
                    "certainty": "inferred",
                }
            )
    return schema.model_validate({"updates": updates})


# --------------------------------------------------------------------------
# Reference intelligence (Milestone 4)
#
# Derived from the image bytes, not from the prompt: the same picture always
# yields the same reading, and two different pictures yield different ones.
# That is what makes downstream aggregation and preference weighting testable
# without a real vision model.
# --------------------------------------------------------------------------
_STYLE_ORDER = (
    "premium",
    "minimal",
    "technical",
    "cinematic",
    "bold",
    "festive",
    "local_cultural",
    "editorial",
)
_COMPOSITIONS = (
    "centered",
    "asymmetric",
    "grid",
    "large_negative_space",
    "product_dominant",
    "people_dominant",
    "typography_dominant",
)
_LIGHTING = ("natural", "studio", "cinematic", "high_key", "low_key")
_IMAGERY = (
    "photorealistic",
    "illustrative",
    "abstract",
    "product_photography",
    "lifestyle",
    "architectural",
    "human_centric",
)
_DENSITY = ("sparse", "balanced", "dense")
_MOODS = (
    "premium",
    "energetic",
    "trustworthy",
    "futuristic",
    "warm",
    "technical",
    "aspirational",
)


def _image_seed(images: tuple[ImageRef, ...]) -> int:
    """Seed from the image itself, so the reading is a property of the picture."""
    material = b""
    for image in images:
        if image.data:
            material += image.data
        elif image.storage_key:
            material += image.storage_key.encode()
    return _seed(material.hex() if material else "no-image")


def _pick(options: tuple[str, ...], seed: int, salt: int) -> str:
    return options[(seed // (salt + 1)) % len(options)]


def _unit(seed: int, salt: int) -> float:
    return round(((seed // (salt + 7)) % 100) / 100, 2)


def _reference_analysis(schema: type[Any], prompt: str, images: tuple[ImageRef, ...]) -> Any:
    seed = _image_seed(images)
    reference_id = _between(prompt, "REFERENCE ID:") or "unknown"

    styles = [_pick(_STYLE_ORDER, seed, i) for i in (1, 5)]
    styles = list(dict.fromkeys(styles))
    moods = list(dict.fromkeys(_pick(_MOODS, seed, i) for i in (2, 9)))
    palette = [f"#{((seed >> (i * 8)) & 0xFFFFFF):06X}" for i in range(3)]

    return schema.model_validate(
        {
            "reference_id": reference_id,
            "style_families": styles,
            "composition": _pick(_COMPOSITIONS, seed, 3),
            "lighting": _pick(_LIGHTING, seed, 4),
            "imagery_style": [_pick(_IMAGERY, seed, 6)],
            "color": {
                "dominant_palette": palette,
                "brightness": _unit(seed, 1),
                "saturation": _unit(seed, 2),
                "contrast": _unit(seed, 3),
                "temperature": ("warm", "neutral", "cool")[seed % 3],
            },
            "typography": {
                "scale": ("large", "medium", "small")[seed % 3],
                "weight": ("light", "regular", "bold")[(seed // 3) % 3],
                "classification": ("serif", "sans_serif", "mixed")[(seed // 5) % 3],
                "case": ("upper", "title", "sentence")[(seed // 7) % 3],
                "text_density": _pick(_DENSITY, seed, 8),
            },
            "layout": {
                "image_text_balance": ("image_led", "balanced", "text_led")[(seed // 11) % 3],
                "subject_placement": ("left", "centre", "right")[(seed // 13) % 3],
                "hierarchy": "Subject first, supporting copy second.",
            },
            "visual_density": _pick(_DENSITY, seed, 10),
            "mood": moods,
            "subject_treatment": "Subject held in clear focus against a simplified ground.",
            "style_takeaways": [
                f"Lean {styles[0].replace('_', ' ')} in overall treatment.",
                f"Use {_pick(_LIGHTING, seed, 4).replace('_', ' ')} lighting.",
                f"Keep the composition {_pick(_COMPOSITIONS, seed, 3).replace('_', ' ')}.",
            ],
            # Stated explicitly so the boundary is visible in the product, not
            # just in the schema docstring.
            "not_transferable": [
                "the reference's own headline and body copy",
                "any logo or wordmark belonging to the reference",
                "its exact layout geometry",
            ],
            "confidence": 0.55 + (seed % 35) / 100,
            "summary": (
                f"Reads as {styles[0].replace('_', ' ')} — "
                f"{_pick(_LIGHTING, seed, 4).replace('_', ' ')} lighting, "
                f"{_pick(_COMPOSITIONS, seed, 3).replace('_', ' ')} composition, "
                f"{_pick(_DENSITY, seed, 10)} density."
            ),
        }
    )


# --------------------------------------------------------------------------
# Creative direction (Milestone 5)
#
# Three *genuinely* different angles, drawn from the campaign in the prompt
# rather than hardcoded strings — which is what lets the deterministic
# diversity check be exercised for real. When the prompt reports that the
# previous attempt was too repetitive, the mock diverges further, so the retry
# path is testable too.
# --------------------------------------------------------------------------
class _Angle(NamedTuple):
    """One creative route. `handle` is the short title a director would write
    on the card; `headline_shape` gives each route its own line, because three
    directions that share a headline are three layouts of one idea."""

    angle: str
    handle: str
    headline_shape: str
    subject: str
    environment: str
    composition: str
    lighting: str


_ANGLES: tuple[_Angle, ...] = (
    _Angle(
        "engineering confidence",
        "Built to Spec",
        "{message}",
        "the product itself, held in precise detail",
        "a fabrication floor, machined surfaces, measured order",
        "tight orthographic framing, product filling the frame",
        "hard directional studio light raking across the surface",
    ),
    _Angle(
        "human aspiration and trust",
        "Lived In",
        "{message} — and the people inside it",
        "a practitioner mid-decision, hand resting on the work",
        "an occupied building at the hour people arrive",
        "wide environmental portrait, subject small against the structure",
        "soft natural window light, long warm shadows",
    ),
    _Angle(
        "architectural modernity",
        "Against the Sky",
        "The line stays true. {message}",
        "the finished form read as geometry against sky",
        "an open urban edge, horizon uninterrupted",
        "low asymmetric angle, strong diagonal, generous negative space",
        "cool overcast daylight, flat even illumination",
    ),
    _Angle(
        "quiet permanence",
        "Weathering Well",
        "Years from now: {message}",
        "a weathered adjacent surface beside an untouched one",
        "a street after rain, reflections holding the light",
        "centred symmetrical elevation, deep stillness",
        "low-key dusk light, single practical source",
    ),
)


def _campaign_field(prompt: str, marker: str, fallback: str) -> str:
    value = _between(prompt, marker)
    return value or fallback


def _phrase(text: str) -> str:
    """A campaign field with its trailing full stop removed, so it can sit
    mid-sentence. Without this, `"{objective} lands with…"` reads as
    "…at design stage. lands with…"."""
    return text.rstrip(" .")


def _clip(text: str, limit: int) -> str:
    """Trim to a word boundary. A bare slice cuts mid-word — "Mumbai and Pu" —
    which is exactly the kind of detail that makes a demo look unfinished."""
    text = _phrase(text)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _proposed_directions(schema: type[Any], prompt: str) -> Any:
    product = _campaign_field(prompt, "PRODUCT:", "the product")
    audience = _campaign_field(prompt, "AUDIENCE:", "the audience")
    objective = _campaign_field(prompt, "OBJECTIVE:", "the campaign objective")
    message = _campaign_field(prompt, "KEY MESSAGE:", "the key message")
    cta = _campaign_field(prompt, "CALL TO ACTION:", "Find out more")
    brand = _campaign_field(prompt, "BRAND:", "the brand")

    # A retry must diverge further, or the diversity check would loop on the
    # same output — so shift the angle window when the prompt says so.
    retried = "TOO REPETITIVE" in prompt
    revision = _between(prompt, "REVISION REQUESTED:")
    offset = 1 if retried else 0
    if revision:
        # Feedback shifts the emotional angle; campaign facts stay put.
        offset = 1

    styles = ["premium", "technical", "editorial", "cinematic"]
    directions = []
    for i in range(3):
        route = _ANGLES[(i + offset) % len(_ANGLES)]
        angle, subject, environment, composition, lighting = (
            route.angle,
            route.subject,
            route.environment,
            route.composition,
            route.lighting,
        )
        directions.append(
            {
                "title": route.handle,
                "big_idea": f"Show {_phrase(product)} through {angle}.",
                "strategic_rationale": (
                    f"{_phrase(objective)} lands with {_phrase(audience)} when the work "
                    f"argues from {angle} rather than from specification alone."
                ),
                "emotional_angle": angle,
                "audience_connection": f"Speaks to {_phrase(audience)} on their own terms.",
                "key_message": message,
                "headline": route.headline_shape.format(message=_phrase(message))
                or "Built to last",
                "cta": cta,
                "cta_direction": "Quiet, placed low, never competing with the subject.",
                "visual_metaphor": f"{subject} standing for {angle}",
                "composition": composition,
                "subject": subject,
                "environment": environment,
                "lighting": lighting,
                "palette": ["#1F2933", "#E4572E", "#F5F5F4"][: 2 + (i % 2)],
                "color_direction": "Restrained ground, one accent carrying the eye.",
                "style_families": [styles[(i + offset) % len(styles)]],
                "brand_integration": f"{brand} present through colour and restraint, not a badge.",
                "product_integration": f"{_phrase(product)} is the subject, not a prop.",
                "regional_considerations": (
                    [_between(prompt, "REGION:")] if _between(prompt, "REGION:") else []
                ),
                # Abstract qualities only — never reference content (ADR-011).
                "reference_characteristics_used": [
                    f"{lighting.split(',')[0]} quality of light",
                    composition.split(",")[0],
                ],
                "reference_characteristics_avoided": [
                    "the reference's own copy and headline",
                    "any logo or wordmark from the reference",
                ],
                "distinctness_note": f"Differs by angle: {angle}.",
            }
        )

    return schema.model_validate(
        {
            "directions": directions,
            "recommended_index": 0,
            "recommendation_reasons": [
                f"Closest fit to the objective: {_clip(objective, 70)}",
                f"Speaks directly to {_clip(audience, 60)}",
                "Uses reference qualities abstractly, without copying",
            ],
        }
    )


def _proposed_specification(schema: type[Any], prompt: str) -> Any:
    concept = _campaign_field(prompt, "CONCEPT:", "the approved concept")
    subject = _campaign_field(prompt, "SUBJECT:", "the product")
    environment = _campaign_field(prompt, "ENVIRONMENT:", "a considered setting")
    composition = _campaign_field(prompt, "COMPOSITION:", "balanced framing")
    lighting = _campaign_field(prompt, "LIGHTING:", "directional daylight")
    headline = _campaign_field(prompt, "HEADLINE:", "Built to last")
    angle = _campaign_field(prompt, "EMOTIONAL ANGLE:", "confidence")

    return schema.model_validate(
        {
            "concept": concept,
            "visual_story": (
                f"{subject} in {environment}. The frame is {composition}, lit by "
                f"{lighting}. Nothing competes with the subject."
            ),
            "emotional_angle": angle,
            "headline": headline,
            "headline_guidance": (
                "Set large, high contrast against the quietest area of the plate. "
                "Weight and case only — no typeface is specified here."
            ),
            "cta": _campaign_field(prompt, "CTA:", "Find out more"),
            "cta_guidance": "Lower third, secondary weight, clear of the subject.",
            "visual_metaphor": f"{subject} as evidence of {angle}",
            "composition": composition,
            "focal_point": f"{subject.split(',')[0]}, held at the optical centre",
            "subject": subject,
            "environment": environment,
            "lighting": lighting,
            "camera": "35mm, eye level, shallow depth of field",
            "palette": ["#1F2933", "#E4572E"],
            "color_direction": "Muted ground with a single warm accent.",
            "mood": [angle.split()[0], "considered"],
            "product_integration": _campaign_field(prompt, "PRODUCT:", "the product, in use"),
            "people_guidance": ("One figure at most, turned into the scene, never facing camera."),
            "brand_integration": _campaign_field(prompt, "BRAND:", "brand colour and restraint"),
            "regional_cues": [],
        }
    )


# --------------------------------------------------------------------------
# Creative evaluation (Milestone 7)
#
# Deterministic, and deliberately *not* uniform. Scores are derived from the
# image bytes, so the same plate always scores the same and two different
# plates score differently — which is what makes ranking, ties, thresholds and
# dispositions testable offline. A mock that returned 80 for everything would
# prove only that the plumbing runs.
# --------------------------------------------------------------------------

#: Per-dimension character, so the mock produces a *shape* rather than noise.
#: Each entry shifts that dimension relative to the asset's base score, which
#: is how a plate ends up strong on craft and weak on audience fit — the sort
#: of result the disposition rules exist to handle.
_DIMENSION_BIAS: tuple[tuple[str, int], ...] = (
    ("brand_alignment", 4),
    ("campaign_objective_fit", 2),
    ("audience_fit", -6),
    ("creative_direction_alignment", 6),
    ("visual_quality", 8),
    ("composition", 3),
    ("product_representation", -3),
    ("regional_fit", 0),
    ("reference_style_alignment", -4),
    ("plate_readiness", 7),
)

_STRENGTH_NOTES: tuple[str, ...] = (
    "Composition holds a clear focal point.",
    "Restrained palette reads as premium.",
    "Light is consistent and believable.",
    "Product is unmistakably the subject.",
    "Generous quiet area for the headline.",
)

_CONCERN_NOTES: tuple[str, ...] = (
    "Reads a little generic for the stated audience.",
    "Background detail competes with the subject.",
    "Colour drifts warmer than the brand palette.",
    "Framing is tighter than the direction asked for.",
    "Little clear space for the call to action.",
)


def _proposed_evaluation(schema: type[Any], prompt: str, images: tuple[ImageRef, ...]) -> Any:
    """Score a plate deterministically from its own pixels."""
    seed = _image_seed(images)
    # Base score spans 42-92, so a batch of plates naturally contains rejects,
    # reviews and passes rather than clustering in one disposition.
    base = 42 + (seed % 51)

    scored: list[tuple[str, int]] = []
    for index, (name, bias) in enumerate(_DIMENSION_BIAS):
        jitter = ((seed >> (index * 3)) % 11) - 5
        scored.append((name, max(0, min(100, base + bias + jitter))))

    ranked = sorted(scored, key=lambda pair: -pair[1])
    strongest, weakest = ranked[0][0], ranked[-1][0]

    return schema.model_validate(
        {
            "dimensions": [
                {"dimension": name, "score": score, "note": _note(name, score)}
                for name, score in scored
            ],
            "strengths": [_pick(_STRENGTH_NOTES, seed, i) for i in (1, 4)],
            "concerns": [_pick(_CONCERN_NOTES, seed, i) for i in (2, 7)],
            "rationale": (f"Strongest on {_human(strongest)}; weakest on {_human(weakest)}."),
        }
    )


def _note(dimension: str, score: int) -> str:
    """One line per dimension, pitched to the score it explains."""
    subject = _human(dimension)
    if score >= 80:
        return f"{subject} is strong."
    if score >= 60:
        return f"{subject} is adequate with room to improve."
    return f"{subject} is weak and would need work."


def _human(dimension: str) -> str:
    return dimension.replace("_", " ")


# --------------------------------------------------------------------------
# Brand Guardian (Milestone 8)
#
# Deterministic from the image bytes, and deliberately able to produce all
# three verdicts: a mock that always passed would leave the NEEDS_REVISION and
# REJECT paths — and the whole revision loop behind them — untested offline.
# --------------------------------------------------------------------------
#: Qualitative checks only. The deterministic ones are settled in code, and the
#: service drops anything the model reports on those.
_GUARDIAN_CHECKS: tuple[str, ...] = (
    "brand_tone",
    "visual_identity",
    "claim_safety",
    "product_representation",
    "logo_readiness",
    "policy_compliance",
)

_GUARDIAN_FAILURES: dict[str, tuple[str, str]] = {
    "brand_tone": (
        "Reads warmer and more consumer than the brand's stated tone.",
        "Cool the palette and remove the lifestyle framing.",
    ),
    "visual_identity": (
        "The treatment is glossier than the brand's usual restraint.",
        "Reduce contrast and let the material do the work.",
    ),
    "product_representation": (
        "The product sits as a background element rather than the subject.",
        "Bring the product forward and give it the focal position.",
    ),
    "logo_readiness": (
        "No clean area is left where the logo will be placed.",
        "Open up a quiet corner with even tone for the logo.",
    ),
    "policy_compliance": (
        "The scene implies a use case the brand has not approved.",
        "Show the product in its stated application only.",
    ),
}


def _proposed_guardian_review(schema: type[Any], prompt: str, images: tuple[ImageRef, ...]) -> Any:
    """Review a plate deterministically from its own pixels."""
    seed = _image_seed(images)
    # 0-9: most plates pass, some need revision, a few are rejected outright.
    band = seed % 10

    checks: list[dict[str, Any]] = []
    for index, name in enumerate(_GUARDIAN_CHECKS):
        failing = name in _GUARDIAN_FAILURES and (seed >> (index * 2)) % 7 == 0 and band >= 6
        if failing:
            detail, fix = _GUARDIAN_FAILURES[name]
            checks.append(
                {
                    "check": name,
                    "status": "FAIL" if band >= 9 else "WARN",
                    "severity": "blocking" if band >= 9 else "major",
                    "detail": detail,
                    "suggested_fix": fix,
                }
            )
        else:
            checks.append(
                {
                    "check": name,
                    "status": "PASS",
                    "detail": f"{name.replace('_', ' ').capitalize()} is within the brand's rules.",
                }
            )

    failed = [c for c in checks if c["status"] != "PASS"]
    summary = (
        "Within the brand's rules."
        if not failed
        else f"{len(failed)} brand issue(s) to address before this can be used."
    )
    return schema.model_validate({"checks": checks, "summary": summary})


# --------------------------------------------------------------------------
# Revision planner (Milestone 8)
#
# Reads cues out of the feedback and turns them into a structured delta. Not a
# rewrite: it names the fields the feedback is about, leaves everything else
# alone, and says which approved facts it is preserving.
# --------------------------------------------------------------------------
#: When a user names a field outright — "everything is good except the
#: environment" — that is the least ambiguous feedback there is, and it must
#: map to that field rather than to whatever adjective sits beside it.
_NAMED_FIELDS: tuple[tuple[str, str, str], ...] = (
    (r"\benvironment|setting|backdrop|location\b", "environment", "a more specific setting"),
    (r"\blighting|light\b", "lighting", "reworked light"),
    (r"\bcomposition|framing|crop\b", "composition", "a reworked frame"),
    (r"\bsubject\b", "subject", "a reconsidered subject"),
    (r"\bmood\b", "mood", "a reconsidered mood"),
)

#: Feedback phrase -> the specification fields it is really about, and how to
#: rewrite them. Ordered: the first cue that matches wins for a given field.
_FEEDBACK_CUES: tuple[tuple[str, str, str], ...] = (
    (
        r"\b(local|region|india|maharashtra|mumbai|pune|context)\w*\b",
        "environment",
        "the same setting, grounded in a recognisably local context",
    ),
    (
        r"\b(premium|luxur|upmarket|refined|elevated)\w*\b",
        "lighting",
        "softer, more directional light with deeper falloff for a premium feel",
    ),
    (
        r"\b(generic|bland|stock|forgettable|boring)\w*\b",
        "visual_story",
        "a specific moment rather than a generic scene, with one memorable detail",
    ),
    (
        r"\b(product|prominen|subject|hero)\w*\b",
        "focal_point",
        "the product itself, held unambiguously at the optical centre",
    ),
    (
        r"\b(technical|clinical|cold|industrial)\w*\b",
        "mood_line",
        "warmer and more human while staying precise",
    ),
    (
        r"\b(clutter|busy|noisy|distract)\w*\b",
        "composition",
        "a simplified frame with generous negative space around the subject",
    ),
    (
        r"\b(people|human|person|occupied)\w*\b",
        "people_guidance",
        "one figure present but turned into the scene, never facing camera",
    ),
    (
        r"\b(colou?r|palette|warm|cool|tone)\w*\b",
        "color_direction",
        "a tighter palette built around the brand's primary with one accent",
    ),
)

#: Fields the planner names as preserved whenever it is not changing them.
#: Saying what stays is how a user sees a refinement rather than a rewrite.
_PRESERVED_BY_DEFAULT: tuple[str, ...] = (
    "concept",
    "headline",
    "cta",
    "subject",
    "product_integration",
    "brand_integration",
    "composition",
)


def _proposed_revision(schema: type[Any], prompt: str) -> Any:
    feedback = _between(prompt, "FEEDBACK:") or prompt.strip()
    lowered = feedback.lower()

    changes: list[dict[str, Any]] = []
    matched: list[str] = []

    # A directly named field first: "except the environment" is unambiguous,
    # and the adjective beside it only refines *how* to change it.
    for pattern, field_name, fallback in _NAMED_FIELDS:
        if not re.search(pattern, lowered):
            continue
        replacement = fallback
        for cue_pattern, _, cue_replacement in _FEEDBACK_CUES:
            if re.search(cue_pattern, lowered):
                replacement = cue_replacement
                break
        matched.append(field_name)
        changes.append(
            {
                "field": field_name,
                "action": "CHANGE",
                "reason": f"Addresses your note about the {field_name.replace('_', ' ')}.",
                "new_value": replacement,
            }
        )

    for pattern, target, replacement in _FEEDBACK_CUES:
        if len(changes) >= 3:
            break
        if not re.search(pattern, lowered):
            continue
        field = "mood" if target == "mood_line" else target
        if field in matched:
            continue
        matched.append(field)
        changes.append(
            {
                "field": field,
                "action": "CHANGE",
                "reason": f"Addresses your note about {_cue_label(pattern)}.",
                "new_value": replacement,
            }
        )

    if not changes:
        # Nothing recognisable. Say so rather than inventing a change — unclear
        # feedback goes back to the human (GRAPH_SPEC, revision_planner).
        return schema.model_validate(
            {
                "interpretation": ("We could not tell which part of the creative this is about."),
                "keep": list(_PRESERVED_BY_DEFAULT),
                "change": [],
                "add": [],
                "remove": [],
                "explicit_unlocks": [],
                "rationale": (
                    "No change proposed: the feedback did not name anything specific "
                    "enough to act on without guessing."
                ),
            }
        )

    changed = {item["field"] for item in changes}
    return schema.model_validate(
        {
            "interpretation": f"Change {', '.join(sorted(changed))}; keep everything else.",
            "keep": [f for f in _PRESERVED_BY_DEFAULT if f not in changed],
            "change": changes,
            "add": [],
            "remove": [],
            "explicit_unlocks": [],
            "rationale": (
                f"Addresses your feedback, preserves the approved product, message "
                f"and call to action, and changes only {', '.join(sorted(changed))}."
            ),
        }
    )


def _cue_label(pattern: str) -> str:
    """A readable name for the cue a pattern matched."""
    words = re.findall(r"[a-z]{4,}", pattern)
    return words[0] if words else "the creative"
