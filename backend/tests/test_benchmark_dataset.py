"""The benchmark dataset asserts things about itself.

A synthetic dataset is only worth something if its claims are mechanically
checked. "The three directions are meaningfully different" and "localisation
is not translation" are exactly the kind of statements that decay into
wishful documentation unless a test fails when they stop being true.

These run offline with no database and no provider. They are checks on the
data, not on the pipeline — the pipeline is tested everywhere else.
"""

from __future__ import annotations

import pytest

from app.benchmark import (
    BENCHMARK_CHANNELS,
    CASES,
    COMPANIES,
    NAIVE_VS_HYPERLOCAL,
    all_campaigns,
    campaign,
    company,
)
from app.domain.creative import copy_for

pytestmark = pytest.mark.unit

ALL = all_campaigns()


# --------------------------------------------------------------- shape
class TestTheDatasetIsWhatItClaims:
    def test_three_companies_three_sizes_three_cities_three_industries(self) -> None:
        assert len(COMPANIES) == 3
        assert len({c.size for c in COMPANIES}) == 3
        assert len({c.market.city for c in COMPANIES}) == 3
        assert len({c.industry for c in COMPANIES}) == 3

    def test_nine_campaigns_three_per_company(self) -> None:
        assert len(ALL) == 9
        for owner in COMPANIES:
            assert len(owner.campaigns) == 3, owner.slug

    def test_every_campaign_offers_exactly_three_directions(self) -> None:
        for _, entry in ALL:
            assert len(entry.directions) == 3, entry.slug

    def test_slugs_are_unique_across_the_whole_dataset(self) -> None:
        slugs = [entry.slug for _, entry in ALL]
        assert len(slugs) == len(set(slugs))

    def test_every_company_is_marked_fictional(self) -> None:
        """A synthetic brand that does not say so is a liability."""
        for owner in COMPANIES:
            text = f"{owner.brand.description} {owner.brand.legal_line}".lower()
            assert "fictional" in text, owner.slug

    def test_lookup_helpers_raise_usefully(self) -> None:
        assert company("nila-living").market.city == "Kochi"
        with pytest.raises(KeyError, match="Available"):
            company("no-such-company")
        with pytest.raises(KeyError, match="Available"):
            campaign("no-such-campaign")


# ------------------------------------------------- directions are different
class TestDirectionsAreMeaningfullyDifferent:
    """The brief's instruction was 'do not simply rewrite the same idea'.

    Distinctness is measured the way the product measures it (M5): on the
    structured choices, not on the prose. Two directions can read very
    differently and be the same poster.
    """

    @pytest.mark.parametrize("slug", [entry.slug for _, entry in ALL])
    def test_the_structured_choices_differ(self, slug: str) -> None:
        _, entry = campaign(slug)
        for field in ("subject", "environment", "composition", "lighting", "headline"):
            values = [getattr(d, field) for d in entry.directions]
            assert len(set(values)) == 3, f"{slug}: {field} repeats across directions"

    @pytest.mark.parametrize("slug", [entry.slug for _, entry in ALL])
    def test_each_direction_says_how_it_differs(self, slug: str) -> None:
        _, entry = campaign(slug)
        notes = [d.distinctness_note for d in entry.directions]
        assert all(notes), f"{slug}: a direction does not say what makes it distinct"
        assert len(set(notes)) == 3

    @pytest.mark.parametrize("slug", [entry.slug for _, entry in ALL])
    def test_the_selected_direction_exists(self, slug: str) -> None:
        _, entry = campaign(slug)
        ordinals = {d.ordinal for d in entry.directions}
        assert entry.selected_direction_ordinal in ordinals


