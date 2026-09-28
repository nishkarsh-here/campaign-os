/**
 * Reading the creative stage.
 *
 * Every interpretation of a backend field for the creative screens lives here,
 * so no component has to know that "why this direction exists" is
 * `strategic_rationale`, or that a direction has no `mood` while the plan does.
 * Scatter that across JSX and the three cards drift apart.
 *
 * ## What is not here, and why
 *
 * `visual_story`, `camera` and `mood` are fields of `CreativeSpecification`,
 * not of `CreativeDirection`. They do not exist at the direction stage, so a
 * concept card cannot show them and this module offers no way to. Nothing here
 * substitutes a near-enough field for a missing one — a card section that
 * quietly renders `visual_metaphor` under the heading "Visual story" would be a
 * lie told in the user's own vocabulary.
 *
 * Likewise `recommended_ordinal` and `recommendation_reasons` are properties of
 * the *set*, not of a direction. The reasons explain why one won; attaching
 * them to a card would read as that card's own rationale.
 */

import type {
  CampaignSpecification,
  Channel,
  ChannelCopy,
  CreativeDirection,
  CreativeDirectionSet,
  CreativeSpecification,
  CreativeStageView,
} from '@/lib/api';

// ------------------------------------------------------------------ the card

/** A labelled passage on a direction card. Absent values are never rendered. */
export interface DirectionSection {
  label: string;
  value: string;
}

export interface DirectionView {
  id: string;
  ordinal: number;
  /** "01", "02", "03" — the editorial numbering. */
  number: string;
  title: string;
  /** One line. The concept, said once. */
  statement: string;
  /**
   * Why this direction exists.
   *
   * `strategic_rationale` is written by the Creative Director for a person to
   * read, so it is shown as the model's own reasoning rather than relabelled
   * "based on campaign context". Where it is empty the section is omitted —
   * the screen never claims a rationale it was not given.
   */
  rationale: string | null;
  /** The proposed words. */
  headline: string;
  subhead: string | null;
  cta: string;
  ctaDirection: string | null;
  /** Read in order; each present only when the direction actually carries it. */
  sections: DirectionSection[];
  /** `regional_considerations` — the localisation the model reasoned about. */
  localRelevance: string[];
  brandFit: DirectionSection[];
  /** What the references contributed, and what was deliberately left behind. */
  referenceUsed: string[];
  referenceAvoided: string[];
  /** Colours the direction names. Shown as swatches, never as a brand palette. */
  palette: string[];
  styleFamilies: string[];
  /** Set-level: this is the one the Creative Director put forward. */
  recommended: boolean;
  /** Set-level: the server's record of what a human approved. */
  selected: boolean;
  /** Why the distinctness check flagged it, where it did. */
  distinctness: string | null;
}

