/**
 * Reading the review stages: evaluation and the brand check.
 *
 * ## What the backend does and does not score
 *
 * Ten real dimensions come back, each with a label, an integer 0-100, a
 * one-sentence note and its share of the total. There is **no "message fit"
 * dimension and no risk score** — the brief asked for both and neither exists,
 * so neither appears. The closest real material is `concerns[]`, the model's
 * own words about what is wrong with a plate, and it is shown as exactly that.
 *
 * The model never supplies the overall score or the disposition: both are
 * computed by the service from the published weights and thresholds, and
 * `disposition_reasons` states the rule that fired in words. That chain is the
 * product's claim to being inspectable, so the screen shows it rather than a
 * bare verdict.
 */

import type {
  Disposition,
  EvaluationDetailView,
  GuardianCheckView,
  GuardianVerdict,
  CheckStatus,
} from '@/lib/api';
import type { Tone } from '@/components/ui';

// ------------------------------------------------------------- evaluation

export interface DispositionMeaning {
  label: string;
  tone: Tone;
  detail: string;
}

/**
 * Note the vocabulary trap: evaluation's `NEEDS_REVIEW` is not the guardian's
 * `NEEDS_REVISION`. They are different enums on different surfaces and mean
 * different things — one asks a person to look, the other asks for a rewrite.
 */
const DISPOSITION: Record<Disposition, DispositionMeaning> = {
  PASS: {
    label: 'Ready for review',
    tone: 'positive',
    detail: 'Scored above the threshold with no weak critical dimension.',
  },
  NEEDS_REVIEW: {
    label: 'Needs attention',
    tone: 'caution',
    detail: 'Good enough to consider, but something scored low enough to look at.',
  },
  REJECT: {
    label: 'Not usable',
    tone: 'negative',
    detail: 'Scored below the threshold, or failed a dimension that cannot be weak.',
  },
};

export function dispositionMeaning(d: Disposition | null): DispositionMeaning | null {
  return d ? DISPOSITION[d] : null;
}

/**
 * A dimension's name, for a reader.
 *
 * The server's `label` is mechanical — `dimension.replace('_',' ').capitalize()`
 * — which is fine for nine of the ten and leaks internal vocabulary for one:
 * "Plate readiness" uses the schema's word for a raw model output. Only that
 * one is renamed, and anything unrecognised falls through to the server's own
 * label rather than being guessed at.
 */
const DIMENSION_LABEL: Record<string, string> = {
  plate_readiness: 'Ready to build on',
};

export function dimensionLabel(dimension: string, serverLabel: string): string {
  return DIMENSION_LABEL[dimension] ?? serverLabel;
}

/**
 * How a score reads without a colour.
 *
 * The bands are the product's own reading of a 0-100 number, not a backend
 * threshold — the backend publishes thresholds for the *overall* score and for
 * critical floors, not per dimension. So this is deliberately coarse and is
 * never presented as a verdict on the dimension.
 */
export function scoreBand(score: number): { label: string; tone: Tone } {
  if (score >= 75) return { label: 'Strong', tone: 'positive' };
  if (score >= 55) return { label: 'Adequate', tone: 'neutral' };
  return { label: 'Weak', tone: 'caution' };
}

export interface EvaluationSummary {
  /** Null for any row that is not COMPLETED — not zero. */
  score: number | null;
  disposition: DispositionMeaning | null;
  /** True when the row never produced a judgement at all. */
  unjudged: boolean;
  /** Why it produced none, when it failed. */
  failure: string | null;
  canRetry: boolean;
}

/**
 * A failed evaluation is not a low score.
 *
 * `status` is the field that separates "not judged" from "judged badly", and
 * conflating them is how a plate nobody scored comes to look like a bad one.
 */
export function summarise(detail: EvaluationDetailView): EvaluationSummary {
  const done = detail.status === 'COMPLETED';
  return {
    score: done ? detail.overall_score : null,
    disposition: done ? dispositionMeaning(detail.disposition) : null,
    unjudged: !done,
    failure: detail.status === 'FAILED' ? (detail.error_message ?? 'The evaluation failed.') : null,
    canRetry: detail.can_retry,
  };
}

