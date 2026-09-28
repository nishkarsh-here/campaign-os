'use client';

/**
 * THE CAMPAIGN SNAPSHOT — the brief, filling in as it is discovered.
 *
 * The discovery screen used to show a completeness rail: a list of field names
 * and a count. This shows the brief itself, growing. A person answering
 * questions can watch the thing they are building take shape, and can see what
 * is still missing — which is the actual reason anyone tolerates an interview.
 *
 * ## It renders a confirmed brief too
 *
 * A confirmed campaign cannot reopen discovery: `POST /discovery/start` answers
 * 409, so there is no `DiscoveryTurn` and therefore no `CampaignInputs`. Every
 * seeded benchmark campaign is in exactly that state, and the screen used to
 * show them nothing at all — the brief the entire pipeline is built from was
 * invisible on its own page. `fromSpecification` adapts the confirmed
 * `CampaignSpecification` into the same shape so there is one rendering path
 * for both, rather than a second panel that can disagree with this one.
 *
 * ## Provenance is the point
 *
 * `assertions` records, per field, an `availability`
 * (known / unknown / not_applicable) and a `certainty`
 * (stated / brand_default / inferred / unresolved). Those map to words a
 * marketer can act on:
 *
 *   stated        -> "Provided by you"  — you said it; we did not decide it
 *   brand_default -> "From brand"        — taken from the Brand Brain
 *   inferred      -> "AI inferred"       — a guess worth confirming
 *   unresolved    -> "Still open"        — asked about, never settled
 *
 * A field whose `availability` is `not_applicable` is *answered*, not missing:
 * someone said it does not apply. Reporting that as "Still needed" would ask
 * them the same question for ever.
 *
 * Every value is read from real state. A field with no value says "Still
 * needed" and stays visibly unresolved — no percentage standing in for the list
 * of things nobody has answered.
 */

import { Card, cx } from '@/components/ui';
import type { CampaignInputs, CampaignSpecification, FieldAssertion } from '@/lib/api';

/** What a certainty means to the person reading it. */
const PROVENANCE: Record<string, { label: string; tone: string; meaning: string }> = {
  stated: { label: 'Provided by you', tone: 'text-success', meaning: 'You said this outright.' },
  brand_default: {
    label: 'From brand',
    tone: 'text-info',
    meaning: 'Taken from the Brand Brain rather than asked for again.',
  },
  inferred: {
    label: 'AI inferred',
    tone: 'text-warning',
    meaning: 'Read from what you said. Worth confirming.',
  },
  unresolved: {
    label: 'Still open',
    tone: 'text-muted',
    meaning: 'Raised in the conversation but never settled.',
  },
};

/**
 * The brief's questions, in the reader's words.
 *
 * `keys` lists every name the assertion for this row might be filed under.
 * `field_assertions` genuinely mixes both vocabularies — a real specification
 * carries `campaign_objective` *and* `audience` *and* `target_audience` — so a
 * single-name lookup silently finds nothing for half the rows and the
 * provenance badge never appears. Trying each known alias is the fix.
 *
 * The set covers every field the interview actually asks about. A row that is
 * missing here would let the snapshot say "2 still needed" while the next three
 * questions are about fields it never showed.
 */
const ROWS: {
  label: string;
  keys: string[];
  read: (v: Snapshotable) => string | null;
}[] = [
  { label: 'Objective', keys: ['campaign_objective', 'objective'], read: (v) => v.objective },
  { label: 'Product', keys: ['product'], read: (v) => v.product },
  { label: 'Audience', keys: ['target_audience', 'audience'], read: (v) => v.audience },
  { label: 'Market', keys: ['region'], read: (v) => v.region },
  { label: 'Message', keys: ['key_message'], read: (v) => v.key_message },
  { label: 'Call to action', keys: ['cta'], read: (v) => v.cta },
  { label: 'Offer', keys: ['key_offer'], read: (v) => v.key_offer },
  { label: 'Timing', keys: ['timing_occasion'], read: (v) => v.timing_occasion },
  { label: 'Tone', keys: ['campaign_tone', 'tone'], read: (v) => join(v.tone) },
  { label: 'Channels', keys: ['channels'], read: (v) => join(v.channels) },
  {
    label: 'Constraints',
    keys: ['avoid_restrictions', 'required_elements'],
    read: (v) => join([...v.required, ...v.avoid]),
  },
];

/** The shape both a draft and a confirmed brief reduce to. */
interface Snapshotable {
  objective: string | null;
  product: string | null;
  audience: string | null;
  region: string | null;
  key_message: string | null;
  cta: string | null;
  key_offer: string | null;
  timing_occasion: string | null;
  tone: string[];
  channels: string[];
  required: string[];
  avoid: string[];
  assertions: Record<string, FieldAssertion>;
}

