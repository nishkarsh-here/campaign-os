"""Aarohan Foods — Guwahati, Assam. Enterprise FMCG. **Fictional.**

The enterprise corner, and the governance stress test. What this company tests
that the other two cannot:

* **Regional adaptation of a national plan.** Aarohan runs a Hindi national
  campaign and an Assamese regional one from the same Campaign Specification.
  That pairing is the benchmark's clearest statement of what localisation is:
  same product, same claims, same brand rules, genuinely different creative.
* **Claims under regulatory weight.** A packaged-food enterprise carries a
  prohibited-claims list that exists because a regulator wrote it, not because
  a founder has taste. The Brand Guardian has real work here, and the contrast
  with Mitti & Bean's four-line list is deliberate.
* **The Northeast, which is where tokenisation is most likely and most
  damaging.** Assam's visual shorthand in national advertising is tea gardens
  and Bihu costume, deployed by people who have never been. The credible cues
  are a river, a winter fog, and a kitchen.
"""

from __future__ import annotations

from app.benchmark.references import style_reference
from app.benchmark.types import (
    BenchmarkCampaign,
    BenchmarkCompany,
    CompanySize,
    LanguagePreference,
    LocalMarketContext,
)
from app.domain.brand import (
    BrandColor,
    BrandProduct,
    BrandProfile,
    BrandTypography,
    BrandVoice,
)
from app.domain.campaign import CampaignBrief
from app.domain.common import Channel, StyleFamily
from app.domain.creative import (
    ChannelCopy,
    CreativeDirection,
    CreativeSpecification,
    NegativeConstraints,
)
from app.domain.reference import Composition, ImageryStyle, Lighting, VisualDensity

SLUG = "aarohan-foods"
BRAND_ID = "bm-brand-aarohan"
ORG_PLACEHOLDER = "bm-org-aarohan"

MARKET = LocalMarketContext(
    city="Guwahati",
    state="Assam",
    localisation_thesis=(
        "Assam is routinely localised by people who have only seen it in "
        "other advertisements, which produces tea gardens and Bihu costume. "
        "What an Assamese household recognises is the Brahmaputra's scale, "
        "winter fog, and a kitchen that looks like theirs."
    ),
    credible_cues=[
        "the Brahmaputra as a wide flat presence, not a scenic backdrop",
        "December fog softening a morning street",
        "an ordinary Assamese kitchen with steel and enamel vessels",
        "bamboo and corrugated roofing in a small-town street",
        "a gamosa present as an everyday object, never as costume",
        "winter light: low, white and diffuse",
    ],
    tokenising_cues=[
        "tea garden rows used as generic 'Assam' shorthand",
        "Bihu dance costume worn by models",
        "one-horned rhinoceros imagery",
        "japi hats as decorative props",
        "'exotic Northeast' framing aimed at outsiders",
    ],
    seasonal_notes=[
        "Rongali Bihu in April is the largest family and purchase occasion",
        "Magh Bihu in January is a feasting festival, distinct in mood",
        "monsoon flooding from June is a genuine constraint on distribution",
    ],
)

LANGUAGES = [
    LanguagePreference(
        language="Assamese",
        usage=(
            "Leads all regional creative. The campaign line is written in "
            "Assamese first; the Hindi and English versions are adaptations."
        ),
        script="Assamese script. Note that ৰ and ৱ differ from Bengali — "
        "using Bengali glyphs is the single most visible localisation failure "
        "available in this market.",
        never_translate=["Aarohan", "Ghoroa", "Xaru"],
    ),
    LanguagePreference(
        language="Hindi",
        usage="Carries the national campaign and reaches non-Assamese speakers "
        "within the Northeast.",
        script="Devanagari.",
        never_translate=["Aarohan", "Ghoroa", "Xaru"],
    ),
    LanguagePreference(
        language="English",
        usage="Packaging, statutory copy, trade and modern-trade communication.",
        script="Latin.",
        never_translate=["Aarohan", "Ghoroa", "Xaru"],
    ),
]

