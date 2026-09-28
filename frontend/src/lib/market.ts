/**
 * Where a campaign runs, and how well we actually know it.
 *
 * Hyperlocalization is the product's reason to exist, so the interface has to
 * do more than print `region`. It has to say whether a person told us the
 * place, whether the brand supplied it, or whether a model guessed — because
 * "Jaipur, because you said so" and "Jaipur, because we inferred it" are
 * different facts and a campaign is approved on the difference.
 *
 * All of this is real data. `CampaignSpecification.field_assertions` carries an
 * `availability` (`known` / `unknown` / `not_applicable`) and a `certainty`
 * (`stated` / `brand_default` / `inferred` / `unresolved`) per field, which is
 * exactly the trichotomy the Local Market panel needs. Nothing here invents a
 * value, substitutes a plausible one, or upgrades a guess into a statement.
 *
 * What it must never do is parse. `region` is one free-text string
 * (`"Jaipur, Rajasthan"`), not structured city and state, and `language` is one
 * string (`"Hindi + English"`), not a list. See `docs/UI_UX_VISION.md` §5.
 */

import type { CampaignSpecification, FieldAssertion } from '@/lib/api';

/**
 * How a fact came to be known.
 *
 * `unrecorded` is the honest answer for a value the specification holds without
 * an assertion explaining it — common for fields with a schema default. It is
 * not the same as `inferred`, which is a positive claim that a model guessed;
 * collapsing the two would attribute a guess the system never made.
 */
export type Confidence = 'stated' | 'brand' | 'inferred' | 'unrecorded' | 'unknown';

export interface MarketFact {
  /** The specification field this came from. */
  key: string;
  /** The user's words for it, never the schema's. */
  label: string;
  value: string | null;
  confidence: Confidence;
}

/** Short badges. `unrecorded` gets none — silence beats an unfounded claim. */
export const CONFIDENCE_LABEL: Record<Confidence, string | null> = {
  stated: 'Stated',
  brand: 'From brand',
  inferred: 'Inferred',
  unrecorded: null,
  unknown: 'Not set',
};

/** One sentence each, for the tooltip and for the panel's own legend. */
export const CONFIDENCE_MEANING: Record<Confidence, string> = {
  stated: 'Someone told us this outright.',
  brand: 'Taken from the brand’s own defaults.',
  inferred: 'Inferred from the conversation — worth confirming.',
  unrecorded: 'Recorded on the specification without a stated source.',
  unknown: 'Not known yet.',
};

function confidenceOf(assertion: FieldAssertion | undefined, value: string | null): Confidence {
  // No value is no value, whatever an assertion claims about it.
  if (!value || !value.trim()) return 'unknown';
  if (!assertion) return 'unrecorded';
  if (assertion.availability !== 'known') return 'unknown';
  switch (assertion.certainty) {
    case 'stated':
      return 'stated';
    case 'brand_default':
      return 'brand';
    case 'inferred':
      return 'inferred';
    // `unresolved` means the interview never settled it. A value that survived
    // to the specification anyway is recorded, not asserted.
    case 'unresolved':
      return 'unrecorded';
  }
}

/** The fields that answer "why does this campaign belong in this market?". */
const MARKET_FIELDS: { key: keyof CampaignSpecification & string; label: string }[] = [
  { key: 'region', label: 'Place' },
  { key: 'language', label: 'Language' },
  { key: 'timing_occasion', label: 'Season or occasion' },
  { key: 'audience', label: 'Audience' },
  { key: 'audience_insight', label: 'Audience insight' },
];

/**
 * The market picture, in display order.
 *
 * A null specification yields every field as `unknown` rather than an empty
 * list: a campaign still in discovery has no specification, and the panel
 * should say what is not known yet instead of rendering nothing and implying
 * there is nothing to know.
 */
export function marketFacts(specification: CampaignSpecification | null): MarketFact[] {
  return MARKET_FIELDS.map(({ key, label }) => {
    const raw = specification ? specification[key] : null;
    const text = typeof raw === 'string' && raw.trim() ? raw.trim() : null;
    const value = key === 'language' ? displayLanguage(text) : text;
    const assertion = specification?.field_assertions?.[key];
    return { key, label, value, confidence: confidenceOf(assertion, value) };
  });
}

/**
 * A language value, as a person would say it.
 *
 * `CampaignSpecification.language` defaults to the literal `"en"` and is not
 * among the fields the brief interview asks about, so most campaigns carry a
 * bare ISO code that reads on screen as a bug. This renders the handful of
 * codes the product realistically sees as their English names and passes
 * everything else through untouched — `"Hindi + English"` is already how a
 * person would say it and must not be parsed.
 *
 * A display transform of a real value, never a substitution: an unrecognised
 * code is shown as it is stored rather than guessed at.
 */
const LANGUAGE_NAME: Record<string, string> = {
  en: 'English',
  hi: 'Hindi',
  as: 'Assamese',
  bn: 'Bengali',
  ml: 'Malayalam',
  ta: 'Tamil',
  te: 'Telugu',
  kn: 'Kannada',
  mr: 'Marathi',
  gu: 'Gujarati',
  pa: 'Punjabi',
};

export function displayLanguage(value: string | null | undefined): string | null {
  const raw = value?.trim();
  if (!raw) return null;
  return LANGUAGE_NAME[raw.toLowerCase()] ?? raw;
}

/** True when at least one market fact is actually known. */
export function hasMarket(facts: readonly MarketFact[]): boolean {
  return facts.some((f) => f.value !== null);
}

