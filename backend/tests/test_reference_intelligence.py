"""Reference intelligence: analysis, the IP boundary, and aggregation.

The most important tests here are the ones about what the system refuses to
extract. Learning a visual language is the feature; copying a design is not.
"""

from __future__ import annotations

import pytest

from app.domain.common import StyleFamily
from app.domain.reference import (
    ColorProfile,
    Composition,
    Lighting,
    ReferenceAnalysis,
    VisualDensity,
    VisualStyleProfile,
)
from app.providers.base import ImageRef
from app.providers.mock.llm import MockLLMProvider
from app.services.reference_intelligence import (
    aggregate,
    build_analysis_prompt,
    sanitise_analysis,
    styles_from_analyses,
)

pytestmark = pytest.mark.unit


def _analysis(**overrides) -> ReferenceAnalysis:
    base = {
        "reference_id": "r1",
        "style_families": [StyleFamily.PREMIUM],
        "composition": Composition.CENTERED,
        "lighting": Lighting.STUDIO,
        "visual_density": VisualDensity.SPARSE,
        "color": ColorProfile(
            dominant_palette=["#1F2933"], brightness=0.4, saturation=0.3, contrast=0.8
        ),
        "style_takeaways": ["Keep it restrained."],
    }
    return ReferenceAnalysis.model_validate(base | overrides)


class TestIntellectualPropertyBoundary:
    def test_the_schema_names_what_it_refuses_to_hold(self) -> None:
        """The rule lives in code so a later milestone cannot widen it quietly."""
        rules = ReferenceAnalysis.forbids_reproduction()
        joined = " ".join(rules).lower()
        assert "logo" in joined
        assert "font" in joined or "typeface" in joined
        assert "layout" in joined

    def test_there_is_no_field_that_could_hold_reproducible_content(self) -> None:
        """No verbatim text, no coordinates, no font family — the schema
        itself is the first line of defence."""
        fields = set(ReferenceAnalysis.model_fields)
        for forbidden in ("text", "headline", "copy", "logo", "font_family", "coordinates"):
            assert forbidden not in fields

    def test_typography_records_character_not_a_typeface(self) -> None:
        from app.domain.reference import TypographyCharacter

        fields = set(TypographyCharacter.model_fields)
        assert "font_family" not in fields
        assert {"scale", "weight", "classification", "case"} <= fields

    def test_the_prompt_tells_the_model_the_rule(self) -> None:
        prompt = build_analysis_prompt("r1", None).lower()
        assert "never include" in prompt
        for rule in ("logo", "font", "layout"):
            assert rule in prompt

    def test_a_quoted_headline_is_stripped_from_model_output(self) -> None:
        """Belt and braces: a model that ignores the instruction must not get
        the reference's own copy into the creative context."""
        dirty = _analysis(
            summary='Bold poster reading "Built to outlast every winter storm" in caps.',
            style_takeaways=['Echo the phrase "Engineered for life" somewhere.'],
        )
        clean = sanitise_analysis(dirty)
        assert "Built to outlast" not in (clean.summary or "")
        assert all("Engineered for life" not in t for t in clean.style_takeaways)

    def test_trademarked_names_are_stripped(self) -> None:
        clean = sanitise_analysis(_analysis(summary="Uses Northline® branding heavily."))
        assert "Northline®" not in (clean.summary or "")

    def test_sanitising_leaves_legitimate_description_intact(self) -> None:
        clean = sanitise_analysis(_analysis(summary="Low-key studio lighting, sparse layout."))
        assert clean.summary == "Low-key studio lighting, sparse layout."


class TestMockAnalysis:
    async def test_the_reading_is_derived_from_the_image(self) -> None:
        llm = MockLLMProvider()
        first = await llm.structured(
            "REFERENCE ID: a", ReferenceAnalysis, images=(ImageRef(data=b"image-one"),)
        )
        second = await llm.structured(
            "REFERENCE ID: b", ReferenceAnalysis, images=(ImageRef(data=b"image-two"),)
        )
        assert first.model_dump() != second.model_dump()

    async def test_the_same_image_always_reads_the_same(self) -> None:
        llm = MockLLMProvider()
        kwargs = {"images": (ImageRef(data=b"stable"),)}
        first = await llm.structured("REFERENCE ID: a", ReferenceAnalysis, **kwargs)
        second = await llm.structured("REFERENCE ID: a", ReferenceAnalysis, **kwargs)
        assert first.model_dump() == second.model_dump()

    async def test_it_produces_a_usable_analysis(self) -> None:
        llm = MockLLMProvider()
        analysis = await llm.structured(
            "REFERENCE ID: r1", ReferenceAnalysis, images=(ImageRef(data=b"poster"),)
        )
        assert analysis.style_families
        assert analysis.composition is not None
        assert analysis.lighting is not None
        assert analysis.color.dominant_palette
        assert analysis.style_takeaways
        assert analysis.not_transferable, "the boundary must be stated in the output"

    async def test_a_failing_provider_raises_rather_than_returning_nonsense(self) -> None:
        from app.providers.base import ProviderInvalidResponse

        llm = MockLLMProvider(failure_mode="malformed")
        with pytest.raises(ProviderInvalidResponse):
            await llm.structured(
                "REFERENCE ID: r1", ReferenceAnalysis, images=(ImageRef(data=b"x"),)
            )