function present(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

function section(label: string, value: string | null | undefined): DirectionSection | null {
  const v = present(value);
  return v ? { label, value: v } : null;
}

/**
 * Turn one direction into what a card shows.
 *
 * Sections are built by filtering, not by rendering placeholders: a direction
 * whose `environment` is empty simply has no Environment row.
 */
export function toDirectionView(
  direction: CreativeDirection,
  set: CreativeDirectionSet,
  selectedId: string | null,
): DirectionView {
  return {
    id: direction.id,
    ordinal: direction.ordinal,
    number: String(direction.ordinal).padStart(2, '0'),
    title: direction.title,
    statement: direction.big_idea,
    rationale: present(direction.strategic_rationale),
    headline: direction.headline,
    subhead: present(direction.subhead),
    cta: direction.cta,
    ctaDirection: present(direction.cta_direction),
    sections: [
      section('The idea', direction.key_message),
      section('Who it speaks to', direction.audience_connection),
      section('How it should feel', direction.emotional_angle),
      section('What you see', direction.visual_metaphor),
      section('Subject', direction.subject),
      section('Setting', direction.environment),
      section('Composition', direction.composition),
      section('Light', direction.lighting),
      section('Colour', direction.color_direction),
    ].filter((s): s is DirectionSection => s !== null),
    localRelevance: direction.regional_considerations.filter((r) => r.trim()),
    brandFit: [
      section('Brand', direction.brand_integration),
      section('Product', direction.product_integration),
    ].filter((s): s is DirectionSection => s !== null),
    referenceUsed: direction.reference_characteristics_used.filter((r) => r.trim()),
    referenceAvoided: direction.reference_characteristics_avoided.filter((r) => r.trim()),
    palette: direction.palette.filter((p) => p.trim()),
    styleFamilies: direction.style_families.filter((s) => s.trim()),
    recommended: set.recommended_ordinal === direction.ordinal,
    selected: selectedId === direction.id,
    distinctness: present(direction.distinctness_note),
  };
}

// ------------------------------------------------------------- the comparison

/**
 * The axes on which two directions can genuinely be compared.
 *
 * Every one is a real `CreativeDirection` field. The brief also asked to
 * compare "visual story", "camera" and "mood" — none of which exist here — so
 * they are absent rather than approximated.
 */
const AXES: { label: string; read: (d: CreativeDirection) => string | null }[] = [
  { label: 'The idea', read: (d) => present(d.big_idea) },
  { label: 'Headline', read: (d) => present(d.headline) },
  { label: 'How it should feel', read: (d) => present(d.emotional_angle) },
  { label: 'Subject', read: (d) => present(d.subject) },
  { label: 'Setting', read: (d) => present(d.environment) },
  { label: 'Composition', read: (d) => present(d.composition) },
  { label: 'Light', read: (d) => present(d.lighting) },
  { label: 'Colour', read: (d) => present(d.color_direction) },
  { label: 'Brand fit', read: (d) => present(d.brand_integration) },
  {
    label: 'Local relevance',
    read: (d) => (d.regional_considerations.length ? d.regional_considerations.join(' · ') : null),
  },
];

export interface ComparisonRow {
  label: string;
  /** One cell per direction, in ordinal order. Null renders as "not specified". */
  values: (string | null)[];
  /** False when every direction says the same thing — then it is not a difference. */
  differs: boolean;
}

/**
 * Compare the directions axis by axis.
 *
 * Rows where every direction agrees are still returned, flagged `differs:
 * false`, so the screen can show what is *shared* as well as what changes —
 * "they all keep the product in frame" is information too. What it must not do
 * is present agreement as a difference.
 */
export function compareDirections(directions: readonly CreativeDirection[]): ComparisonRow[] {
  const ordered = [...directions].sort((a, b) => a.ordinal - b.ordinal);
  return AXES.map(({ label, read }) => {
    const values = ordered.map(read);
    const filled = values.filter((v): v is string => v !== null);
    const differs = new Set(filled).size > 1;
    return { label, values, differs };
  }).filter((row) => row.values.some((v) => v !== null));
}

/** Only the axes that actually distinguish the directions. */
export function differencesOnly(rows: readonly ComparisonRow[]): ComparisonRow[] {
  return rows.filter((r) => r.differs);
}

// ------------------------------------------------------------------ the state

export type CreativeState =
  /** No direction set has been generated yet. */
  | 'not_started'
  /** Gate 1 is open: three directions await a human choice. */
  | 'choosing'
  /** A direction was approved; the plan is being written or awaits Gate 2. */
  | 'planning'
  /** Gate 2 passed. The plan is approved and generation may begin. */
  | 'approved';

export interface StageState {
  state: CreativeState;
  /** The reader's words for where this campaign stands. */
  label: string;
  /** One sentence explaining what that means. */
  detail: string;
}

/**
 * Where the creative stage stands.
 *
 * Read from `gate`, `approved` and `direction_set` — never from the campaign
 * row's status, which only tracks discovery and stops at
 * SPECIFICATION_CONFIRMED however far the creative work has gone.
 */
export function creativeState(view: CreativeStageView | null): StageState {
  if (!view || !view.direction_set) {
    return {
      state: 'not_started',
      label: 'Not started',
      detail: 'No creative routes have been developed from the brief yet.',
    };
  }
  if (view.approved) {
    return {
      state: 'approved',
      label: 'Creative plan approved',
      detail: 'The plan is signed off. Generation works from it.',
    };
  }
  if (view.gate === 'specification_gate' || view.specification) {
    return {
      state: 'planning',
      label: 'Plan needs review',
      detail: 'The chosen direction has been worked into a plan. Read it, then approve.',
    };
  }
  return {
    state: 'choosing',
    label: 'Choose a direction',
    detail: 'Three routes are on the table. Choosing one is a human decision.',
  };
}

// ------------------------------------------------------------- the plan

export interface PlanSection {
  label: string;
  /** Rendered as a paragraph, or as a list when the field is a `string[]`. */
  value: string | string[];
  /** True when a human changed this field; a regeneration must not undo it. */
  edited: boolean;
  /** True when a revision may not touch it without being explicitly asked. */
  locked: boolean;
}

/**
 * The Creative Plan, grouped the way a marketer reads it.
 *
 * `locked` comes from the specification's own `locked_fields`, not from a
 * constant copied out of the backend — a hardcoded list here would quietly
 * disagree the day the backend's changes.
 */
export function planSections(spec: CreativeSpecification): {
  idea: PlanSection[];
  words: PlanSection[];
  visual: PlanSection[];
  guardrails: PlanSection[];
} {
  const flag = (field: string) => ({
    edited: spec.human_edited_fields.includes(field),
    locked: spec.locked_fields.includes(field),
  });
  const make = (
    label: string,
    field: string,
    value: string | string[] | null,
  ): PlanSection | null => {
    if (value === null) return null;
    if (Array.isArray(value) && value.length === 0) return null;
    if (typeof value === 'string' && !value.trim()) return null;
    return { label, value, ...flag(field) };
  };
  const keep = (rows: (PlanSection | null)[]) => rows.filter((r): r is PlanSection => r !== null);

  return {
    idea: keep([
      make('Core idea', 'concept', spec.concept),
      make('How it should feel', 'emotional_angle', spec.emotional_angle),
      make('Why it works', 'visual_story', spec.visual_story),
    ]),
    words: keep([
      make('Headline', 'headline', spec.headline),
      make('Subhead', 'subhead', spec.subhead),
      make('Call to action', 'cta', spec.cta),
      make('Body copy', 'body_copy', spec.body_copy),
      make('How the headline should read', 'headline_guidance', spec.headline_guidance),
    ]),
    visual: keep([
      make('What you see', 'visual_metaphor', spec.visual_metaphor),
      make('Subject', 'subject', spec.subject),
      make('Setting', 'environment', spec.environment),
      make('Composition', 'composition', spec.composition),
      make('Focal point', 'focal_point', spec.focal_point),
      make('Light', 'lighting', spec.lighting),
      make('Camera', 'camera', spec.camera),
      make('Colour', 'color_direction', spec.color_direction),
      make('Mood', 'mood', spec.mood),
      make('Style', 'style_families', spec.style_families),
      make('Local cues', 'regional_cues', spec.regional_cues),
    ]),
    guardrails: keep([
      make('How the brand appears', 'brand_integration', spec.brand_integration),
      make('How the product appears', 'product_integration', spec.product_integration),
      make('People', 'people_guidance', spec.people_guidance),
    ]),
  };
}

// ------------------------------------------------------------- channel copy

export type CopyOrigin = 'default' | 'channel' | 'locked';

export interface ResolvedLine {
  label: string;
  /** The words that will actually be used for this channel. */
  value: string | null;
  origin: CopyOrigin;
}

export interface ChannelPlan {
  channel: Channel;
  lines: ResolvedLine[];
  /** True when this channel overrides nothing — it inherits throughout. */
  inheritsEverything: boolean;
}

/**
 * What each channel will actually say.
 *
 * `ChannelCopy` is a sparse diff: an absent or null field means *inherit the
 * specification's default*, not "this channel has no headline". The backend
 * resolves this with `copy_for`, which is not exposed to the frontend, so the
 * same rule is applied here — and applied in one place, because four
 * independent `or` chains is exactly how the screens came to disagree about
 * what the approved words are (CLAUDE.md, Milestone 11).
 *
 * The call to action is marked `locked` when the specification says so. A
 * locked field is one a revision may not change unless the feedback explicitly
 * asked — it is not a field a person may never edit.
 */
export function channelPlans(
  spec: CreativeSpecification,
  declared: readonly Channel[],
): ChannelPlan[] {
  const ctaLocked = spec.locked_fields.includes('cta');
  return declared.map((channel) => {
    const override: ChannelCopy | undefined = spec.channel_copy[channel];
    const line = (
      label: string,
      key: keyof ChannelCopy,
      fallback: string | null,
    ): ResolvedLine => {
      const own = override?.[key];
      const overridden = own !== undefined && own !== null && String(own).trim() !== '';
      return {
        label,
        value: overridden ? String(own) : fallback,
        origin: overridden ? 'channel' : key === 'cta' && ctaLocked ? 'locked' : 'default',
      };
    };
    const lines = [
      line('Headline', 'headline', spec.headline),
      line('Subhead', 'subhead', spec.subhead),
      line('Call to action', 'cta', spec.cta),
    ];
    return {
      channel,
      lines,
      inheritsEverything: lines.every((l) => l.origin !== 'channel'),
    };
  });
}

/** What an origin means, in the reader's words. */
export const ORIGIN_LABEL: Record<CopyOrigin, string> = {
  default: 'Uses campaign default',
  channel: 'Written for this channel',
  locked: 'Locked — approved wording',
};

// ------------------------------------------------------------------- context

/** The compact context strip above the directions. Real values only. */
export function contextStrip(
  specification: CampaignSpecification | null,
  brandName: string | null,
): { label: string; value: string }[] {
  const rows: { label: string; value: string | null }[] = [
    { label: 'Brand', value: brandName },
    { label: 'Market', value: specification?.region ?? null },
    { label: 'Audience', value: specification?.audience ?? null },
    { label: 'Objective', value: specification?.objective ?? null },
  ];
  return rows
    .map((r) => ({ label: r.label, value: present(r.value) }))
    .filter((r): r is { label: string; value: string } => r.value !== null);
}