BRAND = BrandProfile(
    id=BRAND_ID,
    organization_id=ORG_PLACEHOLDER,
    name="Aarohan Foods",
    industry="FMCG — packaged foods",
    description=(
        "FICTIONAL. A packaged-foods company headquartered in Guwahati with "
        "about 2,400 employees, three plants in Assam and distribution across "
        "the eight Northeastern states plus West Bengal and Bihar. Spice "
        "blends, mustard oil, pickles and ready mixes."
    ),
    positioning=(
        "The taste a Northeastern household already knows, made to the same "
        "standard every time and available in every town."
    ),
    mission="Put a familiar taste within reach of every family in the region.",
    values=["consistency", "familiarity", "reach", "no shortcuts on sourcing"],
    audience_description=(
        "Mass market across the Northeast: family grocery buyers aged 25-55, "
        "and young adults cooking independently for the first time."
    ),
    voice=BrandVoice(
        tone_attributes=["warm", "trusted", "direct", "unpretentious"],
        person="second",
        writing_rules=[
            "Assamese first for regional work, Hindi for national.",
            "Talk about the dish, not the ingredient's chemistry.",
            "Family is the frame, but never idealised or advertised at.",
            "Every claim on this list and no others.",
        ],
        avoid=[
            "'authentic', 'exotic', 'traditional secret'",
            "gourmet or chef-led framing",
            "nutrition or health positioning of any kind",
            "urban-aspirational language that excludes small-town buyers",
        ],
    ),
    colors=[
        BrandColor(name="Xoru", hex="#C0392B", role="primary"),
        BrandColor(name="Halodhi", hex="#E4A11B", role="accent"),
        BrandColor(name="Bhat", hex="#F4EEE2", role="ground"),
        BrandColor(name="Mati", hex="#2E2A25", role="ink"),
    ],
    typography=BrandTypography(
        heading_font="Bold grotesque",
        body_font="Humanist sans",
        fallback_stack=["Arial", "sans-serif"],
        notes=(
            "Must set Assamese, Devanagari and Latin at matched optical "
            "weight. The Assamese ৰ and ৱ must never be substituted with "
            "Bengali forms — verify the font supports Assamese specifically."
        ),
    ),
    preferred_styles=[StyleFamily.BOLD, StyleFamily.LOCAL_CULTURAL, StyleFamily.FESTIVE],
    products=[
        BrandProduct(
            name="Ghoroa Masala",
            category="Spice blend",
            description="An everyday blend for fish and vegetable curry.",
            key_features=["ground in Assam", "no added colour"],
            differentiators=["blend formulated for freshwater fish"],
        ),
        BrandProduct(
            name="Xaru Mustard Oil",
            category="Edible oil",
            description="Kachi ghani cold-pressed mustard oil.",
            key_features=["cold-pressed", "single-source mustard"],
            differentiators=["pressed within the state"],
        ),
    ],
    approved_claims=[
        "Ground and packed in Assam",
        "No added colour",
        "Cold-pressed (kachi ghani)",
        "Available in over 40,000 stores",
    ],
    prohibited_claims=[
        "healthy",
        "heart-friendly",
        "boosts immunity",
        "reduces cholesterol",
        "no preservatives",
        "100% pure",
        "doctor recommended",
        "clinically proven",
        "weight loss",
    ],
    visual_dos=[
        "real home kitchens with ordinary utensils",
        "the finished dish as it is actually served",
        "winter light: low, white and diffuse",
        "families that look like the region's actual households",
    ],
    visual_donts=[
        "tea gardens used as generic Assam shorthand",
        "Bihu dance costume on models",
        "rhinoceros or japi props",
        "chef-styled plating or garnish tweezers",
        "'exotic Northeast' framing for an outside viewer",
    ],
    logo_rules=[
        "Logo on the ground colour only; never on a photograph of food.",
        "Statutory information must never be obscured by the mark.",
    ],
    legal_line=(
        "Aarohan Foods is a fictional brand created for benchmark purposes. "
        "No claim here is a real product claim."
    ),
)

REFERENCES = [
    style_reference(
        reference_id="aarohan-ref-1",
        style_families=[StyleFamily.LOCAL_CULTURAL, StyleFamily.BOLD],
        composition=Composition.PEOPLE_DOMINANT,
        lighting=Lighting.NATURAL,
        imagery_style=[ImageryStyle.LIFESTYLE, ImageryStyle.HUMAN_CENTRIC],
        palette=["#F4EEE2", "#C0392B", "#2E2A25"],
        brightness=0.6,
        saturation=0.45,
        contrast=0.45,
        temperature="neutral",
        image_text_balance="balanced",
        subject_placement="centre",
        hierarchy="people first, food second, room third",
        density=VisualDensity.BALANCED,
        mood=["warm", "ordinary", "familial"],
        subject_treatment="A real kitchen at a real moment; nothing arranged for the camera.",
        takeaways=[
            "an unstyled kitchen reads as trustworthy where a set does not",
            "mass-market warmth comes from ordinariness, not from production value",
            "faces mid-action beat faces mid-smile",
        ],
        summary="Unstyled domestic kitchen scene with people in the middle of something.",
        confidence=0.83,
        extra_not_transferable=["identifiable faces used as a likeness"],
    ),
    style_reference(
        reference_id="aarohan-ref-2",
        style_families=[StyleFamily.BOLD, StyleFamily.FESTIVE],
        composition=Composition.CENTERED,
        lighting=Lighting.NATURAL,
        imagery_style=[ImageryStyle.PRODUCT_PHOTOGRAPHY],
        palette=["#C0392B", "#E4A11B", "#F4EEE2"],
        brightness=0.65,
        saturation=0.6,
        contrast=0.55,
        temperature="warm",
        image_text_balance="balanced",
        subject_placement="centre",
        hierarchy="the dish, then everything else",
        density=VisualDensity.BALANCED,
        mood=["appetising", "direct"],
        subject_treatment="Food photographed straight on at the distance a person sits from it.",
        takeaways=[
            "eye-level framing reads as a meal; overhead reads as a menu",
            "saturation may run higher for mass-market food than for premium",
        ],
        summary="Direct, appetite-led food photography without chef styling.",
        confidence=0.81,
    ),
    style_reference(
        reference_id="aarohan-ref-3",
        style_families=[StyleFamily.EDITORIAL, StyleFamily.LOCAL_CULTURAL],
        composition=Composition.NEGATIVE_SPACE,
        lighting=Lighting.NATURAL,
        imagery_style=[ImageryStyle.ARCHITECTURAL, ImageryStyle.LIFESTYLE],
        palette=["#F4EEE2", "#2E2A25", "#E4A11B"],
        brightness=0.75,
        saturation=0.15,
        contrast=0.25,
        temperature="cool",
        image_text_balance="image_led",
        subject_placement="lower",
        hierarchy="atmosphere first, subject small within it",
        density=VisualDensity.SPARSE,
        mood=["still", "cold", "early"],
        subject_treatment="Fog flattening depth so a small subject reads against a pale field.",
        takeaways=[
            "regional weather locates a scene more honestly than regional motif",
            "a pale low-contrast field is the easiest ground for type",
        ],
        summary="Winter fog as a compositional device and a locating one.",
        confidence=0.77,
        extra_not_transferable=["recognisable landmarks"],
    ),
]


