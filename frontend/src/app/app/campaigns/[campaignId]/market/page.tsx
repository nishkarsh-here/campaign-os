'use client';

/**
 * LOCAL MARKET — why this campaign belongs where it runs.
 *
 * The product's defining layer, given its own destination. The command centre
 * shows a summary; this is the whole picture, and it is organised around one
 * question rather than around the shape of the data.
 *
 * Every fact is read from the campaign specification with the provenance the
 * specification's own `field_assertions` record — stated, from the brand,
 * inferred, or not known. Beside each one is what it *means for the creative*,
 * which is the part a marketer actually acts on and the part the old form field
 * never said.
 *
 * Nothing is invented. A campaign still in discovery shows five unknowns and an
 * explanation of where they come from, because that is the truth about it.
 */

import Link from 'next/link';
import {
  Card,
  EmptyState,
  Reveal,
  SectionHeader,
  SkeletonRows,
  buttonStyles,
  cx,
} from '@/components/ui';
import { useCampaignWorkspace } from '@/lib/campaign-context';
import {
  CONFIDENCE_LABEL,
  CONFIDENCE_MEANING,
  allUnrecorded,
  confidenceCaution,
  creativeImplication,
  hasMarket,
  localCues,
  marketFacts,
  type Confidence,
  type MarketFact,
} from '@/lib/market';

/** Colour *and* wording, so the marker is never the only signal. */
const TONE: Record<Confidence, string> = {
  stated: 'text-success',
  brand: 'text-info',
  inferred: 'text-warning',
  unrecorded: 'text-muted',
  unknown: 'text-muted',
};

export default function LocalMarketPage() {
  const { specification, overview, campaignId } = useCampaignWorkspace();

  // The layout resolves the specification best-effort. Null with no overview
  // means still arriving; null with an overview means the campaign genuinely
  // has no specification yet.
  if (!overview && !specification) return <SkeletonRows rows={4} />;

  const facts = marketFacts(specification);
  const { required, avoid } = localCues(specification);
  const known = hasMarket(facts);

  return (
    <div className="space-y-section">
      <header>
        <p className="text-label uppercase text-accent">Local market</p>
        <h2 className="mt-2 max-w-content text-h1">Why does this campaign belong here?</h2>
        <p className="mt-3 max-w-content text-body text-muted">
          A campaign that could run anywhere belongs nowhere. These are the facts that make
          this one local — and what each of them asks of the creative.
        </p>
      </header>

      {!known ? (
        <EmptyState
          title="No market decided yet"
          description="The place, the language and the season are settled in the brief. Once they are, they appear here with what they mean for the work."
          action={
            <Link href={`/app/campaigns/${campaignId}`} className={buttonStyles('primary', 'lg')}>
              Open the brief
            </Link>
          }
        />
      ) : (
        <>
          {/*
            Said once for the whole set rather than on every row. A
            specification written directly — as the benchmark seeds them —
            records no `field_assertions`, so none of its facts can say where
            they came from. That is worth knowing once; repeated five times it
            is noise.
          */}
          {allUnrecorded(facts) ? (
            <Card className="border-dashed">
              <p className="text-small text-muted">
                None of these facts records where it came from. That happens when a
                specification is written directly rather than settled through the brief
                conversation — the values are real, but nobody stated them on the record.
              </p>
            </Card>
          ) : null}
          <ol className="space-y-4">
            {facts.map((fact, i) => (
              <MarketFactCard key={fact.key} fact={fact} index={i} />
            ))}
          </ol>
        </>
      )}

      {/* The sharp end of localization: the cue that makes a creative belong,
          and the line it must not cross. Both real `string[]` fields. */}
      {required.length > 0 || avoid.length > 0 ? (
        <section aria-labelledby="cues-title">
          <SectionHeader
            title={<span id="cues-title">What the creative must do here</span>}
            description="Carried into the creative plan, the brand check and every generated visual."
          />
          <div className="mt-lg grid gap-4 lg:grid-cols-2">
            {required.length > 0 ? (
              <Card className="border-l-2 border-l-success">
                <h3 className="text-label uppercase text-success">Must include</h3>
                <ul className="mt-3 space-y-2">
                  {required.map((item) => (
                    <li key={item} className="text-body">
                      {item}
                    </li>
                  ))}
                </ul>
              </Card>
            ) : null}
            {avoid.length > 0 ? (
              <Card className="border-l-2 border-l-danger">
                <h3 className="text-label uppercase text-danger">Must avoid</h3>
                <ul className="mt-3 space-y-2">
                  {avoid.map((item) => (
                    <li key={item} className="text-body">
                      {item}
                    </li>
                  ))}
                </ul>
                <p className="mt-4 border-t border-line pt-3 text-caption text-muted">
                  These are refusals, not preferences. The brand check tests the work against
                  them before anything ships.
                </p>
              </Card>
            ) : null}
          </div>
        </section>
      ) : null}

      {known ? <Legend facts={facts} /> : null}
    </div>
  );
}