class TestAggregation:
    def test_no_references_gives_an_empty_aggregate(self) -> None:
        assert aggregate([]).reference_count == 0

    def test_shared_style_becomes_dominant(self) -> None:
        result = aggregate(
            [
                _analysis(style_families=[StyleFamily.PREMIUM]),
                _analysis(style_families=[StyleFamily.PREMIUM, StyleFamily.MINIMAL]),
            ]
        )
        assert result.dominant_styles[0] is StyleFamily.PREMIUM
        assert result.reference_count == 2

    def test_agreement_is_reported_as_a_common_value(self) -> None:
        result = aggregate([_analysis(), _analysis(), _analysis()])
        assert result.common_lighting is Lighting.STUDIO
        assert result.common_composition is Composition.CENTERED

    def test_disagreement_becomes_a_tension_rather_than_an_average(self) -> None:
        """Three references that disagree is information the user should see,
        not a mean nobody chose."""
        result = aggregate(
            [
                _analysis(lighting=Lighting.STUDIO),
                _analysis(lighting=Lighting.NATURAL),
                _analysis(lighting=Lighting.CINEMATIC),
            ]
        )
        assert result.common_lighting is None
        assert any("lighting" in t.lower() for t in result.tensions)

    def test_a_bare_majority_still_counts_as_agreement(self) -> None:
        result = aggregate(
            [
                _analysis(lighting=Lighting.STUDIO),
                _analysis(lighting=Lighting.STUDIO),
                _analysis(lighting=Lighting.NATURAL),
            ]
        )
        assert result.common_lighting is Lighting.STUDIO

    def test_colour_qualities_are_averaged(self) -> None:
        result = aggregate(
            [
                _analysis(color=ColorProfile(brightness=0.2, saturation=0.2, contrast=0.2)),
                _analysis(color=ColorProfile(brightness=0.8, saturation=0.8, contrast=0.8)),
            ]
        )
        assert result.average_color.brightness == pytest.approx(0.5)

    def test_palettes_are_merged_without_duplicates(self) -> None:
        result = aggregate(
            [
                _analysis(color=ColorProfile(dominant_palette=["#111111", "#222222"])),
                _analysis(color=ColorProfile(dominant_palette=["#222222", "#333333"])),
            ]
        )
        assert result.shared_palette == ["#111111", "#222222", "#333333"]

    def test_styles_are_ordered_by_how_often_they_appear(self) -> None:
        styles = styles_from_analyses(
            [
                _analysis(style_families=[StyleFamily.BOLD]),
                _analysis(style_families=[StyleFamily.PREMIUM]),
                _analysis(style_families=[StyleFamily.PREMIUM]),
            ]
        )
        assert styles[0] is StyleFamily.PREMIUM


class TestStyleProfile:
    def test_an_explicit_pick_outweighs_an_inferred_one(self) -> None:
        """The user asking for premium should not be outvoted by three
        references that happen to be cinematic."""
        profile = VisualStyleProfile.from_sources(
            selected=[StyleFamily.PREMIUM],
            reference_styles=[StyleFamily.CINEMATIC, StyleFamily.CINEMATIC],
        )
        assert profile.weights["premium"] > profile.weights["cinematic"]

    def test_the_strongest_signal_normalises_to_one(self) -> None:
        profile = VisualStyleProfile.from_sources(
            selected=[StyleFamily.PREMIUM], reference_styles=[StyleFamily.MINIMAL]
        )
        assert max(profile.weights.values()) == 1.0

    def test_no_input_gives_an_empty_profile(self) -> None:
        profile = VisualStyleProfile.from_sources(selected=[], reference_styles=[])
        assert profile.weights == {}
        assert profile.describe() == "no stated visual preference"

    def test_top_returns_the_strongest_first(self) -> None:
        profile = VisualStyleProfile.from_sources(
            selected=[StyleFamily.PREMIUM, StyleFamily.MINIMAL],
            reference_styles=[StyleFamily.MINIMAL],
        )
        assert profile.top(1)[0].style is StyleFamily.MINIMAL

    def test_the_description_is_readable(self) -> None:
        profile = VisualStyleProfile.from_sources(
            selected=[StyleFamily.LOCAL_CULTURAL], reference_styles=[]
        )
        assert "local cultural" in profile.describe()

    def test_it_is_deterministic(self) -> None:
        """No learning, no randomness — same inputs, same weights (§Preference)."""
        args = {
            "selected": [StyleFamily.PREMIUM, StyleFamily.BOLD],
            "reference_styles": [StyleFamily.MINIMAL],
        }
        assert (
            VisualStyleProfile.from_sources(**args).weights
            == VisualStyleProfile.from_sources(**args).weights
        )