export function fromInputs(inputs: CampaignInputs): Snapshotable {
  return {
    objective: inputs.campaign_objective,
    product: inputs.product,
    audience: inputs.target_audience,
    region: inputs.region,
    key_message: inputs.key_message,
    cta: inputs.cta,
    key_offer: inputs.key_offer,
    timing_occasion: inputs.timing_occasion,
    tone: inputs.campaign_tone,
    channels: inputs.channels,
    required: inputs.required_elements,
    avoid: inputs.avoid_restrictions,
    assertions: inputs.assertions ?? {},
  };
}

export function fromSpecification(spec: CampaignSpecification): Snapshotable {
  return {
    objective: spec.objective,
    product: spec.product,
    audience: spec.audience,
    region: spec.region,
    key_message: spec.key_message,
    cta: spec.cta,
    key_offer: spec.key_offer,
    timing_occasion: spec.timing_occasion,
    tone: spec.campaign_tone.length > 0 ? spec.campaign_tone : spec.tone,
    channels: spec.channels,
    required: spec.required_elements,
    avoid: spec.avoid_restrictions,
    assertions: spec.field_assertions ?? {},
  };
}

function join(values: string[] | null | undefined): string | null {
  if (!values || values.length === 0) return null;
  return values.join(' · ');
}

export function CampaignSnapshot({
  brief,
  /** Field names the interview still wants, from `DiscoveryTurn.missing`. */
  missing = [],
  /** The one field being asked right now, from `DiscoveryTurn.question.field`. */
  asking = null,
  complete,
  /** True when the brief is confirmed — nothing here is outstanding any more. */
  confirmed = false,
}: {
  brief: Snapshotable;
  missing?: string[];
  asking?: string | null;
  complete: boolean;
  confirmed?: boolean;
}) {
  const resolved = ROWS.map((row) => {
    const value = row.read(brief);
    // First alias that has an assertion wins; see the note on `keys`.
    const assertion = row.keys.map((k) => brief.assertions[k]).find(Boolean);
    return { ...row, value, assertion };
  });

  // A field someone marked not-applicable is answered, not outstanding.
  const outstanding = resolved.filter(
    (r) => !r.value && r.assertion?.availability !== 'not_applicable',
  );

  return (
    <Card padding={false} className="h-full">
      <div className="flex flex-wrap items-baseline justify-between gap-2 px-5 pt-5">
        <h3 className="text-h3">Campaign snapshot</h3>
        <p className="text-label uppercase text-muted">
          {confirmed
            ? 'Confirmed'
            : complete || outstanding.length === 0
              ? 'All answered'
              : `${outstanding.length} still needed`}
        </p>
      </div>
      <p className="mt-1 px-5 text-caption text-muted">
        {confirmed
          ? 'The approved brief. Everything downstream is built from this.'
          : 'The brief as it stands. It fills in as you answer.'}
      </p>

      <dl className="mt-4 divide-y divide-line border-t border-line">
        {resolved.map((row) => (
          <SnapshotRow
            key={row.label}
            label={row.label}
            value={row.value}
            assertion={row.assertion}
            asked={!confirmed && row.keys.some((k) => k === asking)}
            outstanding={!confirmed && row.keys.some((k) => missing.includes(k))}
          />
        ))}
      </dl>
    </Card>
  );
}

function SnapshotRow({
  label,
  value,
  assertion,
  asked,
  outstanding,
}: {
  label: string;
  value: string | null;
  assertion: FieldAssertion | undefined;
  /** True only for the single field the interview is asking about now. */
  asked: boolean;
  /** True when the interview still wants this one. */
  outstanding: boolean;
}) {
  const notApplicable = !value && assertion?.availability === 'not_applicable';
  // Provenance only means something once there is something to explain. An
  // assertion on an empty field is a gap, not a source — except when it records
  // that the field deliberately does not apply.
  const provenance = value && assertion ? PROVENANCE[assertion.certainty] : undefined;

  return (
    <div className={cx('px-5 py-3', !value && !notApplicable && 'bg-line/10')}>
      <dt className="flex flex-wrap items-center gap-2">
        <span className="text-label uppercase text-muted">{label}</span>
        {provenance ? (
          <span title={provenance.meaning} className={cx('text-label uppercase', provenance.tone)}>
            {provenance.label}
          </span>
        ) : null}
        {assertion?.edited_by_human ? (
          // A human edit is never overwritten by recompilation (CLAUDE.md,
          // Milestone 3). Worth saying: it changes what happens next.
          <span className="text-label uppercase text-success">Edited by you</span>
        ) : null}
      </dt>
      <dd className="mt-1">
        {value ? (
          <span className="text-small text-ink">{value}</span>
        ) : notApplicable ? (
          <span className="text-small text-muted">Not applicable</span>
        ) : (
          <span className={cx('text-small', asked ? 'text-accent' : 'text-muted')}>
            {/* The accent marks the one field being asked *now* — from
                `question.field`, not from `missing`, which is every remaining
                field and would light the whole column. */}
            {asked ? 'Being asked now' : outstanding ? 'Still needed' : 'Not answered'}
          </span>
        )}
      </dd>
    </div>
  );
}
