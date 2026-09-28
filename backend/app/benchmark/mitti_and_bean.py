"""Mitti & Bean — Jaipur, Rajasthan. Startup, premium cold brew. **Fictional.**

The startup corner of the benchmark. What this company tests that the other
two cannot:

* **Localisation under the strongest pull toward cliché.** Jaipur has the most
  recognisable visual shorthand of the three cities, and that shorthand is
  almost entirely wrong for a contemporary coffee brand aimed at 22-year-olds.
  Every direction here is a test of whether the system can reach for sandstone
  *light* and *texture* without reaching for a palace.
* **Code-mixed copy.** Hindi and English are not two audiences here; they are
  one audience that speaks both in the same sentence. "Thoda Thehro." is not a
  translation of anything.
* **Light governance.** A founder approves their own headline, so the Brand
  Brain is short and the prohibited-claims list is about honesty rather than
  regulatory exposure — the deliberate contrast with Aarohan Foods.
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
from app.domain.reference import (
    Composition,
    ImageryStyle,
    Lighting,
    VisualDensity,
)

SLUG = "mitti-and-bean"
BRAND_ID = "bm-brand-mitti"
ORG_PLACEHOLDER = "bm-org-mitti"

MARKET = LocalMarketContext(
    city="Jaipur",
    state="Rajasthan",
    localisation_thesis=(
        "Jaipur is read by outsiders as heritage and by its own under-30s as a "
        "working city with a young café scene. The campaign has to be legible "
        "to the second group, which means borrowing the city's light and "
        "materials while refusing its postcard."
    ),
    credible_cues=[
        "warm sandstone light in the late afternoon",
        "contemporary café interiors with local stone and raw plaster",
        "hand-thrown terracotta and unglazed ceramic",
        "scooters and students outside a small independent café",
        "block-print texture used as a surface, never as a motif",
        "dry-season dust softening the light",
    ],
    tokenising_cues=[
        "palace or fort architecture as a backdrop",
        "camels, elephants or folk dancers",
        "turbans and mirror-work as costume",
        "saturated 'royal' pink and gold treatment",
        "tourist-brochure wide shots of the old city",
    ],
    seasonal_notes=[
        "March to June is genuinely hot; iced drinks need no persuasion",
        "university exam season in November and April drives late-night demand",
        "October to March is tourist season and the customer mix shifts",
    ],
)

LANGUAGES = [
    LanguagePreference(
        language="Hindi",
        usage=(
            "Leads on headlines and anything emotional. Code-mixed with "
            "English in the same line, the way the audience actually speaks."
        ),
        script="Devanagari for body copy; Roman transliteration for headlines, "
        "because the audience reads Hinglish faster than either pure script.",
        never_translate=["Mitti & Bean", "cold brew", "Slow Steep"],
    ),
    LanguagePreference(
        language="English",
        usage="Carries product detail, the call to action and anything a "
        "tourist or a wholesale buyer needs to understand.",
        script="Latin.",
        never_translate=["Mitti & Bean", "Slow Steep"],
    ),
]

BRAND = BrandProfile(
    id=BRAND_ID,
    organization_id=ORG_PLACEHOLDER,
    name="Mitti & Bean",
    industry="Speciality coffee — cold brew",
    description=(
        "FICTIONAL. A two-café speciality cold brew company in Jaipur, founded "
        "by a former architect and a barista. Roasts in small batches, steeps "
        "for eighteen hours, sells in-store and in glass bottles."
    ),
    positioning=(
        "Premium cold brew for people whose days move too fast — sold as a "
        "deliberate pause rather than a caffeine hit."
    ),
    mission="Make a slow thing worth stopping for, in a city people rush through.",
    values=["slowness as a craft", "local materials", "honest strength", "no theatre"],
    audience_description=(
        "18-30: university students, first-job professionals, photographers "
        "and designers, plus visitors who find the café through Instagram."
    ),
    voice=BrandVoice(
        tone_attributes=["warm", "unhurried", "wry", "plain-spoken"],
        person="second",
        writing_rules=[
            "Short lines. A headline is rarely more than three words.",
            "Hinglish is native here, not a gimmick — mix freely in headlines.",
            "Describe the pause, not the product's specifications.",
            "Never oversell strength; the brew is strong and does not need adjectives.",
        ],
        avoid=[
            "exclamation marks",
            "hustle-culture language",
            "'artisanal', 'handcrafted', 'curated'",
            "wellness claims of any kind",
        ],
    ),
    colors=[
        BrandColor(name="Mitti", hex="#B07A52", role="primary"),
        BrandColor(name="Kaali", hex="#1C1A17", role="ink"),
        BrandColor(name="Chuna", hex="#EFE7DA", role="ground"),
        BrandColor(name="Neem", hex="#5C6B54", role="accent"),
    ],
    typography=BrandTypography(
        heading_font="Grotesque sans, medium weight",
        body_font="Humanist sans",
        fallback_stack=["system-ui", "sans-serif"],
        notes=(
            "Devanagari and Latin must sit on the same baseline and optical "
            "weight. Never set Devanagari smaller than the Latin beside it."
        ),
    ),
    preferred_styles=[StyleFamily.PREMIUM, StyleFamily.EDITORIAL, StyleFamily.MINIMAL],
    products=[
        BrandProduct(
            name="Slow Steep",
            category="Cold brew concentrate",
            description="Eighteen-hour steep, single origin, sold in 250ml glass.",
            key_features=["18-hour steep", "single origin", "glass, returnable"],
            differentiators=["no dilution before bottling", "roast date on every bottle"],
        ),
        BrandProduct(
            name="Chuna Milk",
            category="Cold brew with milk",
            description="Slow Steep cut with full-cream milk, served over one large cube.",
            key_features=["one cube, not crushed ice", "no syrup"],
            differentiators=["unsweetened by default"],
        ),
    ],
    approved_claims=[
        "Steeped for 18 hours",
        "Single origin",
        "Roast date printed on every bottle",
        "Bottled in returnable glass",
    ],
    prohibited_claims=[
        "healthiest coffee",
        "boosts immunity",
        "aids weight loss",
        "strongest coffee in India",
        "medically proven",
    ],
    visual_dos=[
        "real condensation and real ice",
        "natural warm light with visible falloff",
        "local stone, plaster and terracotta as surfaces",
        "generous empty space around the product",
    ],
    visual_donts=[
        "palace, fort or heritage architecture as backdrop",
        "folk costume, camels or elephants",
        "royal pink and gold colour treatment",
        "latte art or coffee beans scattered as decoration",
        "oversaturated or HDR treatment",
    ],
    logo_rules=[
        "Wordmark only; never inside a badge or roundel.",
        "Minimum clear space of one 'M' height on all sides.",
    ],
    legal_line="Mitti & Bean is a fictional brand created for benchmark purposes.",
)

REFERENCES = [
    style_reference(
        reference_id="mitti-ref-1",
        style_families=[StyleFamily.EDITORIAL, StyleFamily.MINIMAL],
        composition=Composition.NEGATIVE_SPACE,
        lighting=Lighting.NATURAL,
        imagery_style=[ImageryStyle.PRODUCT_PHOTOGRAPHY, ImageryStyle.LIFESTYLE],
        palette=["#B07A52", "#EFE7DA", "#1C1A17"],
        brightness=0.55,
        saturation=0.25,
        contrast=0.5,
        temperature="warm",
        image_text_balance="image_led",
        subject_placement="lower",
        hierarchy="one dominant subject, everything else falls away",
        density=VisualDensity.SPARSE,
        mood=["calm", "unhurried", "grounded"],
        subject_treatment="One object held still, with the room falling away behind it.",
        takeaways=[
            "a single subject earns more attention than a styled arrangement",
            "warm light with a long falloff reads as afternoon, not as a studio",
            "empty space above the subject is where the type will go",
        ],
        summary="Quiet product-led editorial with a long warm falloff and a lot of air.",
        confidence=0.82,
    ),
    style_reference(
        reference_id="mitti-ref-2",
        style_families=[StyleFamily.PREMIUM],
        composition=Composition.PRODUCT_DOMINANT,
        lighting=Lighting.CINEMATIC,
        imagery_style=[ImageryStyle.PRODUCT_PHOTOGRAPHY],
        palette=["#1C1A17", "#B07A52", "#EFE7DA"],
        brightness=0.25,
        saturation=0.2,
        contrast=0.85,
        temperature="warm",
        image_text_balance="image_led",
        subject_placement="centre",
        hierarchy="product first, environment a distant second",
        density=VisualDensity.SPARSE,
        mood=["deliberate", "still"],
        subject_treatment="Hard directional key with deep shadow; the product edge-lit.",
        takeaways=[
            "high contrast reads as premium when the palette stays narrow",
            "shadow is a compositional element, not an absence of light",
        ],
        summary="Low-key premium product work built on one hard warm key light.",
        confidence=0.78,
    ),
    style_reference(
        reference_id="mitti-ref-3",
        style_families=[StyleFamily.LOCAL_CULTURAL, StyleFamily.MINIMAL],
        composition=Composition.ASYMMETRIC,
        lighting=Lighting.NATURAL,
        imagery_style=[ImageryStyle.LIFESTYLE, ImageryStyle.ARCHITECTURAL],
        palette=["#B07A52", "#EFE7DA", "#5C6B54"],
        brightness=0.6,
        saturation=0.3,
        contrast=0.45,
        temperature="warm",
        image_text_balance="balanced",
        subject_placement="left",
        hierarchy="texture supports the subject rather than competing",
        density=VisualDensity.BALANCED,
        mood=["local", "contemporary", "textural"],
        subject_treatment="Local material used as surface and light, never as ornament.",
        takeaways=[
            "regional material reads as place when it is a wall, not a motif",
            "texture carries locality more reliably than any landmark",
        ],
        summary="Place expressed as material and light rather than as landmark.",
        confidence=0.8,
        extra_not_transferable=[
            "recognisable buildings or monuments",
            "traditional pattern reproduced as a graphic device",
        ],
    ),
]


# --------------------------------------------------------------------------
# Campaign 1 — Apni Raftaar, Apna Pause
# --------------------------------------------------------------------------
_C1 = "bm-mitti-campaign-pause"

_C1_BRIEF = CampaignBrief(
    campaign_id=_C1,
    title="Apni Raftaar, Apna Pause",
    objective=(
        "Establish Mitti & Bean as the pause inside a fast day, and move "
        "weekday afternoon footfall in both Jaipur cafés."
    ),
    audience=(
        "Students and first-job professionals in Jaipur, 18-30, who buy coffee two or three times "
        "a week."
    ),
    audience_insight=(
        "They are not tired; they are over-stimulated. The thing they want "
        "from a café is fifteen minutes where nothing is asked of them."
    ),
    product="Slow Steep cold brew",
    key_message="A pause you choose is different from one you collapse into.",
    supporting_messages=[
        "Eighteen hours of steeping, for fifteen minutes of yours",
        "Unsweetened by default",
    ],
    cta="TAKE A SIP",
    region="Jaipur, Rajasthan",
    language="Hindi + English",
    channels=[Channel.INSTAGRAM_PORTRAIT, Channel.INSTAGRAM_STORY, Channel.WEB_BANNER],
    tone=["warm", "unhurried", "wry"],
    campaign_tone=["calm", "contemporary"],
    brand_requirements=[
        "Hinglish headline, not translated English",
        "no heritage architecture",
        "product visible and unstyled",
    ],
    constraints=["no wellness or health claims", "no price in the creative"],
    avoid_restrictions=["palace backdrops", "folk costume", "royal pink and gold"],
    required_elements=["visible condensation", "generous negative space for type"],
    success_criteria=["weekday 3-6pm footfall", "saves and shares over likes"],
    desired_emotional_response="Recognition — 'that is exactly my afternoon'.",
    timing_occasion="Hot season, March to June",
    rationale="The pause is the product; the coffee is how it is sold.",
)

_C1_DIRECTIONS = [
    CreativeDirection(
        campaign_id=_C1,
        ordinal=1,
        title="Thoda Thehro",
        big_idea="The city keeps moving. The glass does not.",
        strategic_rationale=(
            "Makes stillness visible by contrast rather than by stating it. "
            "The audience supplies the meaning, which is what makes it stick."
        ),
        emotional_angle="relief without sentimentality",
        audience_connection="Everyone in this audience has stood still while a street did not.",
        key_message="A pause you choose is different from one you collapse into.",
        headline="Thoda Thehro.",
        subhead="Cold brew for your everyday pause.",
        cta="TAKE A SIP",
        cta_direction="Low-key, lowercase-feeling even when set in caps.",
        visual_metaphor="stillness held inside motion",
        composition=(
            "Product sharp and centred low; the street behind it dissolved by a long exposure; "
            "upper third kept quiet."
        ),
        subject="A glass of cold brew on a raw plaster ledge, condensation running.",
        environment=(
            "A Jaipur street outside a small café at 5pm, scooters and students streaming past."
        ),
        lighting="Late sandstone-warm daylight raking from camera left; cool shadow behind.",
        palette=["#B07A52", "#1C1A17", "#EFE7DA"],
        style_families=[StyleFamily.EDITORIAL, StyleFamily.PREMIUM],
        color_direction="Warm pool of light on the product, everything behind desaturated.",
        brand_integration=(
            "Wordmark composited into the quiet upper third; no mark in the photograph."
        ),
        product_integration="The glass is the only sharp object in the frame.",
        regional_considerations=[
            "sandstone-warm light rather than sandstone buildings",
            "raw plaster and local stone as the only surfaces",
            "street life read through motion, not through costume",
        ],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["heritage architecture", "folk costume", "camels"],
            avoid_styles=["oversaturated", "HDR"],
            no_text_in_image=True,
        ),
        reference_characteristics_used=["long warm falloff", "single dominant subject"],
        reference_characteristics_avoided=["any visible lettering"],
        distinctness_note="The only direction built on motion blur.",
    ),
    CreativeDirection(
        campaign_id=_C1,
        ordinal=2,
        title="Aathra Ghanta",
        big_idea="Eighteen hours of patience, for fifteen minutes of yours.",
        strategic_rationale=(
            "Sells the pause through the making rather than the drinking. "
            "Gives the premium price a reason that is not the word 'premium'."
        ),
        emotional_angle="quiet respect for craft",
        audience_connection="An audience that values effort it can verify.",
        key_message="The slowness is in the making, not just the drinking.",
        headline="Aathra Ghanta.",
        subhead="Eighteen hours of steeping. Fifteen minutes of yours.",
        cta="TAKE A SIP",
        cta_direction="Set as a quiet footnote beneath the subhead.",
        visual_metaphor="time made visible as sediment and slow movement",
        composition=(
            "Overhead, tight on the steeping vessel; the frame is almost entirely dark liquid with "
            "one bright edge."
        ),
        subject="A steeping vessel mid-process, grounds suspended in dark water.",
        environment="A back-of-house counter at Mitti & Bean, unstyled, early morning.",
        lighting="Single overhead source, hard, with almost no fill.",
        palette=["#1C1A17", "#B07A52", "#EFE7DA"],
        style_families=[StyleFamily.PREMIUM, StyleFamily.MINIMAL],
        color_direction="Near-monochrome brown-black with one warm highlight.",
        brand_integration="Wordmark sits in the dark field with no competition.",
        product_integration="The product is shown before it is a product.",
        regional_considerations=[
            "local terracotta and steel vessels rather than lab glassware",
            "no regional signalling at all — process is the subject",
        ],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["scattered coffee beans", "latte art"],
            avoid_styles=["clip-art", "3D render"],
            no_text_in_image=True,
        ),
        reference_characteristics_used=["high contrast on a narrow palette"],
        reference_characteristics_avoided=["packaging graphics"],
        distinctness_note="The only direction with no street and no person.",
    ),
    CreativeDirection(
        campaign_id=_C1,
        ordinal=3,
        title="Dus Minute",
        big_idea="A pause looks like someone doing nothing, well.",
        strategic_rationale=(
            "Puts a person in the frame, which the other two refuse. Risk is "
            "cliché; the control is that the subject is disengaged, not posed."
        ),
        emotional_angle="permission",
        audience_connection="Shows the audience an image of themselves not performing.",
        key_message="Doing nothing is a thing you can be good at.",
        headline="Dus Minute.",
        subhead="Ten minutes that belong to you.",
        cta="TAKE A SIP",
        cta_direction="Placed beside the subhead on one line.",
        visual_metaphor="an unoccupied ten minutes",
        composition=(
            "Person seated at the right edge, looking out of frame; two thirds of the frame is "
            "wall."
        ),
        subject="A young woman at a café window with a glass, not using her phone.",
        environment="A contemporary Jaipur café interior: lime plaster, local stone, one plant.",
        lighting="Soft window daylight, high ratio, no fill on the shadow side.",
        palette=["#EFE7DA", "#5C6B54", "#1C1A17"],
        style_families=[StyleFamily.EDITORIAL, StyleFamily.LOCAL_CULTURAL],
        color_direction="Pale plaster ground with one green accent; skin tones true.",
        brand_integration="Wordmark on the empty wall, small.",
        product_integration="The glass is held, not displayed.",
        regional_considerations=[
            "contemporary Jaipur café interior, recognisable to a local by its materials",
            "clothing is ordinary city clothing, never costume",
        ],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["traditional dress", "posed smiling to camera"],
            avoid_styles=["stock-photo staging"],
            no_text_in_image=True,
        ),
        reference_characteristics_used=[
            "left-third subject placement",
            "local material as surface",
        ],
        reference_characteristics_avoided=["recognisable buildings"],
        distinctness_note="The only direction with a person in it.",
    ),
]

_C1_SPEC = CreativeSpecification(
    campaign_id=_C1,
    direction_id="bm-mitti-dir-1",
    version=1,
    concept="The city keeps moving. The glass does not.",
    visual_story=(
        "Rush hour outside a small Jaipur café. Students and scooters stream "
        "past a plaster ledge where one glass of cold brew sits completely "
        "still. The street is smeared into motion; the glass is not."
    ),
    emotional_angle="relief without sentimentality",
    headline="Thoda Thehro.",
    subhead="Cold brew for your everyday pause.",
    cta="TAKE A SIP",
    visual_metaphor="stillness held inside motion",
    composition=(
        "Product sharp and centred low; street dissolved behind; upper third quiet for type."
    ),
    focal_point="condensation running down the cold glass",
    subject="A tall glass of cold brew on a raw plaster ledge, heavy condensation.",
    environment="A Jaipur street outside a small café at 5pm, scooters and students moving past.",
    lighting=(
        "Late sandstone-warm daylight raking from camera left, cool shadow behind, strong falloff."
    ),
    camera="85mm, f/1.8, eye level, long exposure blurring the street",
    palette=["#B07A52", "#1C1A17", "#EFE7DA", "#5C6B54"],
    color_direction="Warm amber pool on the product against desaturated street greys.",
    style_families=[StyleFamily.PREMIUM, StyleFamily.EDITORIAL],
    mood=["calm", "urban", "unhurried"],
    product_integration="The glass is the only sharp object in the frame.",
    people_guidance="Passers-by only, blurred beyond recognition, ordinary city clothing.",
    brand_integration=(
        "No mark in the photograph; the wordmark is composited into the quiet upper third."
    ),
    regional_cues=["sandstone-warm light", "raw lime plaster", "Jaipur street life in motion"],
    negative_constraints=NegativeConstraints(
        forbidden_elements=[
            "heritage or palace architecture",
            "folk costume, camels or elephants",
            "royal pink and gold treatment",
            "scattered coffee beans",
        ],
        forbidden_text=["healthiest coffee", "boosts immunity"],
        avoid_styles=["oversaturated", "HDR", "stock-photo staging"],
        no_text_in_image=True,
    ),
    channel_copy={
        # A story is read in about a second, so the headline gets shorter.
        # Note it cannot *drop* the subhead: `copy_for` treats None as
        # inherit, and removing a line is a geometry decision the layout
        # makes, not a copy decision (see `copy_for`).
        Channel.INSTAGRAM_STORY: ChannelCopy(headline="Thehro."),
        # A banner is seen by someone mid-task and needs the product named.
        Channel.WEB_BANNER: ChannelCopy(
            headline="Thoda Thehro.",
            subhead="18-hour cold brew. Unsweetened by default.",
        ),
    },
)

CAMPAIGN_PAUSE = BenchmarkCampaign(
    slug="apni-raftaar-apna-pause",
    brief=_C1_BRIEF,
    directions=_C1_DIRECTIONS,
    specification=_C1_SPEC,
    selected_direction_ordinal=1,
    tests=[
        "localisation without landmark or costume",
        "Hinglish headline that is not a translation",
        "per-channel copy that shortens rather than resizes",
    ],
)


# --------------------------------------------------------------------------
# Campaign 2 — Raat Ki Padhai (exam season)
# --------------------------------------------------------------------------
_C2 = "bm-mitti-campaign-exams"

_C2_BRIEF = CampaignBrief(
    campaign_id=_C2,
    title="Raat Ki Padhai",
    objective="Own the November exam fortnight for late-night study among Jaipur students.",
    audience="University students in Jaipur, 18-24, during end-semester examinations.",
    audience_insight=(
        "They are already drinking something to stay awake. The choice is not "
        "whether to caffeinate but whether the thing tastes like a punishment."
    ),
    product="Slow Steep cold brew concentrate, 250ml",
    key_message="Stay up on something you actually want to drink.",
    supporting_messages=["Unsweetened by default", "Roast date on every bottle"],
    cta="TAKE A SIP",
    region="Jaipur, Rajasthan",
    language="Hindi + English",
    channels=[Channel.INSTAGRAM_STORY, Channel.INSTAGRAM_POST],
    tone=["wry", "plain-spoken"],
    campaign_tone=["nocturnal", "companionable"],
    brand_requirements=["no hustle-culture framing", "no 'all-nighter' glamour"],
    constraints=[
        "no claim about alertness, focus or performance",
        "no implication that skipping sleep is good",
    ],
    avoid_restrictions=["heritage imagery", "energy-drink visual language"],
    required_elements=["night interior", "space for type at the top"],
    success_criteria=["bottle sales in the exam fortnight", "story replies"],
    desired_emotional_response="Being kept company rather than being cheered on.",
    timing_occasion="End-semester examinations, November",
    rationale="A seasonal campaign that must not become a stimulant advertisement.",
)

_C2_DIRECTIONS = [
    CreativeDirection(
        campaign_id=_C2,
        ordinal=1,
        title="Teen Baje",
        big_idea="Three in the morning, and the bottle is still there.",
        strategic_rationale=(
            "Companionship rather than performance — the one framing that stays inside the claim "
            "constraints."
        ),
        emotional_angle="quiet solidarity",
        audience_connection="Everyone studying at 3am knows the specific silence of it.",
        key_message="Stay up on something you actually want to drink.",
        headline="Teen Baje.",
        subhead="Still here. Still cold.",
        cta="TAKE A SIP",
        cta_direction="Small, bottom-left, unemphatic.",
        visual_metaphor="a companion object in a long night",
        composition=(
            "Desk corner at night, bottle at the right edge, the rest of the frame dark and empty."
        ),
        subject="A 250ml bottle of cold brew beside an open notebook.",
        environment="A student's desk in a Jaipur hostel room, late night, one lamp.",
        lighting="Single warm desk lamp, deep falloff to black.",
        palette=["#1C1A17", "#B07A52", "#EFE7DA"],
        style_families=[StyleFamily.MINIMAL, StyleFamily.EDITORIAL],
        color_direction="Almost monochrome dark with one warm pool.",
        brand_integration="Wordmark in the dark field above the desk.",
        product_integration="The bottle is present, not featured.",
        regional_considerations=["an ordinary Indian hostel desk, not a styled study set"],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["energy-drink styling", "clocks as literal props"],
            avoid_styles=["oversaturated"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction set at night indoors.",
    ),
    CreativeDirection(
        campaign_id=_C2,
        ordinal=2,
        title="Do Din Baaki",
        big_idea="The fridge as the honest record of exam week.",
        strategic_rationale=(
            "Humour without hustle language; the product appears as evidence rather than as hero."
        ),
        emotional_angle="wry recognition",
        audience_connection="A shared hostel fridge is a universal object in this audience.",
        key_message="Stay up on something you actually want to drink.",
        headline="Do Din Baaki.",
        subhead="Stocked accordingly.",
        cta="TAKE A SIP",
        cta_direction="Right-aligned under the subhead.",
        visual_metaphor="preparation shown as inventory",
        composition="Straight-on fridge shelf, bottles lined up, cold interior light only.",
        subject="A row of cold brew bottles on a shared fridge shelf.",
        environment="A shared hostel fridge, unstyled, other people's things visible.",
        lighting="Cold interior fridge light, high key against a dark room.",
        palette=["#EFE7DA", "#5C6B54", "#1C1A17"],
        style_families=[StyleFamily.EDITORIAL, StyleFamily.BOLD],
        color_direction="Cool white interior against warm room dark.",
        brand_integration="Labels are present but not legible; the wordmark is composited.",
        product_integration="Repetition carries the product, not scale.",
        regional_considerations=["a genuinely shared Indian hostel fridge, mess included"],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["pristine styled fridge", "product hero lighting"],
            avoid_styles=["stock-photo staging"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction built on repetition and cold light.",
    ),
    CreativeDirection(
        campaign_id=_C2,
        ordinal=3,
        title="Subah Tak",
        big_idea="The window gets light before you finish.",
        strategic_rationale=(
            "Widens from desk to window, trading intimacy for scale; the most atmospheric of the "
            "three."
        ),
        emotional_angle="endurance, gently",
        audience_connection="The specific blue of a window at 5am after a night awake.",
        key_message="Stay up on something you actually want to drink.",
        headline="Subah Tak.",
        subhead="Cold brew for the long end of the night.",
        cta="TAKE A SIP",
        cta_direction="Centred beneath the subhead.",
        visual_metaphor="night becoming morning without a break",
        composition=(
            "Window fills the upper two thirds, going blue; desk and bottle silhouetted low."
        ),
        subject="A bottle silhouetted against a window turning from black to blue.",
        environment="A Jaipur rooftop room at first light, city roofline soft beyond.",
        lighting="Blue-hour ambience through glass, one warm lamp behind camera.",
        palette=["#2A3340", "#B07A52", "#EFE7DA"],
        style_families=[StyleFamily.CINEMATIC, StyleFamily.PREMIUM],
        color_direction="Cool blue field with a single warm interior accent.",
        brand_integration="Wordmark low, against the dark desk.",
        product_integration="Silhouette only; the shape carries it.",
        regional_considerations=["a Jaipur roofline in soft focus — skyline, never monument"],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["identifiable monuments", "sunrise cliché over a fort"],
            avoid_styles=["HDR"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction using blue hour and a silhouette.",
    ),
]

_C2_SPEC = CreativeSpecification(
    campaign_id=_C2,
    direction_id="bm-mitti-dir-4",
    version=1,
    concept="Three in the morning, and the bottle is still there.",
    visual_story=(
        "A hostel desk at 3am. One lamp, an open notebook, and a bottle of "
        "cold brew that has been there for hours. Nothing is being achieved "
        "in the frame; something is simply being kept company."
    ),
    emotional_angle="quiet solidarity",
    headline="Teen Baje.",
    subhead="Still here. Still cold.",
    cta="TAKE A SIP",
    visual_metaphor="a companion object in a long night",
    composition=(
        "Desk corner at night; bottle right of centre; upper field dark and empty for type."
    ),
    focal_point="the lamp-lit edge of the bottle",
    subject="A 250ml bottle of cold brew beside an open notebook.",
    environment="A student's desk in a Jaipur hostel room, late night, one lamp.",
    lighting="Single warm desk lamp with deep falloff to black.",
    camera="50mm, f/2.0, slightly above desk height",
    palette=["#1C1A17", "#B07A52", "#EFE7DA"],
    color_direction="Near-monochrome dark with one warm pool of lamp light.",
    style_families=[StyleFamily.MINIMAL, StyleFamily.EDITORIAL],
    mood=["nocturnal", "quiet", "companionable"],
    product_integration="The bottle is present rather than featured; label not legible.",
    people_guidance="No people in frame.",
    brand_integration="Wordmark composited into the dark field above the desk.",
    regional_cues=["an ordinary Indian hostel desk", "Jaipur night quiet"],
    negative_constraints=NegativeConstraints(
        forbidden_elements=["energy-drink styling", "literal clocks", "heritage imagery"],
        forbidden_text=["improves focus", "stay alert", "boosts immunity"],
        avoid_styles=["oversaturated", "HDR"],
        no_text_in_image=True,
    ),
    # No per-channel overrides: "Teen Baje." is already two words and every
    # channel inherits it. An override that restates the default is noise.
    channel_copy={},
)

CAMPAIGN_EXAMS = BenchmarkCampaign(
    slug="raat-ki-padhai",
    brief=_C2_BRIEF,
    directions=_C2_DIRECTIONS,
    specification=_C2_SPEC,
    selected_direction_ordinal=1,
    tests=[
        "seasonal occasion targeting without a claim breach",
        "same brand, narrower audience, different tone",
        "compliance pressure on a startup's short claims list",
    ],
)


# --------------------------------------------------------------------------
# Campaign 3 — Wholesale, English-led, LinkedIn
# --------------------------------------------------------------------------
_C3 = "bm-mitti-campaign-wholesale"

_C3_BRIEF = CampaignBrief(
    campaign_id=_C3,
    title="Steeped Here",
    objective=(
        "Win cold brew supply contracts with independent cafés and boutique hotels in Jaipur and "
        "Udaipur."
    ),
    audience="Café owners, F&B managers and boutique hotel buyers in Rajasthan.",
    audience_insight=(
        "A buyer's real fear is inconsistency between deliveries. Craft "
        "language actively works against them; verifiable process does not."
    ),
    product="Slow Steep cold brew concentrate, wholesale 5L",
    key_message="The same eighteen hours, every delivery.",
    supporting_messages=["Roast date on every batch", "Returnable glass, collected weekly"],
    cta="REQUEST A SAMPLE",
    region="Rajasthan",
    language="English",
    channels=[Channel.LINKEDIN, Channel.WEB_BANNER],
    tone=["plain-spoken", "precise"],
    campaign_tone=["professional", "unshowy"],
    brand_requirements=["English only — this audience reads trade in English", "no Hinglish"],
    constraints=["no consumer-facing romance", "no unverifiable consistency claims"],
    avoid_restrictions=["lifestyle imagery", "heritage imagery"],
    required_elements=["process or supply visible", "space for a headline at left"],
    success_criteria=["sample requests", "contracts signed"],
    desired_emotional_response="Confidence that the next delivery is the same as this one.",
    timing_occasion="Pre-tourist-season buying, August to September",
    rationale="Same brand, entirely different audience, language and register.",
)

_C3_DIRECTIONS = [
    CreativeDirection(
        campaign_id=_C3,
        ordinal=1,
        title="Same Eighteen",
        big_idea="Consistency, shown as a repeated measurement.",
        strategic_rationale="Answers the buyer's actual anxiety rather than selling taste.",
        emotional_angle="reassurance through evidence",
        audience_connection="Buyers trust things they can check.",
        key_message="The same eighteen hours, every delivery.",
        headline="Same eighteen hours.",
        subhead="Every batch, every delivery.",
        cta="REQUEST A SAMPLE",
        cta_direction="Button-like, left-aligned under the subhead.",
        visual_metaphor="repetition as a promise",
        composition=(
            "Wide, low-contrast; identical vessels in a row receding to the right; left third "
            "empty for type."
        ),
        subject="A row of identical steeping vessels, all at the same level.",
        environment="A small working production room, clean but not clinical.",
        lighting="Even diffuse daylight, minimal shadow.",
        palette=["#EFE7DA", "#1C1A17", "#5C6B54"],
        style_families=[StyleFamily.TECHNICAL, StyleFamily.MINIMAL],
        color_direction="Neutral and even; no dramatic grade.",
        brand_integration="Wordmark in the empty left third.",
        product_integration="Product as process, not as a glass to drink.",
        regional_considerations=["a real small Indian production space, not a European roastery"],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["lifestyle staging", "hands holding cups"],
            avoid_styles=["cinematic grading"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction shot flat and even, with no mood.",
    ),
    CreativeDirection(
        campaign_id=_C3,
        ordinal=2,
        title="Dated, Not Described",
        big_idea="The roast date does the talking.",
        strategic_rationale="Turns the one verifiable fact into the entire proposition.",
        emotional_angle="plain confidence",
        audience_connection="A date is a fact a buyer can audit.",
        key_message="The same eighteen hours, every delivery.",
        headline="Dated, not described.",
        subhead="Roast date on every batch we send you.",
        cta="REQUEST A SAMPLE",
        cta_direction="Inline, right of the subhead.",
        visual_metaphor="evidence over adjectives",
        composition=(
            "Macro, tight on a bottle shoulder; extreme shallow depth; wide clean area above."
        ),
        subject="The shoulder of a wholesale bottle where the batch date is stamped.",
        environment="A dispatch bench, out of focus behind.",
        lighting="Hard raking light to reveal surface and stamp relief.",
        palette=["#1C1A17", "#EFE7DA", "#B07A52"],
        style_families=[StyleFamily.TECHNICAL, StyleFamily.PREMIUM],
        color_direction="Neutral with one warm glass highlight.",
        brand_integration="Wordmark above, small and quiet.",
        product_integration="A detail of the product stands for all of it.",
        regional_considerations=["no regional signalling; this audience buys on process"],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["legible printed text in the photograph"],
            avoid_styles=["HDR"],
            no_text_in_image=True,
        ),
        distinctness_note="The only macro direction.",
    ),
    CreativeDirection(
        campaign_id=_C3,
        ordinal=3,
        title="Collected Weekly",
        big_idea="The glass comes back.",
        strategic_rationale=(
            "Leads on the returnable-glass logistics, which is both a cost story and a credible "
            "sustainability one."
        ),
        emotional_angle="practical alignment",
        audience_connection="Waste and storage are daily problems for a café.",
        key_message="The same eighteen hours, every delivery.",
        headline="The glass comes back.",
        subhead="Returnable, collected weekly, across Jaipur and Udaipur.",
        cta="REQUEST A SAMPLE",
        cta_direction="Beneath the subhead, left-aligned.",
        visual_metaphor="a loop rather than a line",
        composition=(
            "Crates of returned empties stacked at the right; morning street light; left half open."
        ),
        subject="Stacked crates of returned glass bottles outside a café at opening time.",
        environment="A Jaipur side street at 8am, shutters half up.",
        lighting="Early flat daylight, long soft shadows.",
        palette=["#5C6B54", "#EFE7DA", "#1C1A17"],
        style_families=[StyleFamily.EDITORIAL, StyleFamily.LOCAL_CULTURAL],
        color_direction="Muted green and bone; nothing saturated.",
        brand_integration="Wordmark in the open left half.",
        product_integration="Empties, not full bottles — the point is the return.",
        regional_considerations=[
            "an ordinary Jaipur commercial street at opening",
            "no heritage frontage in shot",
        ],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["heritage frontage", "tourists in frame"],
            avoid_styles=["oversaturated"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction about logistics rather than product.",
    ),
]

_C3_SPEC = CreativeSpecification(
    campaign_id=_C3,
    direction_id="bm-mitti-dir-7",
    version=1,
    concept="Consistency, shown as a repeated measurement.",
    visual_story=(
        "A working production room with identical steeping vessels in a row, "
        "all filled to the same level. Nothing is styled. The picture makes "
        "one argument: the next delivery will be the same as this one."
    ),
    emotional_angle="reassurance through evidence",
    headline="Same eighteen hours.",
    subhead="Every batch, every delivery.",
    cta="REQUEST A SAMPLE",
    visual_metaphor="repetition as a promise",
    composition="Wide and low-contrast; vessels receding right; left third kept empty for type.",
    focal_point="the identical fill level across every vessel",
    subject="A row of identical steeping vessels at the same level.",
    environment="A small working production room in Jaipur, clean but not clinical.",
    lighting="Even diffuse daylight with minimal shadow.",
    camera="35mm, f/5.6, chest height, everything sharp",
    palette=["#EFE7DA", "#1C1A17", "#5C6B54"],
    color_direction="Neutral and even, deliberately without a cinematic grade.",
    style_families=[StyleFamily.TECHNICAL, StyleFamily.MINIMAL],
    mood=["precise", "unshowy", "credible"],
    product_integration="Product shown as process, never as a glass to drink.",
    people_guidance="No people in frame.",
    brand_integration="Wordmark composited into the empty left third.",
    regional_cues=["a real small Indian production space"],
    negative_constraints=NegativeConstraints(
        forbidden_elements=["lifestyle staging", "hands holding cups", "heritage imagery"],
        forbidden_text=["strongest coffee in India", "healthiest coffee"],
        avoid_styles=["cinematic grading", "oversaturated"],
        no_text_in_image=True,
    ),
    channel_copy={
        Channel.WEB_BANNER: ChannelCopy(
            headline="Same eighteen hours.",
            subhead="Wholesale cold brew across Rajasthan.",
            cta="REQUEST A SAMPLE",
        ),
    },
)

CAMPAIGN_WHOLESALE = BenchmarkCampaign(
    slug="steeped-here",
    brief=_C3_BRIEF,
    directions=_C3_DIRECTIONS,
    specification=_C3_SPEC,
    selected_direction_ordinal=1,
    tests=[
        "same brand, B2B audience, English-only",
        "register shift without brand drift",
        "localisation deliberately dialled down where it does not help",
    ],
)


COMPANY = BenchmarkCompany(
    slug=SLUG,
    display_name="Mitti & Bean",
    size=CompanySize.STARTUP,
    industry="Speciality coffee — cold brew",
    market=MARKET,
    languages=LANGUAGES,
    brand=BRAND,
    references=REFERENCES,
    campaigns=[CAMPAIGN_PAUSE, CAMPAIGN_EXAMS, CAMPAIGN_WHOLESALE],
    selection_rationale=(
        "The startup case, and the hardest localisation test of the three: "
        "Jaipur's visual shorthand is both the most recognisable in India and "
        "the most wrong for this brand. A system that localises by reaching "
        "for the nearest regional signifier fails here visibly."
    ),
)