# --------------------------------------------------------------------------
# Campaign 1 — Apnar Swad. Apnar Ghor. (regional, Assamese)
# --------------------------------------------------------------------------
_C1 = "bm-aarohan-campaign-ghor"

_C1_BRIEF = CampaignBrief(
    campaign_id=_C1,
    title="Apnar Swad. Apnar Ghor.",
    objective=(
        "Defend Ghoroa Masala's share in Assam against national brands entering the Northeast."
    ),
    audience=(
        "Family grocery buyers across Assam, 25-55, cooking freshwater fish and vegetable curry "
        "several times a week."
    ),
    audience_insight=(
        "A national brand's spice blend tastes wrong with local fish, and "
        "everyone knows it. The defence is not heritage; it is the dish."
    ),
    product="Ghoroa Masala",
    key_message="The taste your kitchen already knows.",
    supporting_messages=["Ground and packed in Assam", "No added colour"],
    cta="ASK FOR AAROHAN",
    region="Assam",
    language="Assamese",
    channels=[Channel.INSTAGRAM_PORTRAIT, Channel.WEB_BANNER, Channel.LINKEDIN],
    tone=["warm", "direct", "unpretentious"],
    campaign_tone=["domestic", "confident"],
    brand_requirements=[
        "Assamese script verified for ৰ and ৱ",
        "a real Assamese kitchen, not a set",
        "the dish must be recognisably local",
    ],
    constraints=[
        "no health, nutrition or purity claims",
        "no claim outside the approved list",
        "statutory pack information never obscured",
    ],
    avoid_restrictions=["tea gardens", "Bihu costume", "rhinoceros imagery", "japi props"],
    required_elements=["finished dish as served", "clear area for type"],
    success_criteria=["share retention in Assam", "prompted brand recall"],
    desired_emotional_response="Quiet loyalty — 'this is what we use'.",
    timing_occasion="Year-round, weighted to Rongali Bihu in April",
    rationale="Regional defence built on the dish rather than on the region.",
)