# ------------------------------------------------------------ localisation
class TestCitySpecificContext:
    def test_each_city_names_both_credible_and_tokenising_cues(self) -> None:
        """A market context that only lists what to include is a stereotype
        generator. The refusal list is the load-bearing half."""
        for owner in COMPANIES:
            assert owner.market.credible_cues, owner.slug
            assert owner.market.tokenising_cues, owner.slug
            assert owner.market.localisation_thesis

    def test_no_city_shares_a_tokenising_cue_with_another(self) -> None:
        seen: dict[str, str] = {}
        for owner in COMPANIES:
            for cue in owner.market.tokenising_cues:
                assert cue not in seen, f"{cue!r} claimed by {seen.get(cue)} and {owner.slug}"
                seen[cue] = owner.slug

    @pytest.mark.parametrize("owner", COMPANIES, ids=[c.slug for c in COMPANIES])
    def test_a_campaign_never_imports_another_citys_tokens(self, owner) -> None:
        """No cross-location contamination.

        Kerala's houseboats must not appear in a Jaipur campaign, and Jaipur's
        palaces must not appear in Kochi's — not even as something to avoid,
        because a refusal list borrowed from elsewhere is evidence the
        localisation was generic.
        """
        others = [o for o in COMPANIES if o.slug != owner.slug]
        foreign_terms = {
            term
            for other in others
            for cue in other.market.tokenising_cues
            for term in _distinctive_terms(cue)
        }
        mine = {term for cue in owner.market.tokenising_cues for term in _distinctive_terms(cue)}
        foreign_only = foreign_terms - mine

        for entry in owner.campaigns:
            haystack = _campaign_text(entry).lower()
            for term in foreign_only:
                assert term not in haystack, (
                    f"{entry.slug} mentions {term!r}, which belongs to another city"
                )

    @pytest.mark.parametrize("owner", COMPANIES, ids=[c.slug for c in COMPANIES])
    def test_local_context_survives_into_the_approved_specification(self, owner) -> None:
        """Localisation has to reach the artefact generation compiles from.

        A region named only in the brief and lost by the Creative
        Specification is localisation that never reaches an image.
        """
        consumer = [e for e in owner.campaigns if e.brief.region and "trade" not in e.slug]
        localised = [
            e
            for e in consumer
            if e.specification.regional_cues
            or e.specification.negative_constraints.forbidden_elements
        ]
        assert localised, f"{owner.slug}: no campaign carries local context into its specification"

    def test_every_brand_forbids_its_own_citys_clichés(self) -> None:
        for owner in COMPANIES:
            donts = " ".join(owner.brand.visual_donts).lower()
            hits = [
                c for c in owner.market.tokenising_cues if _distinctive_terms(c) & _words(donts)
            ]
            assert hits, f"{owner.slug}: brand rules do not forbid any local cliché"


def _words(text: str) -> set[str]:
    return set(text.replace(",", " ").replace(".", " ").split())


def _distinctive_terms(cue: str) -> set[str]:
    """The nouns in a cue that would identify it anywhere else.

    Deliberately crude: short and generic words are dropped so that ordinary
    vocabulary ('as', 'used', 'imagery') cannot make two unrelated cues look
    like the same one.
    """
    stop = {
        "used",
        "generic",
        "shorthand",
        "framing",
        "imagery",
        "props",
        "costume",
        "aimed",
        "outsiders",
        "models",
        "worn",
        "decorative",
        "border",
        "treatment",
        "colour",
        "wide",
        "shots",
        "backdrop",
        "architecture",
        "dressed",
        "tourism",
        "arranged",
        "hats",
        "faces",
        "boats",
        "gardens",
        "rows",
        "dance",
        "and",
        "the",
        "for",
        "with",
        "that",
        "set",
        "old",
        "city",
        "one",
        "horned",
        "exotic",
        "northeast",
        "nostalgic",
        "royal",
        "mirror",
        "work",
        "folk",
        "dancers",
        "tourist",
        "brochure",
        "saturated",
        "gold",
        "pink",
    }
    return {w for w in _words(cue.lower()) if len(w) > 4 and w not in stop}


def _campaign_text(entry) -> str:
    parts = [entry.brief.model_dump_json(), entry.specification.model_dump_json()]
    parts.extend(d.model_dump_json() for d in entry.directions)
    return " ".join(parts)


