'use client';

/**
 * BRAND CORE — the intelligence layer behind the campaign.
 *
 * The Brand Brain page used to open with a document-upload panel and a table of
 * facts, which reads as a filing system. What it actually holds is the thing
 * every campaign is written from, and its most important property is *how much
 * of it is confirmed*. So the page now opens with that.
 *
 * ## The trichotomy is real
 *
 * `BrandBrain.field_status[]` carries a `knowledge` of `known`, `inferred` or
 * `unknown` per field, and `proposed_facts[]` carries facts a model put forward
 * that no human has accepted yet. That is the architecture showing through:
 * only a person accepting a fact makes it brand truth (CLAUDE.md, Milestone 2).
 * Nothing here computes its own opinion of confidence — it counts what the
 * backend already decided.
 */

import Link from 'next/link';
import { Card, Reveal, StatusBadge, buttonStyles, cx } from '@/components/ui';
import { statusMeaning } from '@/lib/campaign-status';
import type { Brand, BrandBrain, FieldStatus } from '@/lib/api';

type Knowledge = FieldStatus['knowledge'];

const KNOWLEDGE: Record<Knowledge, { label: string; blurb: string; tone: string }> = {
  known: {
    label: 'Confirmed',
    blurb: 'A person asserted or accepted this. Campaigns may rely on it.',
    tone: 'text-success',
  },
  inferred: {
    label: 'Inferred',
    blurb: 'Read from a document but not yet confirmed by anyone.',
    tone: 'text-warning',
  },
  unknown: {
    label: 'Not known',
    blurb: 'Nothing has told us this yet.',
    tone: 'text-muted',
  },
};

/** Field names are schema paths; this is the reader's version. */
function fieldLabel(field: string): string {
  return field.replace(/_/g, ' ').replace(/\./g, ' · ');
}

