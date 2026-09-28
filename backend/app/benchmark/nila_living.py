"""Nila Living — Kochi, Kerala. Mid-size home and lifestyle. **Fictional.**

The middle of the benchmark, and the company that carries its central
argument. What this one tests:

* **Localisation as atmosphere, not as ornament.** Kerala's usable cues are
  climate and material — monsoon light, humidity, lime plaster, unfinished
  teak — rather than motif. A campaign localised here should be recognisable
  to a Malayali before a single word is read.
* **Malayalam that leads rather than follows.** "Veettil Oru Feeling" is the
  campaign, and the English line is the adaptation. This is the company the
  naive-versus-hyperlocal comparison is built on, because it is the case where
  translating an English campaign into Malayalam produces something that is
  grammatically fine and completely wrong.
* **Real but proportionate governance.** A brand team exists, so the claims
  list is longer than the startup's and includes material and sourcing claims
  that carry legal weight — but there is no national regulatory apparatus.
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

SLUG = "nila-living"
BRAND_ID = "bm-brand-nila"
ORG_PLACEHOLDER = "bm-org-nila"

MARKET = LocalMarketContext(
    city="Kochi",
    state="Kerala",
    localisation_thesis=(
        "Kerala's defining variable is water — six months of it. A home brand "
        "here is judged on how it behaves in humidity, and the visual "
        "language that reads as local is weather and material, not motif."
    ),
    credible_cues=[
        "monsoon light: bright overcast with no hard shadow",
        "rain on a courtyard or a half-open window",
        "unfinished teak, cane, lime plaster, terracotta floor",
        "deep verandah shade against a bright exterior",
        "dense green pressing in at the edges of a frame",
        "contemporary Kochi apartment interiors, not ancestral houses",
    ],
    tokenising_cues=[
        "Kathakali faces or costume",
        "snake boats and backwater tourism framing",
        "coconut palms arranged as a decorative border",
        "houseboats",
        "a nostalgic tharavad set dressed as 'authentic'",
    ],
    seasonal_notes=[
        "the southwest monsoon from June to August dominates the year",
        "Onam in August or September is the single largest purchase occasion",
        "humidity is a year-round product concern, not a seasonal one",
    ],
)

LANGUAGES = [
    LanguagePreference(
        language="Malayalam",
        usage=(
            "Leads. The campaign is conceived in Malayalam and the English "
            "line is the adaptation, not the other way round."
        ),
        script="Malayalam script throughout; no Roman transliteration in "
        "headlines, which this audience reads as talking down to them.",
        never_translate=["Nila Living", "Kaatu", "Mazha"],
    ),
    LanguagePreference(
        language="English",
        usage="Product specification, care instructions, trade communication "
        "and anything aimed at architects or specifiers.",
        script="Latin.",
        never_translate=["Nila Living", "Kaatu", "Mazha"],
    ),
]

BRAND = BrandProfile(
    id=BRAND_ID,
    organization_id=ORG_PLACEHOLDER,
    name="Nila Living",
    industry="Home and lifestyle — furniture and soft furnishing",
    description=(
        "FICTIONAL. A Kochi home brand of about ninety people, making "
        "furniture and textiles designed for humid coastal climates. Two "
        "retail stores, a workshop in Aluva, and a trade channel selling to "
        "architects and interior designers."
    ),
    positioning=(
        "Home things built for the way Kerala actually lives — humid, open, "
        "full of people — rather than imported designs that fail in monsoon."
    ),
    mission="Make objects that get better in the climate they are used in.",
    values=["material honesty", "climate fitness", "quiet craft", "longevity"],
    audience_description=(
        "25-45 urban professionals and young families in Kochi, Thrissur and "
        "Kozhikode, plus architects and interior designers specifying for them."
    ),
    voice=BrandVoice(
        tone_attributes=["calm", "warm", "precise", "unhurried"],
        person="second",
        writing_rules=[
            "Malayalam first for anything emotional; English for anything technical.",
            "Describe how a thing behaves over years, not how it looks on day one.",
            "Family is present but never sentimentalised.",
            "Name the material. Always.",
        ],
        avoid=[
            "nostalgia for a vanished Kerala",
            "'ethnic', 'exotic', 'oriental'",
            "luxury-lifestyle vocabulary",
            "translated English idiom in Malayalam copy",
        ],
    ),
    colors=[
        BrandColor(name="Mazha", hex="#4A5D5A", role="primary"),
        BrandColor(name="Chuvar", hex="#E6DFD2", role="ground"),
        BrandColor(name="Teak", hex="#8A5A3B", role="accent"),
        BrandColor(name="Iruttu", hex="#221F1C", role="ink"),
    ],
    typography=BrandTypography(
        heading_font="Transitional serif",
        body_font="Humanist sans",
        fallback_stack=["Georgia", "serif"],
        notes=(
            "Malayalam has tall ascenders and deep descenders; line height "
            "must be set for Malayalam first and Latin allowed to sit inside "
            "it, never the reverse."
        ),
    ),
    preferred_styles=[StyleFamily.PREMIUM, StyleFamily.EDITORIAL, StyleFamily.LOCAL_CULTURAL],
    products=[
        BrandProduct(
            name="Kaatu",
            category="Seating",
            description="A cane-and-teak lounge chair designed for airflow in humid rooms.",
            key_features=["hand-woven cane", "solid teak frame", "no foam"],
            differentiators=["designed for airflow rather than padding"],
        ),
        BrandProduct(
            name="Mazha",
            category="Soft furnishing",
            description="Undyed cotton throws and covers that dry fast in monsoon humidity.",
            key_features=["undyed cotton", "fast-drying weave"],
            differentiators=["tested through a full monsoon before release"],
        ),
    ],
    approved_claims=[
        "Solid teak frame",
        "Hand-woven cane",
        "Undyed cotton",
        "Tested through a full monsoon season",
        "Ten-year frame warranty",
    ],
    prohibited_claims=[
        "waterproof",
        "mould-proof",
        "lasts forever",
        "100% sustainable",
        "certified organic",
    ],
    visual_dos=[
        "bright overcast monsoon light with no hard shadow",
        "visible material grain and weave",
        "rooms that look lived in, with things out of place",
        "deep green visible through an opening",
    ],
    visual_donts=[
        "Kathakali imagery, snake boats or houseboats",
        "coconut palms as a decorative border",
        "empty showroom staging with nothing human in it",
        "warm golden-hour grading — the light here is cool and diffuse",
        "nostalgic period set dressing",
    ],
    logo_rules=[
        "Wordmark in ink or ground colour only; never on the teak accent.",
        "Never placed over a person or a product's primary surface.",
    ],
    legal_line="Nila Living is a fictional brand created for benchmark purposes.",
)

REFERENCES = [
    style_reference(
        reference_id="nila-ref-1",
        style_families=[StyleFamily.EDITORIAL, StyleFamily.PREMIUM],
        composition=Composition.ASYMMETRIC,
        lighting=Lighting.NATURAL,
        imagery_style=[ImageryStyle.LIFESTYLE, ImageryStyle.ARCHITECTURAL],
        palette=["#E6DFD2", "#4A5D5A", "#8A5A3B"],
        brightness=0.7,
        saturation=0.25,
        contrast=0.35,
        temperature="cool",
        image_text_balance="image_led",
        subject_placement="right",
        hierarchy="room first, object second, person third",
        density=VisualDensity.BALANCED,
        mood=["calm", "humid", "domestic"],
        subject_treatment=(
            "Interior read as a whole; the product sits inside it rather than on top of it."
        ),
        takeaways=[
            "flat overcast light with no hard shadow reads as monsoon",
            "a low-contrast frame feels humid where a contrasty one feels arid",
            "green seen through an opening does more locating work than any motif",
        ],
        summary="Low-contrast domestic interior under bright overcast light.",
        confidence=0.84,
        extra_not_transferable=["the specific apartment and its fittings"],
    ),
    style_reference(
        reference_id="nila-ref-2",
        style_families=[StyleFamily.MINIMAL, StyleFamily.TECHNICAL],
        composition=Composition.PRODUCT_DOMINANT,
        lighting=Lighting.NATURAL,
        imagery_style=[ImageryStyle.PRODUCT_PHOTOGRAPHY],
        palette=["#8A5A3B", "#E6DFD2", "#221F1C"],
        brightness=0.6,
        saturation=0.3,
        contrast=0.55,
        temperature="neutral",
        image_text_balance="image_led",
        subject_placement="centre",
        hierarchy="material grain is the subject",
        density=VisualDensity.SPARSE,
        mood=["tactile", "precise"],
        subject_treatment="Raking side light across a surface to make weave and grain readable.",
        takeaways=[
            "material credibility comes from raking light, not from close focus alone",
            "a narrow palette lets texture carry the whole frame",
        ],
        summary="Material study where light exists to reveal surface.",
        confidence=0.8,
    ),
    style_reference(
        reference_id="nila-ref-3",
        style_families=[StyleFamily.LOCAL_CULTURAL, StyleFamily.EDITORIAL],
        composition=Composition.NEGATIVE_SPACE,
        lighting=Lighting.NATURAL,
        imagery_style=[ImageryStyle.LIFESTYLE, ImageryStyle.HUMAN_CENTRIC],
        palette=["#4A5D5A", "#E6DFD2", "#221F1C"],
        brightness=0.5,
        saturation=0.2,
        contrast=0.4,
        temperature="cool",
        image_text_balance="balanced",
        subject_placement="lower",
        hierarchy="weather first, people inside it",
        density=VisualDensity.SPARSE,
        mood=["quiet", "enclosed", "familial"],
        subject_treatment="People are small in the frame and unaware of the camera.",
        takeaways=[
            "family reads more honestly when nobody is looking at the lens",
            "rain at the edge of a frame localises without any motif at all",
        ],
        summary="Domestic life seen at a respectful distance during rain.",
        confidence=0.79,
        extra_not_transferable=["identifiable faces used as a likeness"],
    ),
]


# --------------------------------------------------------------------------
# Campaign 1 — Veettil Oru Feeling
# --------------------------------------------------------------------------
_C1 = "bm-nila-campaign-feeling"

_C1_BRIEF = CampaignBrief(
    campaign_id=_C1,
    title="Veettil Oru Feeling",
    objective=(
        "Reposition Nila Living from furniture retailer to the brand that understands how a Kerala "
        "home feels."
    ),
    audience=(
        "Urban professionals and young families in Kochi, Thrissur and Kozhikode, 25-45, "
        "furnishing a first or second home."
    ),
    audience_insight=(
        "They do not talk about furniture. They talk about whether the house "
        "feels right when it rains and there are eleven people in it."
    ),
    product="Kaatu seating and Mazha soft furnishing",
    key_message="A home is the feeling made inside it, not the things bought for it.",
    supporting_messages=[
        "Built for humidity, not in spite of it",
        "Tested through a full monsoon",
    ],
    cta="VISIT A STORE",
    region="Kerala",
    language="Malayalam + English",
    channels=[Channel.INSTAGRAM_PORTRAIT, Channel.INSTAGRAM_STORY, Channel.WEB_BANNER],
    tone=["calm", "warm", "precise"],
    campaign_tone=["domestic", "unhurried"],
    brand_requirements=[
        "Malayalam headline conceived in Malayalam",
        "material named somewhere in the copy",
        "monsoon light, not golden hour",
    ],
    constraints=["no waterproof or mould-proof claims", "no nostalgia framing"],
    avoid_restrictions=["Kathakali", "houseboats", "coconut palm borders"],
    required_elements=["rain or wet light present", "a room that looks used"],
    success_criteria=["store visits", "brand association with 'feels right'"],
    desired_emotional_response="Recognition of one's own house, not aspiration for another.",
    timing_occasion="Southwest monsoon, June to August",
    rationale="The feeling is the product; the furniture is the evidence.",
)

_C1_DIRECTIONS = [
    CreativeDirection(
        campaign_id=_C1,
        ordinal=1,
        title="Mazha Peyyumbol",
        big_idea="When it rains, the house closes around you.",
        strategic_rationale=(
            "Uses the single most shared Kerala experience as the emotional vehicle, with zero "
            "motif cost."
        ),
        emotional_angle="enclosure and safety",
        audience_connection=(
            "Everyone in Kerala knows the sound of the first heavy rain against a window."
        ),
        key_message="A home is the feeling made inside it.",
        headline="മഴ പെയ്യുമ്പോൾ.",
        subhead="വീട് നിങ്ങളെ ചേർത്തുപിടിക്കുന്നു.",
        cta="VISIT A STORE",
        cta_direction="English call to action beneath Malayalam copy, smaller.",
        visual_metaphor="a house holding its people during rain",
        composition=(
            "Interior looking out through a half-open window; the chair in the near dark; rain "
            "bright beyond."
        ),
        subject="A Kaatu cane chair beside a window, a throw over the arm.",
        environment="A contemporary Kochi apartment living room during heavy rain.",
        lighting="Bright flat overcast light from outside; interior falling into shadow.",
        palette=["#4A5D5A", "#E6DFD2", "#8A5A3B"],
        style_families=[StyleFamily.EDITORIAL, StyleFamily.LOCAL_CULTURAL],
        color_direction="Cool grey-green outside against warm teak inside.",
        brand_integration="Wordmark in the dark interior field.",
        product_integration="The chair is where the eye lands, but the rain is the subject.",
        regional_considerations=[
            "contemporary apartment, never an ancestral house",
            "monsoon light rendered cool and flat, never golden",
            "green pressing at the window edge",
        ],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["Kathakali", "houseboats", "coconut palm borders"],
            avoid_styles=["golden-hour grading", "nostalgic set dressing"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction where weather is the subject.",
    ),
    CreativeDirection(
        campaign_id=_C1,
        ordinal=2,
        title="Pathinonnu Per",
        big_idea="A Kerala living room is designed by whoever turns up.",
        strategic_rationale=(
            "Sells airflow and durability through the reality of a full house rather than through "
            "specification."
        ),
        emotional_angle="affectionate chaos",
        audience_connection="The room that has to absorb eleven relatives without warning.",
        key_message="Built for the way the house is actually used.",
        headline="പതിനൊന്നു പേർ.",
        subhead="മുറി അത് താങ്ങും.",
        cta="VISIT A STORE",
        cta_direction="Right-aligned under the Malayalam subhead.",
        visual_metaphor="a room absorbing more people than it was drawn for",
        composition=(
            "Wide, slightly high; people spread across the room mid-conversation; furniture read "
            "through use."
        ),
        subject="An extended family filling a living room, nobody looking at camera.",
        environment="A Kochi apartment mid-afternoon with the balcony door open.",
        lighting="Even diffuse daylight, no key, humid haze.",
        palette=["#E6DFD2", "#4A5D5A", "#221F1C"],
        style_families=[StyleFamily.LOCAL_CULTURAL, StyleFamily.EDITORIAL],
        color_direction="Bright, low contrast, true skin tones.",
        brand_integration="Wordmark in the ceiling field above the scene.",
        product_integration="Furniture is in use and partly obscured — that is the point.",
        regional_considerations=[
            "ordinary contemporary Malayali family clothing",
            "an apartment, with a balcony and green beyond",
        ],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["posed family portrait", "traditional costume as styling"],
            avoid_styles=["stock-photo staging"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction with a full room of people.",
    ),
    CreativeDirection(
        campaign_id=_C1,
        ordinal=3,
        title="Naalu Varsham",
        big_idea="Four years in, the cane has changed colour. That is the feature.",
        strategic_rationale=(
            "Turns ageing into the proposition — the strongest differentiator against imported "
            "furniture that fails locally."
        ),
        emotional_angle="earned familiarity",
        audience_connection="Everyone has one piece of furniture that got better.",
        key_message="Things that get better in the climate they are used in.",
        headline="നാലു വർഷം.",
        subhead="കനം കൂടി, നിറം മാറി.",
        cta="VISIT A STORE",
        cta_direction="Beneath the subhead, quiet.",
        visual_metaphor="patina as proof",
        composition=(
            "Macro on the cane weave where hands have worn it; the room out of focus behind."
        ),
        subject="A worn arm of a cane chair, colour deepened by years of use.",
        environment="A lived-in Kochi home, out of focus.",
        lighting="Raking side light across the weave to reveal texture.",
        palette=["#8A5A3B", "#E6DFD2", "#221F1C"],
        style_families=[StyleFamily.MINIMAL, StyleFamily.PREMIUM],
        color_direction="Warm teak-dominant with a neutral ground.",
        brand_integration="Wordmark in the defocused field.",
        product_integration="A detail of the product stands for the whole argument.",
        regional_considerations=["no regional signalling; material and wear carry it"],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["new showroom-perfect product"],
            avoid_styles=["HDR", "clinical product lighting"],
            no_text_in_image=True,
        ),
        distinctness_note="The only macro direction, and the only one about time.",
    ),
]

_C1_SPEC = CreativeSpecification(
    campaign_id=_C1,
    direction_id="bm-nila-dir-1",
    version=1,
    concept="When it rains, the house closes around you.",
    visual_story=(
        "Heavy monsoon rain outside a contemporary Kochi apartment. Inside, a "
        "cane chair with a throw over its arm sits in the near dark while the "
        "window is bright with falling water. Nothing is happening, and that "
        "is the feeling the campaign is selling."
    ),
    emotional_angle="enclosure and safety",
    headline="മഴ പെയ്യുമ്പോൾ.",
    subhead="വീട് നിങ്ങളെ ചേർത്തുപിടിക്കുന്നു.",
    cta="VISIT A STORE",
    visual_metaphor="a house holding its people during rain",
    composition=(
        "Interior looking out through a half-open window; chair in near dark; rain bright beyond; "
        "upper left quiet for type."
    ),
    focal_point="the lit edge of the window against the dark interior",
    subject="A Kaatu cane chair beside a window with a cotton throw over the arm.",
    environment="A contemporary Kochi apartment living room during heavy monsoon rain.",
    lighting=(
        "Bright flat overcast light from outside; the interior falling into shadow; no hard shadow "
        "anywhere."
    ),
    camera="35mm, f/2.8, seated eye height",
    palette=["#4A5D5A", "#E6DFD2", "#8A5A3B", "#221F1C"],
    color_direction="Cool grey-green exterior against warm teak interior; low contrast throughout.",
    style_families=[StyleFamily.EDITORIAL, StyleFamily.LOCAL_CULTURAL],
    mood=["calm", "enclosed", "humid"],
    product_integration="The chair is where the eye lands; the rain is what the picture is about.",
    people_guidance="No people, or one person seen only as a shape at the frame edge.",
    brand_integration=(
        "No mark in the photograph; wordmark composited into the dark interior field."
    ),
    regional_cues=[
        "monsoon light: bright overcast, no hard shadow",
        "contemporary Kochi apartment, not an ancestral house",
        "dense green pressing at the window edge",
    ],
    negative_constraints=NegativeConstraints(
        forbidden_elements=[
            "Kathakali imagery or costume",
            "houseboats or snake boats",
            "coconut palms as decorative border",
            "nostalgic period set dressing",
        ],
        forbidden_text=["waterproof", "mould-proof", "lasts forever"],
        avoid_styles=["golden-hour grading", "HDR", "empty showroom staging"],
        no_text_in_image=True,
    ),
    channel_copy={
        # Trade-adjacent surface: English leads and the material is named,
        # because a banner reaches specifiers as well as homeowners.
        Channel.WEB_BANNER: ChannelCopy(
            headline="Built for the monsoon.",
            subhead="Cane and solid teak, tested through a full season.",
        ),
    },
)

CAMPAIGN_FEELING = BenchmarkCampaign(
    slug="veettil-oru-feeling",
    brief=_C1_BRIEF,
    directions=_C1_DIRECTIONS,
    specification=_C1_SPEC,
    selected_direction_ordinal=1,
    tests=[
        "Malayalam-led creative, not translated English",
        "climate as localisation instead of motif",
        "channel override that switches language for a different reader",
    ],
)


# --------------------------------------------------------------------------
# Campaign 2 — Onam
# --------------------------------------------------------------------------
_C2 = "bm-nila-campaign-onam"

_C2_BRIEF = CampaignBrief(
    campaign_id=_C2,
    title="Onathinu Veedu",
    objective=(
        "Capture the Onam furnishing and gifting peak without becoming a festival-cliché brand."
    ),
    audience=(
        "Kerala families preparing a home for Onam, and Malayali buyers outside the state sending "
        "gifts home."
    ),
    audience_insight=(
        "The Onam anxiety is not decoration. It is whether the house can seat "
        "everyone who is coming, and whether it looks like someone cared."
    ),
    product="Kaatu seating, Mazha throws",
    key_message="Make room before you make decorations.",
    supporting_messages=["Delivered before Thiruvonam", "Ten-year frame warranty"],
    cta="ORDER BEFORE ONAM",
    region="Kerala",
    language="Malayalam + English",
    channels=[Channel.INSTAGRAM_POST, Channel.INSTAGRAM_STORY, Channel.WEB_BANNER],
    tone=["warm", "practical"],
    campaign_tone=["festive", "domestic"],
    brand_requirements=[
        "festival present through preparation, not through iconography",
        "pookkalam may appear only incidentally, never centred",
    ],
    constraints=["no religious iconography", "no delivery promise without a date"],
    avoid_restrictions=["Kathakali", "Maveli costume", "stock festival imagery"],
    required_elements=["a house being made ready", "seating visible"],
    success_criteria=["pre-Onam order volume", "delivery-window conversion"],
    desired_emotional_response="Readiness rather than festivity.",
    timing_occasion="Onam, August to September",
    rationale="Tests whether occasion targeting can avoid the occasion's clichés.",
)

_C2_DIRECTIONS = [
    CreativeDirection(
        campaign_id=_C2,
        ordinal=1,
        title="Idam Undakku",
        big_idea="Onam starts with moving the furniture.",
        strategic_rationale=(
            "Occupies the true first step of the festival and owns a moment no competitor "
            "advertises."
        ),
        emotional_angle="anticipation through preparation",
        audience_connection="The annual rearranging of a living room before relatives arrive.",
        key_message="Make room before you make decorations.",
        headline="ഇടം ഉണ്ടാക്കൂ.",
        subhead="ബാക്കിയെല്ലാം പിന്നാലെ വരും.",
        cta="ORDER BEFORE ONAM",
        cta_direction="With the delivery date beneath it.",
        visual_metaphor="space cleared in advance of people",
        composition=(
            "Room mid-rearrangement; furniture off its marks; floor visible and empty in the "
            "centre."
        ),
        subject="A living room being cleared and rearranged, chairs pulled out of place.",
        environment="A Kochi home on the morning of Uthradam.",
        lighting="Bright flat morning daylight through an open door.",
        palette=["#E6DFD2", "#4A5D5A", "#8A5A3B"],
        style_families=[StyleFamily.EDITORIAL, StyleFamily.LOCAL_CULTURAL],
        color_direction="Bright, neutral, low saturation.",
        brand_integration="Wordmark on the empty floor area.",
        product_integration="Seating is the object being moved.",
        regional_considerations=[
            "a pookkalam half-finished at the frame edge, never centred",
            "contemporary Kerala home interior",
        ],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["Maveli costume", "religious iconography", "centred pookkalam"],
            avoid_styles=["stock festival imagery"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction set before the festival begins.",
    ),
    CreativeDirection(
        campaign_id=_C2,
        ordinal=2,
        title="Randu Kasera Koodi",
        big_idea="Two more chairs is the whole gift.",
        strategic_rationale=(
            "Reduces the proposition to a single purchasable unit, which is what a gifting "
            "campaign needs."
        ),
        emotional_angle="practical generosity",
        audience_connection="Sending something home that will actually be used.",
        key_message="Make room before you make decorations.",
        headline="രണ്ടു കസേര കൂടി.",
        subhead="അത്രയും മതി.",
        cta="ORDER BEFORE ONAM",
        cta_direction="Inline beside the subhead.",
        visual_metaphor="addition as affection",
        composition="Two chairs alone against a plain wall, one slightly angled toward the other.",
        subject="Two Kaatu chairs, nothing else in frame.",
        environment="A plain lime-plaster wall in a Kerala home.",
        lighting="Soft directional daylight from the left, gentle shadow.",
        palette=["#8A5A3B", "#E6DFD2", "#221F1C"],
        style_families=[StyleFamily.MINIMAL, StyleFamily.PREMIUM],
        color_direction="Teak against bone; nothing else.",
        brand_integration="Wordmark on the wall beside the chairs.",
        product_integration="Product is the entire frame, unstyled.",
        regional_considerations=["lime plaster wall as the only locating cue"],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["festival decoration of any kind"],
            avoid_styles=["clinical product lighting"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction with no room and no people — product alone.",
    ),
    CreativeDirection(
        campaign_id=_C2,
        ordinal=3,
        title="Sadya Kazhinju",
        big_idea="The best hour of Onam is the one after lunch.",
        strategic_rationale=(
            "Claims the aftermath rather than the event, which is both truer and entirely unowned."
        ),
        emotional_angle="contentment",
        audience_connection="The specific collapse of a family after the sadya.",
        key_message="A home is the feeling made inside it.",
        headline="സദ്യ കഴിഞ്ഞു.",
        subhead="ഇനി ഇരിക്കാം.",
        cta="ORDER BEFORE ONAM",
        cta_direction="Small, bottom-right.",
        visual_metaphor="rest after effort",
        composition="Room after a meal; people slumped across seating; cleared plates at the edge.",
        subject="A family resting in a living room after a large lunch.",
        environment="A Kochi home in the early afternoon, doors open, rain starting outside.",
        lighting="Flat post-noon overcast light, humid.",
        palette=["#4A5D5A", "#E6DFD2", "#8A5A3B"],
        style_families=[StyleFamily.LOCAL_CULTURAL, StyleFamily.EDITORIAL],
        color_direction="Muted, humid, slightly cool.",
        brand_integration="Wordmark in the quiet upper wall area.",
        product_integration="Seating in heavy use, partly obscured by people.",
        regional_considerations=[
            "the sadya present only as cleared leaves at the frame edge",
            "ordinary contemporary clothing",
        ],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["centred sadya spread", "traditional costume as styling"],
            avoid_styles=["stock festival imagery"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction set after the festival's peak.",
    ),
]

_C2_SPEC = CreativeSpecification(
    campaign_id=_C2,
    direction_id="bm-nila-dir-4",
    version=1,
    concept="Onam starts with moving the furniture.",
    visual_story=(
        "The morning before Thiruvonam. A living room is mid-rearrangement — "
        "chairs pulled off their marks, the centre of the floor cleared for "
        "people who have not arrived yet. A pookkalam is half-finished at the "
        "edge of frame, unremarked."
    ),
    emotional_angle="anticipation through preparation",
    headline="ഇടം ഉണ്ടാക്കൂ.",
    subhead="ബാക്കിയെല്ലാം പിന്നാലെ വരും.",
    cta="ORDER BEFORE ONAM",
    visual_metaphor="space cleared in advance of people",
    composition="Room mid-rearrangement; empty floor at centre; upper third quiet for type.",
    focal_point="the cleared floor where people will sit",
    subject="A living room being cleared and rearranged for guests.",
    environment="A contemporary Kochi home on the morning of Uthradam, door open to green.",
    lighting="Bright flat morning daylight through an open door; no hard shadow.",
    camera="28mm, f/4, standing height",
    palette=["#E6DFD2", "#4A5D5A", "#8A5A3B"],
    color_direction="Bright neutral ground, low saturation, one teak accent.",
    style_families=[StyleFamily.EDITORIAL, StyleFamily.LOCAL_CULTURAL],
    mood=["anticipatory", "domestic", "bright"],
    product_integration="Seating is the object being moved, shown mid-handling.",
    people_guidance="One or two people mid-task, faces away from camera.",
    brand_integration="Wordmark composited onto the cleared floor area.",
    regional_cues=[
        "a half-finished pookkalam at the frame edge, never centred",
        "contemporary Kerala home interior",
        "green visible through an open door",
    ],
    negative_constraints=NegativeConstraints(
        forbidden_elements=[
            "Maveli costume",
            "religious iconography",
            "a centred pookkalam",
            "Kathakali imagery",
        ],
        forbidden_text=["waterproof", "guaranteed delivery"],
        avoid_styles=["stock festival imagery", "golden-hour grading"],
        no_text_in_image=True,
    ),
    channel_copy={
        Channel.WEB_BANNER: ChannelCopy(
            headline="Make room before Onam.",
            subhead="Order by 2 September for delivery before Thiruvonam.",
        ),
    },
)

CAMPAIGN_ONAM = BenchmarkCampaign(
    slug="onathinu-veedu",
    brief=_C2_BRIEF,
    directions=_C2_DIRECTIONS,
    specification=_C2_SPEC,
    selected_direction_ordinal=1,
    tests=[
        "festival targeting without festival cliché",
        "occasion-driven seasonality in the Campaign Specification",
        "local cue admitted only at the frame edge",
    ],
)


# --------------------------------------------------------------------------
# Campaign 3 — Trade / specifiers
# --------------------------------------------------------------------------
_C3 = "bm-nila-campaign-specify"

_C3_BRIEF = CampaignBrief(
    campaign_id=_C3,
    title="Specified, Not Styled",
    objective=(
        "Get Nila Living onto architects' and interior designers' specification lists for coastal "
        "residential projects."
    ),
    audience=(
        "Architects, interior designers and project managers working on residential projects in "
        "coastal Kerala and Karnataka."
    ),
    audience_insight=(
        "A specifier's reputation is damaged by a failure eighteen months "
        "after handover. They buy against that risk, not against a look."
    ),
    product="Kaatu seating, contract quantities",
    key_message="Specified for humidity, with the test data to back it.",
    supporting_messages=["Tested through a full monsoon season", "Ten-year frame warranty"],
    cta="REQUEST SPECIFICATIONS",
    region="Coastal Kerala and Karnataka",
    language="English",
    channels=[Channel.LINKEDIN, Channel.WEB_BANNER],
    tone=["precise", "plain-spoken"],
    campaign_tone=["professional", "technical"],
    brand_requirements=["English only", "material and test conditions named"],
    constraints=["no claim beyond the approved list", "no waterproof language"],
    avoid_restrictions=["lifestyle imagery", "festival imagery", "regional motif"],
    required_elements=["material or construction visible", "left area clear for type"],
    success_criteria=["specification requests", "projects won"],
    desired_emotional_response="Confidence that this will not fail after handover.",
    timing_occasion="Project specification season, October to January",
    rationale="Same brand, professional audience, localisation deliberately minimal.",
)

_C3_DIRECTIONS = [
    CreativeDirection(
        campaign_id=_C3,
        ordinal=1,
        title="One Monsoon In",
        big_idea="Every frame we sell has already survived a monsoon.",
        strategic_rationale=(
            "Converts the brand's one verifiable test into the entire specification argument."
        ),
        emotional_angle="risk removed",
        audience_connection="Specifiers fear the failure they cannot inspect for.",
        key_message="Specified for humidity, with the test data to back it.",
        headline="One monsoon in.",
        subhead="Every frame is tested through a full season before it ships.",
        cta="REQUEST SPECIFICATIONS",
        cta_direction="Left-aligned beneath the subhead.",
        visual_metaphor="proof by exposure",
        composition="Frames on a covered test rack; rain beyond; left third empty for type.",
        subject="Teak frames on an open-sided test rack during rain.",
        environment="A covered workshop yard in Aluva during monsoon.",
        lighting="Flat overcast, high humidity haze, no key light.",
        palette=["#4A5D5A", "#8A5A3B", "#E6DFD2"],
        style_families=[StyleFamily.TECHNICAL, StyleFamily.EDITORIAL],
        color_direction="Cool, damp, desaturated.",
        brand_integration="Wordmark in the empty left third.",
        product_integration="Product as frames under test, not as finished furniture.",
        regional_considerations=["monsoon is the test condition, so weather is functional here"],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["styled interiors", "people relaxing"],
            avoid_styles=["lifestyle staging"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction where rain is a test rather than a mood.",
    ),
    CreativeDirection(
        campaign_id=_C3,
        ordinal=2,
        title="The Joint",
        big_idea="The joint is the specification.",
        strategic_rationale="Speaks to the one detail a specifier actually inspects.",
        emotional_angle="technical respect",
        audience_connection="Architects judge furniture at the joint.",
        key_message="Specified for humidity, with the test data to back it.",
        headline="Look at the joint.",
        subhead="Solid teak, mortise and tenon, no fasteners in the frame.",
        cta="REQUEST SPECIFICATIONS",
        cta_direction="Beneath the subhead.",
        visual_metaphor="construction as argument",
        composition="Macro on a frame joint; extreme shallow depth; clean field above.",
        subject="A mortise-and-tenon joint in solid teak.",
        environment="A workshop bench, out of focus behind.",
        lighting="Hard raking light to reveal the joint line and grain.",
        palette=["#8A5A3B", "#221F1C", "#E6DFD2"],
        style_families=[StyleFamily.TECHNICAL, StyleFamily.MINIMAL],
        color_direction="Warm wood against neutral dark.",
        brand_integration="Wordmark above the joint, small.",
        product_integration="A construction detail stands for the product.",
        regional_considerations=["none; construction is not a regional argument"],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["finished room context"],
            avoid_styles=["HDR"],
            no_text_in_image=True,
        ),
        distinctness_note="The only macro direction in this campaign.",
    ),
    CreativeDirection(
        campaign_id=_C3,
        ordinal=3,
        title="Eighteen Months",
        big_idea="Show the piece after the project, not at handover.",
        strategic_rationale=(
            "Attacks the specifier's real timeline — the callback — which no competitor's imagery "
            "addresses."
        ),
        emotional_angle="vindication",
        audience_connection="The photographs specifiers never get to see.",
        key_message="Specified for humidity, with the test data to back it.",
        headline="Eighteen months later.",
        subhead="The same frame, in the same room, in the same climate.",
        cta="REQUEST SPECIFICATIONS",
        cta_direction="Right of the subhead.",
        visual_metaphor="time as evidence",
        composition=(
            "Wide interior of a completed project, furniture visibly used; left half quiet."
        ),
        subject="Installed seating in a finished coastal residence, well used.",
        environment="A completed Kerala coastal home, lived in for over a year.",
        lighting="Available daylight only, flat and humid.",
        palette=["#E6DFD2", "#4A5D5A", "#8A5A3B"],
        style_families=[StyleFamily.EDITORIAL, StyleFamily.TECHNICAL],
        color_direction="Neutral and honest; no grade that flatters.",
        brand_integration="Wordmark in the quiet left half.",
        product_integration="Product shown after wear, deliberately not refreshed.",
        regional_considerations=["a real coastal Kerala interior, contemporary"],
        negative_constraints=NegativeConstraints(
            forbidden_elements=["freshly styled handover photography"],
            avoid_styles=["real-estate wide-angle distortion"],
            no_text_in_image=True,
        ),
        distinctness_note="The only direction showing an installed project.",
    ),
]

_C3_SPEC = CreativeSpecification(
    campaign_id=_C3,
    direction_id="bm-nila-dir-7",
    version=1,
    concept="Every frame we sell has already survived a monsoon.",
    visual_story=(
        "A covered workshop yard in Aluva during heavy rain. Teak frames sit "
        "on an open-sided test rack, exposed to the humidity they will spend "
        "their lives in. Nothing is styled; the picture is documentation."
    ),
    emotional_angle="risk removed",
    headline="One monsoon in.",
    subhead="Every frame is tested through a full season before it ships.",
    cta="REQUEST SPECIFICATIONS",
    visual_metaphor="proof by exposure",
    composition="Frames on a covered test rack; rain beyond; left third kept empty for type.",
    focal_point="the damp sheen on exposed teak",
    subject="Teak frames on an open-sided test rack during rain.",
    environment="A covered workshop yard in Aluva during the monsoon.",
    lighting="Flat overcast with humid haze; no key light; no hard shadow.",
    camera="35mm, f/5.6, chest height",
    palette=["#4A5D5A", "#8A5A3B", "#E6DFD2"],
    color_direction="Cool, damp and desaturated; deliberately unflattering.",
    style_families=[StyleFamily.TECHNICAL, StyleFamily.EDITORIAL],
    mood=["precise", "damp", "credible"],
    product_integration="Product as frames under test, never as finished furniture.",
    people_guidance="No people in frame.",
    brand_integration="Wordmark composited into the empty left third.",
    regional_cues=["monsoon as the functional test condition"],
    negative_constraints=NegativeConstraints(
        forbidden_elements=[
            "styled interiors",
            "people relaxing",
            "Kathakali or houseboat imagery",
        ],
        forbidden_text=["waterproof", "mould-proof", "100% sustainable"],
        avoid_styles=["lifestyle staging", "HDR"],
        no_text_in_image=True,
    ),
    channel_copy={
        Channel.WEB_BANNER: ChannelCopy(
            headline="Tested through a full monsoon.",
            subhead="Contract seating for coastal residential projects.",
        ),
    },
)

CAMPAIGN_SPECIFY = BenchmarkCampaign(
    slug="specified-not-styled",
    brief=_C3_BRIEF,
    directions=_C3_DIRECTIONS,
    specification=_C3_SPEC,
    selected_direction_ordinal=1,
    tests=[
        "same brand, professional audience, English-only",
        "localisation reduced to a functional variable",
        "claim discipline under a longer prohibited list",
    ],
)


COMPANY = BenchmarkCompany(
    slug=SLUG,
    display_name="Nila Living",
    size=CompanySize.MID_SIZE,
    industry="Home and lifestyle — furniture and soft furnishing",
    market=MARKET,
    languages=LANGUAGES,
    brand=BRAND,
    references=REFERENCES,
    campaigns=[CAMPAIGN_FEELING, CAMPAIGN_ONAM, CAMPAIGN_SPECIFY],
    selection_rationale=(
        "The mid-size case and the one the naive-versus-hyperlocal comparison "
        "rests on. Kerala's usable localisation is climate and material, which "
        "a translation-only pipeline cannot reach: it will produce correct "
        "Malayalam over a frame lit like Rajasthan and call the job done."
    ),
)