# ---------------------------------------------------------------- language
class TestLanguageSpecificCopy:
    def test_every_company_declares_how_each_language_is_used(self) -> None:
        for owner in COMPANIES:
            assert owner.languages
            for language in owner.languages:
                assert language.usage and language.script

    def test_brand_marks_are_never_translated(self) -> None:
        """A brand name that survives translation is the cheapest and most
        common localisation failure.

        Matched on the distinctive first token rather than the full legal
        name, because "Aarohan Foods" is the company and "Aarohan" is the
        mark that appears in copy.
        """
        for owner in COMPANIES:
            mark = owner.brand.name.split()[0]
            for language in owner.languages:
                protected = " ".join(language.never_translate)
                assert mark in protected, f"{owner.slug}/{language.language} may translate {mark!r}"

    def test_regional_campaigns_carry_non_latin_headlines(self) -> None:
        """Malayalam and Assamese creative must actually be in those scripts.

        Copy written in Latin and labelled Malayalam is the exact failure the
        benchmark's naive baseline makes.
        """
        for slug in ("veettil-oru-feeling", "onathinu-veedu", "apnar-swad-apnar-ghor"):
            _, entry = campaign(slug)
            assert not entry.specification.headline.isascii(), (
                f"{slug} headline is ASCII; it is supposed to be in a local script"
            )

    def test_the_same_product_gets_a_different_idea_per_language(self) -> None:
        """The national/regional pair. Same brand, same product, same claims —
        and a different insight, headline and call to action."""
        _, regional = campaign("apnar-swad-apnar-ghor")
        _, national = campaign("ghar-ka-swad")

        assert regional.brief.product == national.brief.product
        assert regional.brief.language != national.brief.language
        assert regional.brief.region != national.brief.region
        assert regional.brief.audience_insight != national.brief.audience_insight
        assert regional.brief.cta != national.brief.cta
        assert regional.specification.headline != national.specification.headline
        assert regional.specification.environment != national.specification.environment


# --------------------------------------------------------- brand consistency
class TestBrandConsistencyAcrossCampaigns:
    @pytest.mark.parametrize("owner", COMPANIES, ids=[c.slug for c in COMPANIES])
    def test_palettes_stay_inside_the_brand(self, owner) -> None:
        approved = {c.hex.upper() for c in owner.brand.colors}
        for entry in owner.campaigns:
            used = {c.upper() for c in entry.specification.palette}
            assert used <= approved, (
                f"{entry.slug} uses colour outside the brand: {used - approved}"
            )

    @pytest.mark.parametrize("owner", COMPANIES, ids=[c.slug for c in COMPANIES])
    def test_no_campaign_may_say_a_prohibited_thing(self, owner) -> None:
        """The claim the Brand Guardian exists to catch must not be sitting in
        the approved copy to begin with."""
        for entry in owner.campaigns:
            approved_copy = " ".join(
                filter(
                    None,
                    [
                        entry.specification.headline,
                        entry.specification.subhead,
                        entry.specification.cta,
                        entry.brief.key_message,
                        *entry.brief.supporting_messages,
                    ],
                )
            ).lower()
            for claim in owner.brand.prohibited_claims:
                assert claim.lower() not in approved_copy, f"{entry.slug} states {claim!r}"

    @pytest.mark.parametrize("owner", COMPANIES, ids=[c.slug for c in COMPANIES])
    def test_every_specification_refuses_brand_text_in_the_image(self, owner) -> None:
        """ADR-006 is not negotiable per campaign."""
        for entry in owner.campaigns:
            assert entry.specification.negative_constraints.no_text_in_image is True, entry.slug

    def test_governance_weight_rises_with_company_size(self) -> None:
        """The benchmark's governance dimension, asserted rather than asserted
        about: the enterprise must carry more prohibited claims than the
        startup, or the comparison is not testing anything."""
        by_slug = {c.slug: c for c in COMPANIES}
        startup = len(by_slug["mitti-and-bean"].brand.prohibited_claims)
        enterprise = len(by_slug["aarohan-foods"].brand.prohibited_claims)
        assert enterprise > startup