export function BrandCore({ brain }: { brain: BrandBrain }) {
  const { brand, field_status: fields } = brain;
  const pending = brain.proposed_facts.filter((f) => f.status === 'proposed');

  const counts: Record<Knowledge, FieldStatus[]> = {
    known: fields.filter((f) => f.knowledge === 'known'),
    inferred: fields.filter((f) => f.knowledge === 'inferred'),
    unknown: fields.filter((f) => f.knowledge === 'unknown'),
  };

  return (
    <section aria-labelledby="brand-core" className="space-y-lg">
      <h2 id="brand-core" className="sr-only">
        Brand core
      </h2>

      {/* ------------------------------------------------- what is confirmed */}
      <Card>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h3 className="text-h3">What this brand knows about itself</h3>
          <p className="text-label uppercase text-muted">
            {fields.length} {fields.length === 1 ? 'field' : 'fields'} tracked
          </p>
        </div>

        {/* A proportional bar, not a pie or a percentage: the three widths are
            the three counts, and the numbers are printed beside it so the bar
            is never the only way to read the split. */}
        {fields.length > 0 ? (
          <div
            className="mt-4 flex h-1.5 overflow-hidden rounded-full bg-line/50"
            role="img"
            aria-label={`${counts.known.length} confirmed, ${counts.inferred.length} inferred, ${counts.unknown.length} not known`}
          >
            {(['known', 'inferred', 'unknown'] as const).map((kind) =>
              counts[kind].length > 0 ? (
                <span
                  key={kind}
                  style={{ width: `${(counts[kind].length / fields.length) * 100}%` }}
                  className={
                    kind === 'known'
                      ? 'bg-success'
                      : kind === 'inferred'
                        ? 'bg-warning'
                        : 'bg-line'
                  }
                />
              ) : null,
            )}
          </div>
        ) : null}

        <dl className="mt-5 grid gap-5 sm:grid-cols-3">
          {(['known', 'inferred', 'unknown'] as const).map((kind) => (
            <div key={kind}>
              <dt className={cx('text-label uppercase', KNOWLEDGE[kind].tone)}>
                {KNOWLEDGE[kind].label}
              </dt>
              <dd className="mt-1 text-h2 tabular-nums">{counts[kind].length}</dd>
              <dd className="mt-1 text-caption text-muted">{KNOWLEDGE[kind].blurb}</dd>
            </div>
          ))}
        </dl>

        {/* The fields themselves, grouped. Confirmed first — that is the part
            a campaign can actually be written from. */}
        {(['known', 'inferred', 'unknown'] as const).map((kind) =>
          counts[kind].length > 0 ? (
            <div key={kind} className="mt-5 border-t border-line pt-4">
              <p className={cx('text-label uppercase', KNOWLEDGE[kind].tone)}>
                {KNOWLEDGE[kind].label}
              </p>
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {counts[kind].map((field) => (
                  <li
                    key={field.field}
                    className="rounded-sm border border-line bg-line/20 px-2 py-0.5 text-caption text-muted"
                  >
                    {fieldLabel(field.field)}
                    {/* The count of outstanding proposals for this field —
                        real, from `proposal_count`. */}
                    {field.knowledge === 'inferred' && field.proposal_count > 0
                      ? ` (${field.proposal_count})`
                      : ''}
                  </li>
                ))}
              </ul>
            </div>
          ) : null,
        )}

        {pending.length > 0 ? (
          <p className="mt-5 border-t border-line pt-4 text-body">
            <StatusBadge tone="caution">Needs you</StatusBadge>{' '}
            <span className="ml-1 text-muted">
              {pending.length} {pending.length === 1 ? 'fact is' : 'facts are'} waiting for
              someone to accept or reject {pending.length === 1 ? 'it' : 'them'}.
            </span>
          </p>
        ) : null}
      </Card>

      {/* ---------------------------------------------------------- identity */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Identity brand={brand} />
        <Voice brand={brand} />
        <VisualIdentity brand={brand} />
        <Claims brand={brand} />
      </div>
    </section>
  );
}

/**
 * A panel that states its own absence rather than vanishing.
 *
 * `isEmpty` is passed in rather than inferred from `children`. Inferring it
 * does not work: `Voice` always renders four child elements, each of which
 * decides internally to return null, so a truthiness test on `children` reports
 * content for a panel that draws nothing — which is precisely the blank box
 * this component exists to prevent. Only the caller, which holds the data, can
 * answer the question.
 */
function Panel({
  title,
  isEmpty,
  children,
  empty,
}: {
  title: string;
  isEmpty: boolean;
  children: React.ReactNode;
  /** Shown when the brand holds nothing for this panel. */
  empty: string;
}) {
  return (
    <Card className="h-full">
      <h3 className="text-h3">{title}</h3>
      {isEmpty ? (
        // Naming the gap is how a person knows to go and fill it. A panel that
        // disappears when empty reads as a feature that does not exist.
        <p className="mt-3 text-small text-muted">{empty}</p>
      ) : (
        <div className="mt-4 space-y-4">{children}</div>
      )}
    </Card>
  );
}

function Line({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div>
      <p className="text-label uppercase text-muted">{label}</p>
      <p className="mt-1 text-body">{value}</p>
    </div>
  );
}

function Chips({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) return null;
  return (
    <div>
      <p className="text-label uppercase text-muted">{label}</p>
      <ul className="mt-1.5 flex flex-wrap gap-1.5">
        {values.map((value) => (
          <li
            key={value}
            className="rounded-sm border border-line bg-line/20 px-2 py-0.5 text-caption"
          >
            {value}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Identity({ brand }: { brand: Brand }) {
  const isEmpty =
    !brand.positioning && !brand.mission && !brand.audience_description && brand.values.length === 0;
  return (
    <Panel
      title="Identity"
      isEmpty={isEmpty}
      empty="No positioning, mission or values recorded yet."
    >
      <Line label="Positioning" value={brand.positioning} />
      <Line label="Mission" value={brand.mission} />
      <Chips label="Values" values={brand.values} />
      <Line label="Audience" value={brand.audience_description} />
    </Panel>
  );
}

function Voice({ brand }: { brand: Brand }) {
  const { voice } = brand;
  const isEmpty =
    voice.tone_attributes.length === 0 &&
    !voice.person &&
    voice.writing_rules.length === 0 &&
    voice.avoid.length === 0;
  return (
    <Panel title="Voice" isEmpty={isEmpty} empty="No tone, rules or person recorded yet.">
      <Chips label="Tone" values={voice.tone_attributes} />
      <Line label="Person" value={voice.person} />
      <Chips label="Writing rules" values={voice.writing_rules} />
      <Chips label="Avoid" values={voice.avoid} />
    </Panel>
  );
}

function VisualIdentity({ brand }: { brand: Brand }) {
  const { typography } = brand;
  const isEmpty =
    brand.colors.length === 0 &&
    !typography.heading_font &&
    !typography.body_font &&
    !typography.notes &&
    brand.visual_dos.length === 0 &&
    brand.visual_donts.length === 0 &&
    brand.logo_rules.length === 0;
  return (
    <Panel
      title="Visual identity"
      isEmpty={isEmpty}
      empty="No palette or typeface recorded yet."
    >
      {brand.colors.length > 0 ? (
        <div>
          <p className="text-label uppercase text-muted">Palette</p>
          <ul className="mt-2 flex flex-wrap gap-3">
            {brand.colors.map((colour) => (
              <li key={colour.hex} className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className="h-6 w-6 rounded-sm border border-line"
                  style={{ background: colour.hex }}
                />
                <span className="text-caption">
                  {/* The hex is named as well as shown: a swatch alone is
                      unreadable to anyone who cannot see the colour. */}
                  <span className="block text-ink">{colour.name}</span>
                  <span className="block font-mono uppercase text-muted">{colour.hex}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <Line label="Heading typeface" value={typography.heading_font} />
      <Line label="Body typeface" value={typography.body_font} />
      <Line label="Typography notes" value={typography.notes} />
      <Chips label="Visual do" values={brand.visual_dos} />
      <Chips label="Visual don’t" values={brand.visual_donts} />
      <Chips label="Logo rules" values={brand.logo_rules} />
    </Panel>
  );
}

function Claims({ brand }: { brand: Brand }) {
  const isEmpty =
    brand.approved_claims.length === 0 &&
    brand.prohibited_claims.length === 0 &&
    !brand.legal_line;
  return (
    <Panel
      title="Claims"
      isEmpty={isEmpty}
      empty="No approved or prohibited claims recorded yet."
    >
      {brand.approved_claims.length > 0 ? (
        <div>
          <p className="text-label uppercase text-success">Approved</p>
          <ul className="mt-1.5 space-y-1.5">
            {brand.approved_claims.map((claim) => (
              <li key={claim} className="text-small">
                {claim}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {brand.prohibited_claims.length > 0 ? (
        <div>
          <p className="text-label uppercase text-danger">Prohibited</p>
          <ul className="mt-1.5 space-y-1.5">
            {brand.prohibited_claims.map((claim) => (
              <li key={claim} className="text-small">
                {claim}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <Line label="Legal line" value={brand.legal_line} />
    </Panel>
  );
}

// ------------------------------------------------------- campaigns using this

/**
 * Campaigns written from this brand.
 *
 * The audit found the brand page had no route to them at all — a dead end in a
 * product whose whole point is that campaigns come from brands. The list is the
 * organization's campaigns filtered by `brand_id`, which is a real field on
 * every campaign row; no new endpoint and no invented association.
 */
export function CampaignsUsingBrand({
  campaigns,
  loading,
}: {
  campaigns: { id: string; title: string; status: string }[];
  loading: boolean;
}) {
  return (
    <section aria-labelledby="brand-campaigns">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="brand-campaigns" className="text-h2">
          Campaigns using this brand
        </h2>
        {!loading ? (
          <p className="text-label uppercase text-muted">
            {campaigns.length} {campaigns.length === 1 ? 'campaign' : 'campaigns'}
          </p>
        ) : null}
      </div>

      <div className="mt-lg">
        {loading ? (
          <div className="h-16 animate-pulse rounded-lg border border-line bg-line/30" />
        ) : campaigns.length === 0 ? (
          <Card className="text-center">
            <p className="text-body text-muted">
              No campaign has been written from this brand yet.
            </p>
            <Link href="/app/campaigns" className={buttonStyles('secondary', 'md', 'mt-4')}>
              Start a campaign
            </Link>
          </Card>
        ) : (
          <Card padding={false}>
            <ul className="divide-y divide-line">
              {campaigns.map((campaign, i) => (
                <Reveal as="li" key={campaign.id} index={i}>
                  <Link
                    href={`/app/campaigns/${campaign.id}/overview`}
                    className="flex items-center justify-between gap-4 px-5 py-4 transition-colors duration-fast hover:bg-line/20"
                  >
                    <span className="min-w-0 truncate text-body font-medium">
                      {campaign.title}
                    </span>
                    {/* The reader's words, not the enum. "SPECIFICATION
                        CONFIRMED" is a database value; "Brief confirmed" is
                        what happened. */}
                    <StatusBadge tone={statusMeaning(campaign.status).tone}>
                      {statusMeaning(campaign.status).label}
                    </StatusBadge>
                  </Link>
                </Reveal>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </section>
  );
}
