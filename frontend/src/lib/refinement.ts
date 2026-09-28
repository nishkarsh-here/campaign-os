/**
 * Reading the refinement stage: the revision loop, and the versions it makes.
 *
 * ## Where "which version am I looking at" actually comes from
 *
 * Not from `/creative`. That endpoint reads the creative graph's checkpoint,
 * and on a campaign that has been revised it reports the version the *gate*
 * approved — a live campaign here returns v2 while the approved plan is v3 and
 * every plate was built from v3. Showing that as "current" would not be a gap,
 * it would be a wrong number.
 *
 * The version facts this module uses are the ones that cannot disagree with
 * each other, because each is stamped on the row it describes:
 *
 * - `GenerationView.specification_version` — the plan generation is working from;
 * - `GeneratedAssetView.specification_version` — the plan a plate was built from;
 * - `GuardianResultView.specification_version` — the plan a check judged against;
 * - `RevisionRecordView.from_version` / `to_version` — the step a revision made.
 *
 * ## What is deliberately absent
 *
 * **No author, anywhere.** `SpecificationRevisionRow` has no `requested_by`
 * and the API projects none, so a version says "Revision recorded" and never a
 * name. Inventing one on an audit surface would be the worst place in the
 * product to invent anything.
 *
 * **No verdict a version did not receive.** A version's brand status is read
 * from guardian results actually stamped with that version. A version nobody
 * checked reports that it was not checked — never a pass, and never a failure.
 */

import type {
  CampaignSpecification,
  CreativeSpecification,
  EvaluationView,
  GeneratedAssetView,
  GenerationView,
  GuardianResultView,
  GuardianVerdict,
  GuardianView,
  RevisionAction,
  RevisionDeltaView,
  RevisionRecordView,
  RevisionStatus,
  RevisionView,
  FieldChangeView,
} from '@/lib/api';
import type { Tone } from '@/components/ui';
import { displayLanguage } from '@/lib/market';
import { verdictMeaning } from '@/lib/review';

// ------------------------------------------------------------------- labels

/**
 * A creative-plan field, in a marketer's words.
 *
 * The server's own label is `name.replace("_"," ").capitalize()`, which is
 * serviceable for most fields and leaks for a few: "Cta" is not a word, and
 * "Visual story" and "Concept" read as jargon without help. Only the entries
 * that genuinely improve are listed; anything unknown falls through to the
 * server's label, or to the de-underscored name when there is none — never to
 * a guess.
 */
const FIELD_LABEL: Record<string, string> = {
  cta: 'Call to action',
  cta_guidance: 'Call-to-action guidance',
  headline: 'Headline',
  headline_guidance: 'Headline guidance',
  subhead: 'Subhead',
  body_copy: 'Body copy',
  concept: 'The idea',
  visual_story: 'What the picture shows',
  emotional_angle: 'Emotional angle',
  visual_metaphor: 'Visual metaphor',
  composition: 'Composition',
  focal_point: 'Focal point',
  subject: 'Subject',
  environment: 'Setting',
  lighting: 'Lighting',
  camera: 'Camera',
  palette: 'Colour palette',
  color_direction: 'Colour direction',
  style_families: 'Style',
  mood: 'Mood',
  typography_guidance: 'Typography guidance',
  product_integration: 'How the product appears',
  people_guidance: 'People',
  brand_integration: 'How the brand appears',
  regional_cues: 'Local cues',
  negative_constraints: 'Things that must not appear',
  channel_copy: 'Per-channel copy',
};

export function fieldLabel(field: string, serverLabel?: string | null): string {
  if (FIELD_LABEL[field]) return FIELD_LABEL[field];
  if (serverLabel && serverLabel.trim()) return serverLabel;
  const spaced = field.replace(/_/g, ' ').trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : field;
}

// ------------------------------------------------------- the revision plan

export interface PlannedChange {
  field: string;
  label: string;
  action: RevisionAction;
  /** The planner's own sentence. Never paraphrased, never invented. */
  reason: string;
  before: string | null;
  after: string | null;
}

export interface RevisionPlan {
  /** Fields this revision leaves exactly as approved. */
  keep: { field: string; label: string }[];
  change: PlannedChange[];
  add: PlannedChange[];
  remove: PlannedChange[];
  /** One sentence: what the planner understood the feedback to mean. */
  interpretation: string;
  /** Why it proposed this. A short summary, never a reasoning trace. */
  rationale: string;
  /** Locks the feedback explicitly asked to open. */
  unlocks: { field: string; label: string }[];
  /** True when the plan touches nothing — a real outcome, not an error. */
  empty: boolean;
}