/**
 * What the campaign must include locally, and what it must avoid.
 *
 * Both are real `string[]` fields on the specification. They are the sharp end
 * of localization — the cue that makes a creative belong, and the line it must
 * not cross — so they are surfaced rather than buried in a spec dump.
 */
export function localCues(specification: CampaignSpecification | null): {
  required: string[];
  avoid: string[];
} {
  return {
    required: specification?.required_elements ?? [],
    avoid: specification?.avoid_restrictions ?? [],
  };
}

// --------------------------------------------------------- creative meaning

/**
 * What a market fact means for the creative.
 *
 * The Local Market surface has to answer "why does this campaign belong here?",
 * and a place name alone does not answer it. This turns each fact into the
 * instruction it implies for the work.
 *
 * These are *templates over real values*, not invented data. The rule
 * "a campaign written in two languages needs quiet space for longer text" is a
 * design consequence of the `language` field, the same way "leave a text safe
 * area" is a consequence of the channel. Nothing here asserts a fact the
 * specification does not hold, and a field with no value produces no
 * implication at all — the absence is reported instead.
 */
export function creativeImplication(fact: MarketFact): string | null {
  if (!fact.value) return null;
  const value = inline(fact.value);
  // Long free-text values make a run-on sentence when quoted back. Above this
  // the implication is phrased without repeating the value, which the reader
  // can see directly above it anyway.
  const brief = value.length <= 60;
  switch (fact.key) {
    case 'region':
      return `Environment, architecture, signage and casting should read as ${value} — not as a generic city.`;
    case 'language':
      return `Headline and call to action are written in ${value}. The visual needs quiet space for that text, and more of it where two scripts run together.`;
    case 'timing_occasion':
      return brief
        ? `Light, wardrobe and seasonal cues should belong to ${value}.`
        : 'Light, wardrobe and seasonal cues should belong to this moment in the year.';
    case 'audience':
      return brief
        ? `Casting, styling and setting should be recognisable to ${value}.`
        : 'Casting, styling and setting should be recognisable to these people — not to a generic urban audience.';
    case 'audience_insight':
      return 'This is the tension the creative has to answer, not decorate.';
    default:
      return null;
  }
}

/**
 * Prepare a stored value for quoting inside a sentence.
 *
 * Specification fields are written as prose and often end in a full stop, which
 * produces "…several times a week.." when interpolated. Trailing sentence
 * punctuation is dropped; nothing else about the value is touched.
 */
function inline(value: string): string {
  return value.trim().replace(/[.!?]+$/, '');
}

/**
 * How much to trust a fact when acting on it.
 *
 * An inferred market is still actionable — it just deserves a look before the
 * campaign is built on it. Returned separately from the implication so a screen
 * can show the caution beside the instruction rather than blurring the two.
 */
export function confidenceCaution(confidence: Confidence): string | null {
  switch (confidence) {
    case 'inferred':
      return 'Inferred from the conversation. Worth confirming before this drives the creative.';
    case 'unknown':
      return 'Not known yet, so nothing in the creative can rely on it.';
    // `unrecorded` deliberately returns nothing. It is the common case for a
    // specification written directly rather than through discovery, and
    // repeating "recorded without a stated source" on every row is noise that
    // teaches people to stop reading the line that matters. The screen says it
    // once, for the whole set, where it is actually informative.
    case 'unrecorded':
    default:
      return null;
  }
}

/** True when nothing in the set records where it came from. */
export function allUnrecorded(facts: readonly MarketFact[]): boolean {
  const withValues = facts.filter((f) => f.value);
  return withValues.length > 0 && withValues.every((f) => f.confidence === 'unrecorded');
}

// ------------------------------------------------------------ across campaigns

export interface MarketGroup {
  /** The `region` string, exactly as the specification holds it. */
  region: string;
  /** Distinct languages seen for this region. */
  languages: string[];
  /** Distinct audiences seen for this region. */
  audiences: string[];
  /** Campaign ids in this region — a count nobody had to invent. */
  campaignIds: string[];
}

/**
 * Group campaigns by the market they run in.
 *
 * Takes already-fetched specifications rather than fetching: the caller knows
 * how many campaigns it is willing to resolve, and a helper that quietly issues
 * N requests is a helper that makes a page slow in a way nobody can see.
 *
 * Campaigns with no region are omitted entirely. They are not an "Unknown"
 * market — they are campaigns whose market has not been decided, and inventing
 * a bucket for them would put a fake pin on the map.
 */
export function groupByMarket(
  entries: readonly { campaignId: string; specification: CampaignSpecification | null }[],
): MarketGroup[] {
  const groups = new Map<string, MarketGroup>();
  for (const { campaignId, specification } of entries) {
    const region = specification?.region?.trim();
    if (!region) continue;
    const group = groups.get(region) ?? {
      region,
      languages: [],
      audiences: [],
      campaignIds: [],
    };
    const language = specification?.language?.trim();
    if (language && !group.languages.includes(language)) group.languages.push(language);
    const audience = specification?.audience?.trim();
    if (audience && !group.audiences.includes(audience)) group.audiences.push(audience);
    group.campaignIds.push(campaignId);
    groups.set(region, group);
  }
  // Busiest market first, then alphabetical so the order is stable between
  // renders rather than following whatever order the requests resolved in.
  return [...groups.values()].sort(
    (a, b) => b.campaignIds.length - a.campaignIds.length || a.region.localeCompare(b.region),
  );
}