_C1_DIRECTIONS = [
    CreativeDirection(
        campaign_id=_C1,
        ordinal=1,
        title="Ghor-or Xwad",
        big_idea="The curry that tastes like your own kitchen, because it was made for it.",
        strategic_rationale=(
            "Puts the dish at the centre and lets provenance be implied by the food rather than "
            "stated by a landscape."
        ),
        emotional_angle="belonging",
        audience_connection=(
            "A fish curry that tastes right is not a preference; it is an identity."
        ),
        key_message="The taste your kitchen already knows.",
        headline="ঘৰৰ সোৱাদ।",
        subhead="আপোনাৰ পাকঘৰে জনা সোৱাদ।",
        cta="ASK FOR AAROHAN",
        cta_direction="Beneath the subhead, in Assamese with the pack shown small.",
        visual_metaphor="a familiar dish as a form of home",
        composition=(
            "Eye-level, straight on to a served bowl on a steel plate; kitchen soft behind; upper "
            "area clear."
        ),
        subject="A bowl of freshwater fish curry as actually served, on steel.",
        environment="An ordinary Assamese home kitchen, steel and enamel vessels.",
        lighting="Flat daylight from a side window; no styling light.",
        palette=["#C0392B", "#F4EEE2", "#2E2A25"],
        style_families=[StyleFamily.BOLD, StyleFamily.LOCAL_CULTURAL],
        color_direction="Warm and appetising, saturation slightly raised.",
        brand_integration=(
            "Pack appears small at the frame edge; logo composited on the ground colour."
        ),
        product_integration="The blend is present only as the dish it made.",
        regional_considerations=[
            "freshwater fish specifically, not marine",
            "steel and enamel serving vessels",
            "no tea garden, no costume, no japi",
        ],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["tea gardens", "Bihu costume", "rhinoceros", "japi hats"],
            forbidden_text=["healthy", "100% pure", "no preservatives"],
            avoid_styles=["chef plating", "garnish styling"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction where the dish alone carries the frame.",
    ),
    CreativeDirection(
        campaign_id=_C1,
        ordinal=2,
        title="Ma-e Jinika",
        big_idea="The packet your mother reaches for without looking.",
        strategic_rationale=(
            "Habit as the moat. Harder to dislodge than preference and impossible for a new "
            "entrant to claim."
        ),
        emotional_angle="unthinking trust",
        audience_connection="The shelf position every family kitchen has memorised.",
        key_message="The taste your kitchen already knows.",
        headline="নোচোৱাকৈয়ে।",
        subhead="হাতে জানে কোনটো।",
        cta="ASK FOR AAROHAN",
        cta_direction="Small, lower-right.",
        visual_metaphor="memory held in a hand rather than a head",
        composition=(
            "Tight on a hand reaching into a kitchen shelf; the pack among other household things."
        ),
        subject="A hand reaching for the pack on a crowded kitchen shelf.",
        environment="A working Assamese kitchen shelf, genuinely cluttered.",
        lighting="Available kitchen light, slightly dim, unflattering and honest.",
        palette=["#F4EEE2", "#E4A11B", "#2E2A25"],
        style_families=[StyleFamily.LOCAL_CULTURAL, StyleFamily.EDITORIAL],
        color_direction="Muted domestic palette with the pack's red as the only strong note.",
        brand_integration="Pack visible in situ; logo composited above.",
        product_integration="The pack is the subject, but in use rather than on display.",
        regional_considerations=["a real Assamese kitchen shelf with its actual contents"],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["styled pantry", "products faced like a shelf display"],
            forbidden_text=["heart-friendly", "clinically proven"],
            avoid_styles=["retail photography"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction where the pack itself is the subject.",
    ),
    CreativeDirection(
        campaign_id=_C1,
        ordinal=3,
        title="Kuwoli-r Puwa",
        big_idea="A winter morning, and the kitchen is already warm.",
        strategic_rationale=(
            "Uses Assam's most honest seasonal cue — December fog — to locate the brand without a "
            "single motif."
        ),
        emotional_angle="warmth against cold",
        audience_connection="The specific cold of an Assamese December morning.",
        key_message="The taste your kitchen already knows.",
        headline="কুঁৱলীৰ পুৱা।",
        subhead="পাকঘৰ আগতেই গৰম।",
        cta="ASK FOR AAROHAN",
        cta_direction="Centred beneath the subhead.",
        visual_metaphor="a warm interior inside a cold region",
        composition=(
            "From outside a kitchen doorway: fog and pale street beyond, warm interior within; "
            "pale upper field for type."
        ),
        subject="A kitchen doorway seen from a foggy courtyard, steam inside.",
        environment="A small-town Assamese house on a December morning.",
        lighting="Low white diffuse winter light outside; warm interior glow.",
        palette=["#F4EEE2", "#E4A11B", "#2E2A25"],
        style_families=[StyleFamily.EDITORIAL, StyleFamily.LOCAL_CULTURAL],
        color_direction="Cold pale exterior against a warm interior pocket.",
        brand_integration="Logo in the pale fog field, where it reads cleanly.",
        product_integration="Product implied by the cooking, shown only at the edge.",
        regional_considerations=[
            "Assamese winter fog, which is specific and recognisable",
            "bamboo and corrugated roofing in a small-town street",
        ],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["tea gardens", "tourist framing", "Bihu costume"],
            forbidden_text=["boosts immunity"],
            avoid_styles=["exotic Northeast framing"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction shot from outside, and the only one using weather.",
    ),
]

_C1_SPEC = CreativeSpecification(
    campaign_id=_C1,
    direction_id="bm-aarohan-dir-1",
    version=1,
    concept="The curry that tastes like your own kitchen, because it was made for it.",
    visual_story=(
        "A bowl of freshwater fish curry on a steel plate, photographed at "
        "the distance a person actually sits from their lunch. An ordinary "
        "Assamese kitchen falls away behind it. Nothing is arranged."
    ),
    emotional_angle="belonging",
    headline="ঘৰৰ সোৱাদ।",
    subhead="আপোনাৰ পাকঘৰে জনা সোৱাদ।",
    cta="ASK FOR AAROHAN",
    visual_metaphor="a familiar dish as a form of home",
    composition=(
        "Eye-level, straight on to a served bowl; kitchen soft behind; upper area kept clear for "
        "type."
    ),
    focal_point="the surface of the curry where the oil separates",
    subject="A bowl of freshwater fish curry as actually served, on a steel plate.",
    environment="An ordinary Assamese home kitchen with steel and enamel vessels.",
    lighting="Flat daylight from a side window; no styling light; no hard shadow.",
    camera="50mm, f/4, seated eye height",
    palette=["#C0392B", "#F4EEE2", "#2E2A25", "#E4A11B"],
    color_direction="Warm and appetising with saturation slightly raised for mass-market read.",
    style_families=[StyleFamily.BOLD, StyleFamily.LOCAL_CULTURAL],
    mood=["warm", "ordinary", "familial"],
    product_integration="The blend appears only as the dish it made; pack small at the frame edge.",
    people_guidance="Hands only, if any; no faces.",
    brand_integration="Logo composited on the ground colour, never over the food.",
    regional_cues=[
        "freshwater fish specifically, not marine",
        "steel and enamel serving vessels",
        "an ordinary Assamese home kitchen",
    ],
    negative_constraints=NegativeConstraints(
        forbidden_elements=[
            "tea gardens as generic shorthand",
            "Bihu dance costume",
            "rhinoceros imagery",
            "japi hats as props",
            "chef plating or garnish styling",
        ],
        forbidden_text=[
            "healthy",
            "heart-friendly",
            "boosts immunity",
            "no preservatives",
            "100% pure",
        ],
        avoid_styles=["exotic Northeast framing", "gourmet styling"],
        no_text_in_image=True,
    ),
    channel_copy={
        Channel.WEB_BANNER: ChannelCopy(
            headline="ঘৰৰ সোৱাদ।",
            subhead="অসমত পিষা আৰু পেক কৰা।",
        ),
        # Trade audience on LinkedIn: English, distribution-led, no emotion.
        Channel.LINKEDIN: ChannelCopy(
            headline="Ground and packed in Assam.",
            subhead="Ghoroa Masala, now in over 40,000 stores across the Northeast.",
            cta="CONTACT DISTRIBUTION",
        ),
    },
)

CAMPAIGN_GHOR = BenchmarkCampaign(
    slug="apnar-swad-apnar-ghor",
    brief=_C1_BRIEF,
    directions=_C1_DIRECTIONS,
    specification=_C1_SPEC,
    selected_direction_ordinal=1,
    tests=[
        "Assamese script correctness as a localisation requirement",
        "regional defence without regional tokenisation",
        "channel override switching language, register and call to action",
        "enterprise claim discipline under a nine-item prohibited list",
    ],
)


# --------------------------------------------------------------------------
# Campaign 2 — the national Hindi counterpart (the adaptation test)
# --------------------------------------------------------------------------
_C2 = "bm-aarohan-campaign-national"

_C2_BRIEF = CampaignBrief(
    campaign_id=_C2,
    title="Ghar Ka Swad",
    objective="Launch Ghoroa Masala into West Bengal and Bihar using a national Hindi campaign.",
    audience="Family grocery buyers in West Bengal and Bihar, 25-55, unfamiliar with the brand.",
    audience_insight=(
        "Outside Assam the brand has no memory to trade on, so the regional "
        "campaign's central asset — familiarity — is unavailable and the "
        "argument has to be made from scratch."
    ),
    product="Ghoroa Masala",
    key_message="Made in Assam, for the fish you already cook.",
    supporting_messages=["Ground and packed in Assam", "No added colour"],
    cta="TRY IT ONCE",
    region="West Bengal and Bihar",
    language="Hindi",
    channels=[Channel.INSTAGRAM_POST, Channel.WEB_BANNER],
    tone=["direct", "warm"],
    campaign_tone=["confident", "introductory"],
    brand_requirements=[
        "Hindi copy written for the market, not translated from Assamese",
        "provenance stated because it is new information here",
    ],
    constraints=["no health or purity claims", "no claim outside the approved list"],
    avoid_restrictions=["tea gardens", "Bihu costume", "exotic Northeast framing"],
    required_elements=["the dish", "provenance legible"],
    success_criteria=["trial rate", "repeat purchase at eight weeks"],
    desired_emotional_response="Curiosity with low perceived risk.",
    timing_occasion="Launch window, post-monsoon",
    rationale=(
        "The deliberate counterpart to the Assamese campaign. Same product, "
        "same brand rules, same claims — and a different insight, language, "
        "environment and call to action. This pair is the benchmark's "
        "clearest demonstration of adaptation versus translation."
    ),
)

_C2_DIRECTIONS = [
    CreativeDirection(
        campaign_id=_C2,
        ordinal=1,
        title="Assam Se",
        big_idea="Provenance as the reason to try it once.",
        strategic_rationale=(
            "Where familiarity is unavailable, origin is the next strongest trust signal."
        ),
        emotional_angle="curiosity",
        audience_connection=(
            "A Bengali household cooks freshwater fish too — the bridge is the dish."
        ),
        key_message="Made in Assam, for the fish you already cook.",
        headline="असम से।",
        subhead="उसी मछली के लिए, जो आप पहले से बनाते हैं।",
        cta="TRY IT ONCE",
        cta_direction="Beneath the subhead with the pack shown.",
        visual_metaphor="a shared dish across two states",
        composition=(
            "Eye-level on a served bowl in a Bengali kitchen; the pack clearly legible beside it."
        ),
        subject="Freshwater fish curry in a Bengali home, Aarohan pack beside the bowl.",
        environment="An ordinary Kolkata or Patna home kitchen.",
        lighting="Flat daylight from a side window.",
        palette=["#C0392B", "#F4EEE2", "#E4A11B"],
        style_families=[StyleFamily.BOLD, StyleFamily.LOCAL_CULTURAL],
        color_direction="Warm and appetising; the pack red reads as the brand note.",
        brand_integration=(
            "Pack legible because the brand is unknown here — the opposite of the Assam creative."
        ),
        product_integration="Pack and dish share the frame equally.",
        regional_considerations=[
            "a Bengali or Bihari kitchen, not an Assamese one",
            "the dish is the bridge; Assam is a claim, not a setting",
        ],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["tea gardens", "Bihu costume", "Assamese set dressing"],
            forbidden_text=["100% pure", "healthy"],
            avoid_styles=["exotic Northeast framing"],
            no_text_in_image=True,
        ),
        distinctness_note="Provenance-led, and the only direction where the pack must be legible.",
    ),
    CreativeDirection(
        campaign_id=_C2,
        ordinal=2,
        title="Ek Baar",
        big_idea="One meal is the whole ask.",
        strategic_rationale="Minimises perceived risk, which is the only real barrier at launch.",
        emotional_angle="low-stakes invitation",
        audience_connection="Switching a staple is a real risk for a household budget.",
        key_message="Made in Assam, for the fish you already cook.",
        headline="एक बार।",
        subhead="एक बार बनाकर देखिए।",
        cta="TRY IT ONCE",
        cta_direction="Inline, right of the subhead.",
        visual_metaphor="a single trial rather than a commitment",
        composition="A single serving portion, small in a generous empty frame.",
        subject="One small bowl of curry, alone in the frame.",
        environment="A plain kitchen counter, minimal context.",
        lighting="Soft even daylight.",
        palette=["#F4EEE2", "#C0392B", "#2E2A25"],
        style_families=[StyleFamily.MINIMAL, StyleFamily.BOLD],
        color_direction="Pale ground with the curry as the only saturated element.",
        brand_integration="Logo on the pale ground with plenty of room.",
        product_integration="Small pack beside the bowl.",
        regional_considerations=["deliberately unlocated; the offer is the message"],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["abundance or feast staging"],
            forbidden_text=["no preservatives"],
            avoid_styles=["chef plating"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction built on emptiness and a single portion.",
    ),
    CreativeDirection(
        campaign_id=_C2,
        ordinal=3,
        title="Dukaan Mein",
        big_idea="It is already on your shelf.",
        strategic_rationale=(
            "Availability is itself a trust signal in mass FMCG; being findable beats being "
            "persuasive."
        ),
        emotional_angle="reassurance",
        audience_connection=(
            "A brand you can buy locally is a brand that will still be there next month."
        ),
        key_message="Made in Assam, for the fish you already cook.",
        headline="आपकी दुकान में।",
        subhead="चालीस हज़ार से ज़्यादा दुकानों में।",
        cta="TRY IT ONCE",
        cta_direction="Below the subhead, left.",
        visual_metaphor="presence as proof",
        composition=(
            "A neighbourhood shop shelf with the pack among familiar brands; upper area open."
        ),
        subject="The pack on a kirana shop shelf beside everyday competitors.",
        environment="A small neighbourhood grocery in Kolkata or Patna.",
        lighting="Available shop lighting, slightly green, honest.",
        palette=["#F4EEE2", "#E4A11B", "#2E2A25"],
        style_families=[StyleFamily.EDITORIAL, StyleFamily.BOLD],
        color_direction="Busy but readable; the pack red as the anchor.",
        brand_integration="Pack in situ; logo composited in the open area.",
        product_integration="Retail presence is the product story.",
        regional_considerations=["a real kirana shop in the launch market"],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["modern-trade aisle", "competitor brands legible"],
            forbidden_text=["best in India"],
            avoid_styles=["retail stock photography"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction set in retail rather than a home.",
    ),
]

_C2_SPEC = CreativeSpecification(
    campaign_id=_C2,
    direction_id="bm-aarohan-dir-4",
    version=1,
    concept="Provenance as the reason to try it once.",
    visual_story=(
        "A Bengali home kitchen, a bowl of freshwater fish curry, and the "
        "Aarohan pack legible beside it. In Assam the pack hides at the frame "
        "edge because everyone knows it. Here it has to introduce itself."
    ),
    emotional_angle="curiosity",
    headline="असम से।",
    subhead="उसी मछली के लिए, जो आप पहले से बनाते हैं।",
    cta="TRY IT ONCE",
    visual_metaphor="a shared dish across two states",
    composition="Eye-level on a served bowl; pack legible beside it; upper area clear for type.",
    focal_point="the pack sitting beside a familiar dish",
    subject="Freshwater fish curry in a Bengali home with the Aarohan pack beside the bowl.",
    environment="An ordinary Kolkata or Patna home kitchen.",
    lighting="Flat daylight from a side window; no styling light.",
    camera="50mm, f/4, seated eye height",
    palette=["#C0392B", "#F4EEE2", "#E4A11B"],
    color_direction="Warm and appetising; pack red as the brand note.",
    style_families=[StyleFamily.BOLD, StyleFamily.LOCAL_CULTURAL],
    mood=["warm", "direct", "introductory"],
    product_integration="Pack and dish share the frame; the pack must be legible.",
    people_guidance="Hands only, if any; no faces.",
    brand_integration="Logo composited on the ground colour, never over the food.",
    regional_cues=[
        "a Bengali or Bihari kitchen, not an Assamese one",
        "Assam appears as a stated origin, never as a setting",
    ],
    negative_constraints=NegativeConstraints(
        forbidden_elements=[
            "tea gardens",
            "Bihu costume",
            "Assamese set dressing",
            "chef plating",
        ],
        forbidden_text=["healthy", "100% pure", "boosts immunity", "no preservatives"],
        avoid_styles=["exotic Northeast framing", "gourmet styling"],
        no_text_in_image=True,
    ),
    channel_copy={
        Channel.WEB_BANNER: ChannelCopy(
            headline="असम से।",
            subhead="चालीस हज़ार से ज़्यादा दुकानों में।",
        ),
    },
)

CAMPAIGN_NATIONAL = BenchmarkCampaign(
    slug="ghar-ka-swad",
    brief=_C2_BRIEF,
    directions=_C2_DIRECTIONS,
    specification=_C2_SPEC,
    selected_direction_ordinal=1,
    tests=[
        "same product and brand, different region, different insight",
        "national versus regional adaptation from one brand",
        "pack legibility inverted by audience familiarity",
    ],
)


# --------------------------------------------------------------------------
# Campaign 3 — Magh Bihu
# --------------------------------------------------------------------------
_C3 = "bm-aarohan-campaign-bihu"

_C3_BRIEF = CampaignBrief(
    campaign_id=_C3,
    title="Bhogali-r Pise",
    objective="Drive Xaru Mustard Oil volume through the Magh Bihu feasting fortnight in Assam.",
    audience="Household cooks across Assam preparing for Magh Bihu, 25-55.",
    audience_insight=(
        "Magh Bihu is about cooking volume, not refinement. The purchase "
        "decision is made on quantity and reliability days in advance."
    ),
    product="Xaru Mustard Oil",
    key_message="Enough for the whole fortnight.",
    supporting_messages=["Cold-pressed (kachi ghani)", "Ground and packed in Assam"],
    cta="STOCK UP FOR BIHU",
    region="Assam",
    language="Assamese",
    channels=[Channel.INSTAGRAM_POST, Channel.INSTAGRAM_STORY, Channel.WEB_BANNER],
    tone=["warm", "direct"],
    campaign_tone=["festive", "practical"],
    brand_requirements=[
        "Magh Bihu specifically, not Rongali Bihu — the moods differ",
        "Assamese script verified",
    ],
    constraints=["no health or purity claims about oil", "no cooking-medium health framing"],
    avoid_restrictions=["Bihu dance costume", "tea gardens", "japi props"],
    required_elements=["scale of cooking visible", "clear type area"],
    success_criteria=["fortnight volume", "large-pack mix"],
    desired_emotional_response="Practical readiness for a big cooking week.",
    timing_occasion="Magh Bihu, mid-January",
    rationale="Festival campaign where the festival is a workload, not a costume.",
)

_C3_DIRECTIONS = [
    CreativeDirection(
        campaign_id=_C3,
        ordinal=1,
        title="Gotei Pokhek",
        big_idea="A fortnight of cooking starts with one decision.",
        strategic_rationale=(
            "Frames the purchase as preparation for workload, which is how the category is "
            "actually bought."
        ),
        emotional_angle="competence",
        audience_connection="The pre-festival stock-up is its own ritual.",
        key_message="Enough for the whole fortnight.",
        headline="গোটেই পখেক।",
        subhead="এবাৰতে যথেষ্ট।",
        cta="STOCK UP FOR BIHU",
        cta_direction="Beneath the subhead with pack size shown.",
        visual_metaphor="provisioning as foresight",
        composition=(
            "A kitchen counter staged for volume cooking: large vessels, the oil tin among them."
        ),
        subject="A large tin of mustard oil among vessels prepared for a feast.",
        environment="An Assamese home kitchen the day before Magh Bihu.",
        lighting="Low white winter daylight, diffuse.",
        palette=["#E4A11B", "#F4EEE2", "#2E2A25"],
        style_families=[StyleFamily.LOCAL_CULTURAL, StyleFamily.FESTIVE],
        color_direction="Warm yellow oil note against a pale cold ground.",
        brand_integration="Logo on the pale wall behind.",
        product_integration="The tin sits among the vessels, in scale with the task.",
        regional_considerations=[
            "Magh Bihu's practical mood, distinct from Rongali Bihu's celebration",
            "steel and aluminium vessels of the size actually used",
        ],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["Bihu dance costume", "japi", "tea gardens"],
            forbidden_text=["heart-friendly", "healthy cooking oil"],
            avoid_styles=["festival stock imagery"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction about quantity.",
    ),
    CreativeDirection(
        campaign_id=_C3,
        ordinal=2,
        title="Pitha-r Gondho",
        big_idea="The smell of the first pitha reaching the next house.",
        strategic_rationale=(
            "Sells the sensory payoff rather than the purchase, giving the campaign an emotional "
            "register the others lack."
        ),
        emotional_angle="appetite and anticipation",
        audience_connection="Everyone knows which neighbour starts frying first.",
        key_message="Enough for the whole fortnight.",
        headline="পিঠাৰ গোন্ধ।",
        subhead="ওচৰৰ ঘৰলৈকে যায়।",
        cta="STOCK UP FOR BIHU",
        cta_direction="Small, lower-left.",
        visual_metaphor="aroma crossing a boundary",
        composition=(
            "Steam and frying haze at the doorway of a kitchen, seen from outside; pale fog beyond."
        ),
        subject="Pitha frying, steam escaping through an open kitchen door.",
        environment="A small-town Assamese house at dusk in January.",
        lighting="Warm interior light against cold blue exterior.",
        palette=["#E4A11B", "#2E2A25", "#F4EEE2"],
        style_families=[StyleFamily.FESTIVE, StyleFamily.EDITORIAL],
        color_direction="Warm interior pocket against a cold exterior.",
        brand_integration="Logo in the dark exterior field.",
        product_integration="Product implied by the frying; tin visible at the edge.",
        regional_considerations=["pitha specifically, and the January cold that frames it"],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["dance performance", "costume"],
            forbidden_text=["no preservatives"],
            avoid_styles=["festival stock imagery"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction built on steam and dusk.",
    ),
    CreativeDirection(
        campaign_id=_C3,
        ordinal=3,
        title="Ekeliage",
        big_idea="Four people, one kitchen, no argument.",
        strategic_rationale=(
            "Puts the family in the frame doing work rather than celebrating, avoiding the "
            "festival-advertising default."
        ),
        emotional_angle="shared effort",
        audience_connection="The festival kitchen is crowded and everyone has a job.",
        key_message="Enough for the whole fortnight.",
        headline="একেলগে।",
        subhead="সকলোৱে হাত লগায়।",
        cta="STOCK UP FOR BIHU",
        cta_direction="Right-aligned beneath the subhead.",
        visual_metaphor="a kitchen operating as a team",
        composition=(
            "Slightly high and wide; four people at different tasks; nobody looking at camera."
        ),
        subject="A family cooking together, each at a separate task.",
        environment="A crowded Assamese kitchen mid-preparation.",
        lighting="Mixed daylight and interior bulb, honest and uneven.",
        palette=["#F4EEE2", "#E4A11B", "#C0392B"],
        style_families=[StyleFamily.LOCAL_CULTURAL, StyleFamily.BOLD],
        color_direction="Busy and warm, true skin tones.",
        brand_integration="Logo in the upper wall area.",
        product_integration="The tin is in use on the counter, unremarked.",
        regional_considerations=["ordinary contemporary Assamese clothing, never costume"],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["Bihu costume", "posed family portrait", "dance"],
            forbidden_text=["clinically proven"],
            avoid_styles=["stock-photo staging"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction with a full family working.",
    ),
]

_C3_SPEC = CreativeSpecification(
    campaign_id=_C3,
    direction_id="bm-aarohan-dir-7",
    version=1,
    concept="A fortnight of cooking starts with one decision.",
    visual_story=(
        "The day before Magh Bihu. A kitchen counter is laid out for volume "
        "cooking — large steel vessels, soaked rice, and a big tin of mustard "
        "oil standing among them, in scale with the work ahead."
    ),
    emotional_angle="competence",
    headline="গোটেই পখেক।",
    subhead="এবাৰতে যথেষ্ট।",
    cta="STOCK UP FOR BIHU",
    visual_metaphor="provisioning as foresight",
    composition=(
        "Counter staged for volume cooking; oil tin among the vessels; upper wall clear for type."
    ),
    focal_point="the tin standing at the scale of the task",
    subject="A large tin of mustard oil among vessels prepared for a feast.",
    environment="An Assamese home kitchen the day before Magh Bihu.",
    lighting="Low white winter daylight, diffuse, no hard shadow.",
    camera="35mm, f/5.6, standing height looking down across the counter",
    palette=["#E4A11B", "#F4EEE2", "#2E2A25"],
    color_direction="Warm yellow oil note against a pale cold winter ground.",
    style_families=[StyleFamily.LOCAL_CULTURAL, StyleFamily.FESTIVE],
    mood=["practical", "anticipatory", "cold-bright"],
    product_integration="The tin sits among the vessels, in scale with the task, label legible.",
    people_guidance="Hands at the frame edge at most; no faces.",
    brand_integration="Logo composited on the pale wall behind.",
    regional_cues=[
        "Magh Bihu's practical mood, distinct from Rongali Bihu's celebration",
        "steel and aluminium vessels of the size actually used",
        "Assamese January light: low, white, diffuse",
    ],
    negative_constraints=NegativeConstraints(
        forbidden_elements=[
            "Bihu dance costume",
            "japi hats",
            "tea gardens",
            "rhinoceros imagery",
        ],
        forbidden_text=[
            "heart-friendly",
            "healthy",
            "reduces cholesterol",
            "100% pure",
        ],
        avoid_styles=["festival stock imagery", "exotic Northeast framing"],
        no_text_in_image=True,
    ),
    channel_copy={
        Channel.WEB_BANNER: ChannelCopy(
            headline="গোটেই পখেক।",
            subhead="মাঘ বিহুৰ বাবে এবাৰতে।",
        ),
    },
)

CAMPAIGN_BIHU = BenchmarkCampaign(
    slug="bhogali-r-pise",
    brief=_C3_BRIEF,
    directions=_C3_DIRECTIONS,
    specification=_C3_SPEC,
    selected_direction_ordinal=1,
    tests=[
        "festival specificity — Magh Bihu is not Rongali Bihu",
        "occasion campaign under enterprise claim governance",
        "regional festival without costume or performance",
    ],
)


COMPANY = BenchmarkCompany(
    slug=SLUG,
    display_name="Aarohan Foods",
    size=CompanySize.ENTERPRISE,
    industry="FMCG — packaged foods",
    market=MARKET,
    languages=LANGUAGES,
    brand=BRAND,
    references=REFERENCES,
    campaigns=[CAMPAIGN_GHOR, CAMPAIGN_NATIONAL, CAMPAIGN_BIHU],
    selection_rationale=(
        "The enterprise case, carrying both the heaviest claim governance and "
        "the national-versus-regional pair. Its Assamese and Hindi campaigns "
        "share a product, a brand and a claims list while differing in "
        "insight, language, environment and call to action — which is the "
        "distinction the whole benchmark exists to measure."
    ),
)