function planned(rows: readonly FieldChangeView[]): PlannedChange[] {
  return rows.map((row) => ({
    field: row.field,
    label: fieldLabel(row.field, row.label),
    action: row.action,
    reason: row.reason,
    before: row.current_value,
    after: row.new_value,
  }));
}

export function revisionPlan(delta: RevisionDeltaView): RevisionPlan {
  const change = planned(delta.change);
  const add = planned(delta.add);
  const remove = planned(delta.remove);
  return {
    keep: delta.keep.map((field) => ({ field, label: fieldLabel(field) })),
    change,
    add,
    remove,
    interpretation: delta.interpretation,
    rationale: delta.rationale,
    unlocks: delta.explicit_unlocks.map((field) => ({ field, label: fieldLabel(field) })),
    empty: change.length + add.length + remove.length === 0,
  };
}

/** How an action reads, and how it is toned. Never colour alone — the word is
 *  always rendered beside it. */
export const ACTION_MEANING: Record<RevisionAction, { label: string; tone: Tone }> = {
  KEEP: { label: 'Keeping', tone: 'neutral' },
  CHANGE: { label: 'Changing', tone: 'caution' },
  ADD: { label: 'Adding', tone: 'positive' },
  REMOVE: { label: 'Removing', tone: 'negative' },
};

// ------------------------------------------------------------ where we are

export interface RevisionStatusMeaning {
  label: string;
  tone: Tone;
  /** True when nothing moves until a person decides. */
  awaitsHuman: boolean;
}

/**
 * The four revision states, in the user's language.
 *
 * `APPLIED` is the one worth naming carefully: the delta has been turned into
 * a new specification version, but nobody has accepted it yet. "Applied" reads
 * as finished and it is not.
 */
const REVISION_STATUS: Record<RevisionStatus, RevisionStatusMeaning> = {
  PROPOSED: { label: 'Plan awaiting your approval', tone: 'caution', awaitsHuman: true },
  APPLIED: { label: 'Revised plan awaiting your approval', tone: 'caution', awaitsHuman: true },
  APPROVED: { label: 'Approved', tone: 'positive', awaitsHuman: false },
  REJECTED: { label: 'Discarded', tone: 'neutral', awaitsHuman: false },
};

export function revisionStatusMeaning(status: RevisionStatus): RevisionStatusMeaning {
  return (
    REVISION_STATUS[status] ?? {
      label: String(status).toLowerCase().replace(/_/g, ' '),
      tone: 'neutral' as Tone,
      awaitsHuman: false,
    }
  );
}

export type RefinementStep = 'feedback' | 'plan' | 'revised' | 'regenerate' | 'blocked';

export interface RefinementState {
  step: RefinementStep;
  /** The heading sentence for the stage. */
  headline: string;
  /** What happens after the thing in front of the user. */
  next: string | null;
  /** True when a new round of feedback may be started. */
  canStartRound: boolean;
}

/**
 * Where the loop stands, and what follows.
 *
 * The chain is feedback → plan → revised plan → **regenerate** → brand check,
 * and the last two are the point: approving a revision does not produce a
 * visual and does not carry the previous version's brand verdict with it. The
 * copy here says so at every step, because a screen that stopped at "approved"
 * would imply both.
 */
export function refinementState(view: RevisionView): RefinementState {
  const current = view.current;
  if (!view.can_revise && !current) {
    return {
      step: 'blocked',
      headline: view.blocked_reason ?? 'Refinement is not open yet.',
      next: null,
      canStartRound: false,
    };
  }
  if (current?.status === 'PROPOSED') {
    return {
      step: 'plan',
      headline: 'Read the plan before it runs.',
      next: 'Approving it writes a new version of the creative plan. Nothing is generated yet.',
      canStartRound: false,
    };
  }
  if (current?.status === 'APPLIED') {
    return {
      step: 'revised',
      headline: `Creative plan v${current.to_version ?? current.from_version + 1} is ready to read.`,
      next: 'Approving it makes this the plan the campaign works from.',
      canStartRound: false,
    };
  }
  if (current?.status === 'APPROVED') {
    return {
      step: 'regenerate',
      headline: `Creative plan v${current.to_version ?? current.from_version + 1} is approved.`,
      // The two facts a person most needs and is least likely to assume.
      next: 'Nothing has been generated from it yet, and it has not been brand-checked.',
      canStartRound: true,
    };
  }
  return {
    step: 'feedback',
    headline: 'Describe what you would change.',
    next: 'Campaign OS turns it into a plan you approve before anything runs.',
    canStartRound: true,
  };
}

// --------------------------------------------------------------- protection

export interface ProtectedGroup {
  title: string;
  /** Why these are protected, in one sentence. */
  detail: string;
  items: { field: string; label: string }[];
}