/**
 * One market fact, its provenance, and what it asks of the creative.
 *
 * Laid out as a two-column editorial row rather than a definition list,
 * because the implication is the point and a `dt`/`dd` pair buries it.
 */
function MarketFactCard({ fact, index }: { fact: MarketFact; index: number }) {
  const implication = creativeImplication(fact);
  const caution = confidenceCaution(fact.confidence);
  const badge = CONFIDENCE_LABEL[fact.confidence];

  return (
    <Reveal as="li" index={index}>
      <Card className={cx('h-full', fact.value ? undefined : 'border-dashed')}>
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] lg:gap-10">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-label uppercase text-muted">{fact.label}</span>
              {badge ? (
                <span
                  title={CONFIDENCE_MEANING[fact.confidence]}
                  className={cx('text-label uppercase', TONE[fact.confidence])}
                >
                  {badge}
                </span>
              ) : null}
            </div>
            {/* Display type for a known value, because the place is the
                headline of this screen. An em dash would be a shrug. */}
            <p
              className={cx(
                'mt-2',
                fact.value ? 'text-h2' : 'text-h3 font-normal text-muted',
              )}
            >
              {fact.value ?? 'Not known yet'}
            </p>
            {caution ? <p className="mt-2 text-caption text-muted">{caution}</p> : null}
          </div>

          <div className="min-w-0 border-t border-line pt-4 lg:border-l lg:border-t-0 lg:pl-10 lg:pt-0">
            <p className="text-label uppercase text-muted">Creative implication</p>
            {implication ? (
              <p className="mt-2 text-body">{implication}</p>
            ) : (
              // No value, no instruction. Inventing guidance from a blank
              // field is how a campaign ends up "localized" for nowhere.
              <p className="mt-2 text-body text-muted">
                Nothing in the creative can rely on this until it is decided.
              </p>
            )}
          </div>
        </div>
      </Card>
    </Reveal>
  );
}

/**
 * What the provenance markers mean.
 *
 * Only for the kinds actually present. Often the whole legend is absent, and
 * that is itself informative: a specification written directly carries no
 * `field_assertions`, so its facts are recorded without a stated source,
 * whereas one built through discovery records stated or inferred per field.
 */
function Legend({ facts }: { facts: readonly MarketFact[] }) {
  const kinds = [...new Set(facts.map((f) => f.confidence))].filter(
    (kind) => CONFIDENCE_LABEL[kind] !== null,
  );
  if (kinds.length === 0) return null;
  return (
    <section aria-labelledby="legend-title" className="border-t border-line pt-6">
      <h2 id="legend-title" className="text-label uppercase text-muted">
        How we know
      </h2>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {kinds.map((kind) => (
          <div key={kind}>
            <dt className={cx('text-label uppercase', TONE[kind])}>{CONFIDENCE_LABEL[kind]}</dt>
            <dd className="mt-1 text-caption text-muted">{CONFIDENCE_MEANING[kind]}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