// ---------------------------------------------------------------- guardian

export interface CheckMeaning {
  label: string;
  tone: Tone;
}

const CHECK_STATUS: Record<CheckStatus, CheckMeaning> = {
  PASS: { label: 'Passed', tone: 'positive' },
  WARN: { label: 'Worth a look', tone: 'caution' },
  FAIL: { label: 'Failed', tone: 'negative' },
  NOT_APPLICABLE: { label: 'Not applicable', tone: 'neutral' },
};

export function checkMeaning(status: string): CheckMeaning {
  return (
    CHECK_STATUS[status as CheckStatus] ?? {
      label: status.replace(/_/g, ' ').toLowerCase(),
      tone: 'neutral' as Tone,
    }
  );
}

const VERDICT: Record<GuardianVerdict, { label: string; tone: Tone; detail: string }> = {
  PASS: {
    label: 'Within the brand’s rules',
    tone: 'positive',
    detail: 'Nothing checked contradicts what the brand allows.',
  },
  NEEDS_REVISION: {
    label: 'Needs changes',
    tone: 'caution',
    detail: 'Something has to change before this can ship against this brand.',
  },
  REJECT: {
    label: 'Cannot ship',
    tone: 'negative',
    detail: 'This work breaks a brand rule that is not negotiable.',
  },
  UNKNOWN: {
    label: 'No verdict',
    tone: 'neutral',
    detail: 'The checks did not produce a verdict.',
  },
};

export function verdictMeaning(v: GuardianVerdict | null) {
  return v ? VERDICT[v] : null;
}

/**
 * Why a check matters.
 *
 * **This is the product's own explanation, not the model's.** The backend has
 * no "why it matters" field — `CHECK_GUIDANCE` exists server-side but is used
 * only to build the model prompt and is never projected — so these are fixed
 * sentences about fixed check types, written here and clearly ours. An
 * unrecognised check id gets nothing rather than a generic platitude.
 *
 * They are shown under a heading that attributes them to Campaign OS, never
 * beside the model's `detail` as though the model said them.
 */
const WHY_IT_MATTERS: Record<string, string> = {
  claim_safety:
    'A prohibited claim in a campaign is a legal and regulatory exposure, not a style problem.',
  brand_restrictions:
    'These are the things the brand has said it will not show. Breaking one undoes the brand’s own positioning.',
  color_constraints:
    'Colour is how a brand is recognised before anything is read.',
  brand_tone:
    'Tone is what makes the work sound like this brand rather than any other.',
  visual_identity:
    'Consistency across campaigns is what makes a brand feel like one thing.',
  product_representation:
    'A product shown wrongly misleads the buyer and the sales team both.',
  logo_readiness:
    'The logo has to survive the composition step at every channel size.',
  policy_compliance:
    'Platform policy decides whether the campaign can run at all.',
};

export function whyItMatters(check: string): string | null {
  return WHY_IT_MATTERS[check] ?? null;
}

/** Checks that need a human to look, first; then the rest in backend order. */
export function orderChecks(checks: readonly GuardianCheckView[]): GuardianCheckView[] {
  const rank = (c: GuardianCheckView) =>
    c.status === 'FAIL' ? 0 : c.status === 'WARN' ? 1 : c.status === 'PASS' ? 2 : 3;
  return [...checks].sort((a, b) => rank(a) - rank(b));
}

/** How many checks did what — counted, never estimated. */
export function checkTally(checks: readonly GuardianCheckView[]) {
  return {
    total: checks.length,
    passed: checks.filter((c) => c.status === 'PASS').length,
    warned: checks.filter((c) => c.status === 'WARN').length,
    failed: checks.filter((c) => c.status === 'FAIL').length,
    notApplicable: checks.filter((c) => c.status === 'NOT_APPLICABLE').length,
    /** Checks decided by code rather than by a model. */
    deterministic: checks.filter((c) => c.deterministic).length,
  };
}