/**
 * What a revision does not get to touch, from what the backend actually says.
 *
 * Three real sources, and no fourth invented one:
 *
 * - `delta.keep` — the fields *this* revision preserved. Per-revision truth.
 * - `specification.locked_fields` — standing locks. Populated by
 *   `apply_revision`, so a plan that has never been revised carries none; an
 *   empty list therefore renders nothing rather than a reassuring fiction.
 * - `delta.explicit_unlocks` — locks the feedback asked to open, shown because
 *   a protection that was lifted is exactly what a reader must not miss.
 */
export function protectedFields(
  delta: RevisionDeltaView | null,
  specification: CreativeSpecification | null,
): ProtectedGroup[] {
  const groups: ProtectedGroup[] = [];
  const unlocked = new Set(delta?.explicit_unlocks ?? []);

  const locks = (specification?.locked_fields ?? []).filter((f) => !unlocked.has(f));
  if (locks.length) {
    groups.push({
      title: 'Locked by Campaign OS',
      detail:
        'Approved facts a revision may not rewrite unless your feedback asks for it outright.',
      items: locks.map((field) => ({ field, label: fieldLabel(field) })),
    });
  }

  // A locked field is usually also in `keep`, and listing it twice reads as
  // two separate protections rather than one fact stated once. The stronger
  // statement wins: "locked" says it could not have changed, "kept" only says
  // it did not.
  const alreadyLocked = new Set(locks);
  const keep = (delta?.keep ?? []).filter((f) => !unlocked.has(f) && !alreadyLocked.has(f));
  if (keep.length) {
    groups.push({
      title: 'Kept exactly as approved',
      detail: 'This revision leaves these untouched.',
      items: keep.map((field) => ({ field, label: fieldLabel(field) })),
    });
  }

  if (unlocked.size) {
    groups.push({
      title: 'Unlocked because you asked',
      detail: 'Your feedback named these outright, so the lock was lifted for this revision.',
      items: [...unlocked].map((field) => ({ field, label: fieldLabel(field) })),
    });
  }
  return groups;
}

// ------------------------------------------------------------ localization

export interface LocalizationContext {
  rows: { label: string; value: string }[];
  /** Constraints the market puts on the work, where the brief states any. */
  required: string[];
  restricted: string[];
  /** False when the brief records no market context at all. */
  known: boolean;
}

/**
 * The market context a revision does not move.
 *
 * Read from the **campaign** specification, which a revision never edits — a
 * revision writes a `CreativeSpecification`, and region, language and audience
 * live on the `CampaignBrief`. That is why the claim "the market did not
 * change" is safe to make: it is structurally true, not merely observed.
 *
 * Absent values are omitted rather than filled in. A brief with no region
 * produces no region row.
 */
export function localizationContext(
  specification: CampaignSpecification | null,
): LocalizationContext {
  const rows: { label: string; value: string }[] = [];
  const push = (label: string, value: string | null | undefined) => {
    if (value && value.trim()) rows.push({ label, value: value.trim() });
  };
  push('Market', specification?.region ?? null);
  // `displayLanguage`, not the raw field: the brief stores ISO codes as well
  // as prose, and "en" is not a language to a reader.
  push('Language', displayLanguage(specification?.language ?? null));
  push('Audience', specification?.audience ?? null);
  push('Timing', specification?.timing_occasion ?? null);
  const required = specification?.required_elements ?? [];
  const restricted = specification?.avoid_restrictions ?? [];
  return {
    rows,
    required,
    restricted,
    known: rows.length > 0 || required.length > 0 || restricted.length > 0,
  };
}

// --------------------------------------------------------------- versions

export interface VersionEntry {
  version: number;
  /** The revision that produced this version, when one did. v1 has none. */
  revision: RevisionRecordView | null;
  /** What this version changed, in the reader's words. Empty for the first. */
  summary: string | null;
  /** Plates actually built from this version. May legitimately be empty. */
  assets: GeneratedAssetView[];
  /** Brand verdicts stamped with this version. Empty means "not checked". */
  verdicts: GuardianVerdict[];
  /** True for the plan generation is currently working from. */
  current: boolean;
  createdAt: string | null;
}

function summarise(record: RevisionRecordView | null): string | null {
  if (!record) return null;
  const plan = revisionPlan(record.delta);
  const touched = [...plan.change, ...plan.add, ...plan.remove];
  if (!touched.length) return record.delta.interpretation || null;
  // The fields themselves, because "3 fields changed" tells a reader nothing
  // they can act on.
  const names = touched.map((c) => c.label);
  const shown = names.slice(0, 3).join(', ');
  return names.length > 3 ? `${shown} and ${names.length - 3} more` : shown;
}

/**
 * Every plan version this campaign actually has, oldest first.
 *
 * Assembled from rows that each stamp their own version, so a version appears
 * because something real carries its number — a revision step, a plate, or a
 * brand check — and never because a gap in the sequence implied one.
 */