# ------------------------------------------------------------ channel copy
class TestChannelCopy:
    def test_overrides_only_name_channels_the_campaign_declares(self) -> None:
        """The M11 service-boundary rule, enforced in the dataset itself."""
        for _, entry in ALL:
            declared = set(entry.brief.channels)
            overridden = set(entry.specification.channel_copy)
            assert overridden <= declared, (
                f"{entry.slug} overrides {overridden - declared}, which it does not run"
            )

    def test_an_absent_override_inherits(self) -> None:
        _, entry = campaign("apni-raftaar-apna-pause")
        from app.domain.common import Channel

        assert Channel.INSTAGRAM_PORTRAIT in entry.brief.channels
        assert Channel.INSTAGRAM_PORTRAIT not in entry.specification.channel_copy
        resolved = copy_for(entry.specification, Channel.INSTAGRAM_PORTRAIT)
        assert resolved.headline == entry.specification.headline
        assert resolved.subhead == entry.specification.subhead
        assert resolved.cta == entry.specification.cta

    def test_an_override_changes_only_what_it_names(self) -> None:
        _, entry = campaign("apni-raftaar-apna-pause")
        from app.domain.common import Channel

        resolved = copy_for(entry.specification, Channel.INSTAGRAM_STORY)
        assert resolved.headline == "Thehro.", "the story shortens the headline"
        assert resolved.headline != entry.specification.headline
        # Unnamed fields inherit rather than blanking.
        assert resolved.subhead == entry.specification.subhead
        assert resolved.cta == entry.specification.cta

    def test_copy_cannot_remove_a_line_only_change_it(self) -> None:
        """A documented limit, asserted so the dataset cannot pretend
        otherwise.

        `ChannelCopy` uses None for "inherit", so there is no value that
        means "this channel has no subhead". Dropping a line is a geometry
        decision the layout makes, and a benchmark that quietly assumed
        otherwise would be describing a product that does not exist.
        """
        from app.domain.common import Channel
        from app.domain.creative import ChannelCopy

        _, entry = campaign("apni-raftaar-apna-pause")
        attempted = entry.specification.model_copy(
            update={"channel_copy": {Channel.INSTAGRAM_STORY: ChannelCopy(headline="Thehro.")}}
        )
        assert copy_for(attempted, Channel.INSTAGRAM_STORY).subhead == entry.specification.subhead

        with pytest.raises(ValueError):
            ChannelCopy(headline="Thehro.", subhead="")

    def test_at_least_one_override_adapts_rather_than_shortens(self) -> None:
        """The benchmark's channel claim is that a variant addresses a
        different reader, not merely a different aspect ratio."""
        _, entry = campaign("apnar-swad-apnar-ghor")
        from app.domain.common import Channel

        default = copy_for(entry.specification, Channel.INSTAGRAM_PORTRAIT)
        linkedin = copy_for(entry.specification, Channel.LINKEDIN)
        assert linkedin.headline != default.headline
        assert linkedin.cta != default.cta
        assert linkedin.headline.isascii(), "the trade channel switches to English"
        assert not default.headline.isascii(), "the consumer channel stays in Assamese"

    def test_the_benchmark_channels_are_ones_the_product_has(self) -> None:
        from app.domain.common import CHANNEL_DIMENSIONS

        for channel in BENCHMARK_CHANNELS:
            assert channel in CHANNEL_DIMENSIONS


# ----------------------------------------------------------------- matrix
class TestTheMatrixMatchesTheDataset:
    def test_every_case_references_real_campaigns(self) -> None:
        known = {entry.slug for _, entry in ALL}
        for case in CASES:
            unknown = set(case.campaign_slugs) - known
            assert not unknown, f"{case.case_id} references {unknown}"

    def test_case_ids_are_unique(self) -> None:
        ids = [c.case_id for c in CASES]
        assert len(ids) == len(set(ids))

    def test_every_case_names_a_control(self) -> None:
        """A comparison that varies everything measures nothing."""
        for case in CASES:
            assert case.held_constant and case.varied
            assert case.expected_signal

    def test_the_dimensions_are_actually_exercised(self) -> None:
        from app.benchmark.matrix import LocalisationDimension

        covered = {case.dimension for case in CASES}
        missing = set(LocalisationDimension) - covered
        assert not missing, f"no case covers {missing}"

    def test_the_naive_comparison_points_at_a_real_campaign(self) -> None:
        owner, entry = campaign(NAIVE_VS_HYPERLOCAL.campaign_slug)
        assert owner.slug == "nila-living"
        assert entry.specification.headline
        assert NAIVE_VS_HYPERLOCAL.naive_failure_modes
        assert NAIVE_VS_HYPERLOCAL.what_produces_the_difference