export function versionTimeline(
  revision: RevisionView | null,
  guardian: GuardianView | null,
  generation: GenerationView | null,
  evaluation: EvaluationView | null,
): VersionEntry[] {
  const records = new Map<number, RevisionRecordView>();
  const created = new Map<number, string>();
  const versions = new Set<number>();

  const history = [...(revision?.history ?? [])];
  if (revision?.current && !history.some((r) => r.id === revision.current?.id)) {
    history.push(revision.current);
  }
  for (const record of history) {
    versions.add(record.from_version);
    if (record.to_version !== null) {
      versions.add(record.to_version);
      records.set(record.to_version, record);
      created.set(record.to_version, record.created_at);
    }
  }

  // Assets can come from either surface: generation returns the latest batch,
  // while evaluation and the guardian still hold plates from earlier versions.
  const assets = new Map<string, GeneratedAssetView>();
  for (const asset of generation?.assets ?? []) assets.set(asset.id, asset);
  for (const row of evaluation?.ranked ?? []) if (row.asset) assets.set(row.asset.id, row.asset);
  for (const row of guardian?.results ?? []) if (row.asset) assets.set(row.asset.id, row.asset);
  for (const asset of assets.values()) versions.add(asset.specification_version);

  for (const row of guardian?.results ?? []) versions.add(row.specification_version);
  if (generation?.specification_version != null) versions.add(generation.specification_version);

  const currentVersion = generation?.specification_version ?? Math.max(...versions, 0);

  return [...versions]
    .filter((v) => Number.isFinite(v) && v > 0)
    .sort((a, b) => a - b)
    .map((version) => {
      const record = records.get(version) ?? null;
      return {
        version,
        revision: record,
        summary: summarise(record),
        assets: [...assets.values()].filter((a) => a.specification_version === version),
        verdicts: (guardian?.results ?? [])
          .filter((r) => r.specification_version === version && r.verdict !== null)
          .map((r) => r.verdict as GuardianVerdict),
        current: version === currentVersion,
        createdAt: created.get(version) ?? null,
      };
    });
}

export interface VersionBrandStatus {
  label: string;
  tone: Tone;
  /** True when no check has ever been stamped with this version. */
  unchecked: boolean;
}

/**
 * A version's brand standing, from checks stamped with that version alone.
 *
 * A revision never inherits the previous version's verdict: a new plan is a new
 * thing to check, and carrying a pass forward is the one claim this screen must
 * never make.
 */
export function versionBrandStatus(entry: VersionEntry): VersionBrandStatus {
  if (!entry.verdicts.length) {
    return { label: 'Not brand-checked', tone: 'neutral', unchecked: true };
  }
  const worst: GuardianVerdict | undefined =
    entry.verdicts.find((v) => v === 'REJECT') ??
    entry.verdicts.find((v) => v === 'NEEDS_REVISION') ??
    entry.verdicts.find((v) => v === 'UNKNOWN') ??
    entry.verdicts[0];
  const meaning = worst ? verdictMeaning(worst) : null;
  return {
    label: meaning?.label ?? 'Not brand-checked',
    tone: meaning?.tone ?? 'neutral',
    unchecked: false,
  };
}

// -------------------------------------------------------------- comparison

export interface VersionComparison {
  from: VersionEntry;
  to: VersionEntry;
  /** Fields the revision between them actually changed. */
  changed: PlannedChange[];
  /** Fields it explicitly kept. */
  stayed: { field: string; label: string }[];
  /**
   * Brand standing on each side. Null where that version was never checked —
   * which is a different statement from "it failed".
   */
  brand: { from: VersionBrandStatus; to: VersionBrandStatus };
}

/**
 * Two versions, and the revision between them.
 *
 * Only defined for adjacent versions joined by a revision record: that record
 * is the only thing that knows what changed and why. Comparing v1 with v3
 * would need a diff nobody computed, so it is not offered.
 */
export function compareVersions(
  from: VersionEntry,
  to: VersionEntry,
): VersionComparison | null {
  const record = to.revision;
  if (!record || record.from_version !== from.version) return null;
  const plan = revisionPlan(record.delta);
  return {
    from,
    to,
    changed: [...plan.change, ...plan.add, ...plan.remove],
    stayed: plan.keep,
    brand: { from: versionBrandStatus(from), to: versionBrandStatus(to) },
  };
}

/** The plate a comparison should show for a side, or null when it has none. */
export function representativeAsset(
  entry: VersionEntry,
  preferredId: string | null,
): GeneratedAssetView | null {
  if (preferredId) {
    const preferred = entry.assets.find((a) => a.id === preferredId);
    if (preferred) return preferred;
  }
  return entry.assets[0] ?? null;
}
