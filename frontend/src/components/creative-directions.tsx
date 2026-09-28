'use client';

/**
 * CHOOSE A CREATIVE DIRECTION.
 *
 * Three routes out of one brief, presented as concepts rather than as records.
 * This is the first genuinely creative decision in the product and the first
 * human gate that changes what gets made, so it is built as a review rather
 * than as a form.
 *
 * ## Nothing here is invented
 *
 * Every passage is a real `CreativeDirection` field, mapped once in
 * `lib/creative.ts`. Fields the direction does not carry — `visual_story`,
 * `camera`, `mood`, all of which belong to the later plan — are absent rather
 * than approximated from a neighbouring field.
 *
 * There is no imagery at this stage and none is faked. The coloured band on
 * each card is the direction's own `palette`, drawn as swatches and labelled as
 * a stated palette, not as a preview of the campaign.
 */

import { useId, useState } from 'react';
import {
  Button,
  Card,
  EmptyState,
  Reveal,
  StatusBadge,
  Textarea,
  cx,
} from '@/components/ui';
import type { CampaignSpecification, CreativeStageView } from '@/lib/api';
import type { Capabilities } from '@/lib/capabilities';
import {
  compareDirections,
  contextStrip,
  differencesOnly,
  toDirectionView,
  type ComparisonRow,
  type DirectionView,
} from '@/lib/creative';

export function CreativeDirections({
  view,
  campaignSpecification,
  brandName,
  capabilities,
  busy,
  /**
   * True only while Gate 1 is open.
   *
   * The routes stay on screen after one is chosen — the set still holds all
   * three and a person should be able to see what was not picked, and why the
   * winner won. What goes away is the ability to choose, because the server
   * will refuse it.
   */
  gateOpen,
  onChoose,
  onRequestChanges,
}: {
  view: CreativeStageView;
  campaignSpecification: CampaignSpecification | null;
  brandName: string | null;
  capabilities: Capabilities;
  busy: boolean;
  gateOpen: boolean;
  onChoose: (directionId: string) => void;
  onRequestChanges: (feedback: string) => void;
}) {
  const [comparing, setComparing] = useState(false);
  const set = view.direction_set;

  if (!set || set.directions.length === 0) {
    return (
      <EmptyState
        title="No creative routes yet"
        description="Campaign OS develops three different routes from the brief, the brand and the market. Nothing has been generated for this campaign."
      />
    );
  }

  const directions = [...set.directions]
    .sort((a, b) => a.ordinal - b.ordinal)
    .map((d) => toDirectionView(d, set, view.selected_direction_id));
  const rows = compareDirections(set.directions);
  const differences = differencesOnly(rows);
  const context = contextStrip(campaignSpecification, brandName);
  const canApprove = capabilities.can('approve');
  const chosen = directions.find((d) => d.selected);

  return (
    <div className="space-y-lg">
      <header>
        <h2 className="max-w-content text-h1">
          {gateOpen ? 'Choose a creative direction' : 'The creative routes'}
        </h2>
        <p className="mt-3 max-w-content text-body text-muted">
          {gateOpen
            ? `Campaign OS developed ${directions.length} different creative ${
                directions.length === 1 ? 'route' : 'routes'
              } from your brief, your brand and this market. They are meant to be genuinely different — choosing one is a human decision.`
            : chosen
              ? `Direction ${chosen.number} was chosen. The other ${
                  directions.length - 1
                } are kept here so the decision can be read back.`
              : 'The routes developed from this brief.'}
        </p>

        {context.length > 0 ? (
          <dl className="mt-5 flex flex-wrap gap-x-8 gap-y-3 border-t border-line pt-4">
            {context.map((row) => (
              <div key={row.label} className="min-w-0 max-w-[24rem]">
                <dt className="text-label uppercase text-muted">{row.label}</dt>
                <dd className="mt-0.5 truncate text-small" title={row.value}>
                  {row.value}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}
      </header>

      {/* The distinctness check is deterministic set overlap, not a model
          opinion — worth surfacing when it failed, because two similar routes
          are not really a choice. */}
      {view.diversity && !view.diversity.passed ? (
        <Card className="border-l-2 border-l-warning">
          <p className="text-label uppercase text-warning">These routes overlap</p>
          <p className="mt-2 text-body text-muted">
            The distinctness check found two routes too similar to each other. You can still
            choose one, or ask for another set.
          </p>
        </Card>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant={comparing ? 'primary' : 'secondary'}
          onClick={() => setComparing((c) => !c)}
          aria-pressed={comparing}
        >
          {comparing ? 'Back to the routes' : 'Compare all three'}
        </Button>
        {set.recommended_ordinal !== null ? (
          <p className="text-small text-muted">
            Campaign OS puts direction{' '}
            {String(set.recommended_ordinal).padStart(2, '0')} forward — you do not have to
            agree.
          </p>
        ) : null}
      </div>

      {comparing ? (
        <Comparison directions={directions} rows={rows} differences={differences} />
      ) : (
        <ul className="grid gap-5 xl:grid-cols-3 xl:items-start">
          {directions.map((direction, i) => (
            <DirectionCard
              key={direction.id}
              direction={direction}
              index={i}
              gateOpen={gateOpen}
              canApprove={canApprove}
              busy={busy}
              onChoose={() => onChoose(direction.id)}
            />
          ))}
        </ul>
      )}

      {/* Set-level reasoning: why the recommended one won. Attached to the set
          because that is what it describes — putting it on a card would read as
          that card's own rationale. */}
      {set.recommendation_reasons.length > 0 ? (
        <Card>
          <h3 className="text-h3">Why Campaign OS put one forward</h3>
          <ul className="mt-3 space-y-2">
            {set.recommendation_reasons.map((reason) => (
              <li key={reason} className="text-body text-muted">
                {reason}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {gateOpen ? (
        <CreativeReview
          directions={directions}
          campaignSpecification={campaignSpecification}
          brandName={brandName}
          capabilities={capabilities}
          busy={busy}
          onRequestChanges={onRequestChanges}
        />
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------ the card

function DirectionCard({
  direction,
  index,
  gateOpen,
  canApprove,
  busy,
  onChoose,
}: {
  direction: DirectionView;
  index: number;
  gateOpen: boolean;
  canApprove: boolean;
  busy: boolean;
  onChoose: () => void;
}) {
  const headingId = useId();
  return (
    <Reveal as="li" index={index} className="h-full">
      <Card
        as="article"
        padding={false}
        aria-labelledby={headingId}
        data-selected={direction.selected}
        className="direction-card flex h-full flex-col"
      >
        <div className="p-5 sm:p-6">
          <div className="flex items-start justify-between gap-4">
            {/* The editorial number. Display type because the three of them
                are the primary way a person refers to these.

                `aria-hidden` (the heading below carries "Direction 01"), but
                still ink on a page: at `text-muted/40` it measured 2.17 against
                the 3.0 large-text floor. Quiet is not the same as unreadable. */}
            <p className="text-display leading-none text-muted" aria-hidden="true">
              {direction.number}
            </p>
            <div className="flex shrink-0 flex-col items-end gap-1.5">
              {direction.selected ? <StatusBadge tone="positive">Chosen</StatusBadge> : null}
              {direction.recommended && !direction.selected ? (
                <StatusBadge tone="active">Put forward</StatusBadge>
              ) : null}
            </div>
          </div>

          <h3 id={headingId} className="mt-4 text-h2">
            <span className="sr-only">Direction {direction.number}: </span>
            {direction.title}
          </h3>
          <p className="mt-3 text-body text-muted">{direction.statement}</p>

          {/* The direction's own stated colours. Labelled, because a band of
              colour next to a concept could otherwise be read as artwork. */}
          {direction.palette.length > 0 ? (
            <div className="mt-5">
              <p className="text-label uppercase text-muted">Palette this route names</p>
              <div
                className="palette-band mt-2"
                role="img"
                aria-label={`Palette: ${direction.palette.join(', ')}`}
              >
                {direction.palette.slice(0, 6).map((hex) => (
                  <span key={hex} style={{ background: hex }} />
                ))}
              </div>
            </div>
          ) : null}
        </div>

        <div className="space-y-5 border-t border-line p-5 sm:p-6">
          {direction.rationale ? (
            <Passage label="Why Campaign OS suggested this" value={direction.rationale} />
          ) : null}

          {direction.localRelevance.length > 0 ? (
            <div>
              <p className="text-label uppercase text-accent">Local relevance</p>
              <ul className="mt-2 space-y-1.5">
                {direction.localRelevance.map((item) => (
                  <li key={item} className="text-small">
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {direction.brandFit.length > 0 ? (
            <div>
              <p className="text-label uppercase text-muted">Brand fit</p>
              <dl className="mt-2 space-y-2">
                {direction.brandFit.map((f) => (
                  <div key={f.label}>
                    <dt className="sr-only">{f.label}</dt>
                    <dd className="text-small">{f.value}</dd>
                  </div>
                ))}
              </dl>
              {/* No score and no percentage: the backend expresses brand fit
                  as prose, and a number invented here would look like a
                  measurement. */}
            </div>
          ) : null}

          {/* Everything else is progressive disclosure. A concept card that
              dumps eighteen fields is the records view this screen replaced. */}
          <details className="group">
            <summary className="cursor-pointer list-none text-label uppercase text-muted transition-colors duration-fast hover:text-ink">
              <span className="group-open:hidden">More about this route →</span>
              <span className="hidden group-open:inline">Less ↑</span>
            </summary>
            <div className="mt-4 space-y-4 border-l border-line pl-4">
              <Passage label="Headline" value={direction.headline} />
              {direction.subhead ? (
                <Passage label="Subhead" value={direction.subhead} />
              ) : null}
              <Passage label="Call to action" value={direction.cta} />
              {direction.sections.map((s) => (
                <Passage key={s.label} label={s.label} value={s.value} />
              ))}
              {direction.referenceUsed.length > 0 || direction.referenceAvoided.length > 0 ? (
                <ReferenceInfluence direction={direction} />
              ) : null}
              {direction.distinctness ? (
                <Passage label="On distinctness" value={direction.distinctness} />
              ) : null}
            </div>
          </details>
        </div>

        <div className="mt-auto border-t border-line p-5 sm:p-6">
          {gateOpen && canApprove ? (
            <Button
              variant={direction.selected ? 'secondary' : 'primary'}
              size="lg"
              className="w-full"
              disabled={busy || direction.selected}
              onClick={onChoose}
            >
              {direction.selected ? 'This route is chosen' : `Choose direction ${direction.number}`}
            </Button>
          ) : direction.selected ? (
            <p className="text-label uppercase text-success">Chosen — the plan is built from this</p>
          ) : gateOpen ? (
            // The decision is live, this person just may not make it. Saying
            // "not chosen" here would misreport an open gate as a closed one.
            <p className="text-caption text-muted">Choosing a direction needs approval rights.</p>
          ) : (
            // The gate has closed: the server refuses the decision, and a
            // control that cannot work is worse than none.
            <p className="text-caption text-muted">Not chosen</p>
          )}
        </div>
      </Card>
    </Reveal>
  );
}

function Passage({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-label uppercase text-muted">{label}</p>
      <p className="mt-1 text-small">{value}</p>
    </div>
  );
}

/**
 * What the references contributed to this route.
 *
 * Both lists are fields on the direction itself. Showing the refusal beside the
 * borrowing is what makes ADR-011 — learn the style, never copy the design —
 * checkable rather than merely stated.
 */
function ReferenceInfluence({ direction }: { direction: DirectionView }) {
  return (
    <div>
      <p className="text-label uppercase text-muted">Reference influence</p>
      {direction.referenceUsed.length > 0 ? (
        <ul className="mt-2 space-y-1">
          {direction.referenceUsed.map((r) => (
            <li key={r} className="flex gap-2 text-small">
              <span aria-hidden="true" className="text-success">
                +
              </span>
              <span>{r}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {direction.referenceAvoided.length > 0 ? (
        <ul className="mt-2 space-y-1">
          {direction.referenceAvoided.map((r) => (
            <li key={r} className="flex gap-2 text-small text-muted">
              <span aria-hidden="true" className="text-danger">
                −
              </span>
              <span>{r}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------- compare mode

/**
 * The three routes, axis by axis.
 *
 * Differences first, because that is the question a person opens this to
 * answer. What they share follows, since "all three keep the product in frame"
 * is also worth knowing. An axis no direction fills is not shown at all.
 */
function Comparison({
  directions,
  rows,
  differences,
}: {
  directions: readonly DirectionView[];
  rows: readonly ComparisonRow[];
  differences: readonly ComparisonRow[];
}) {
  const shared = rows.filter((r) => !r.differs);
  return (
    <Reveal className="space-y-lg">
      <section aria-labelledby="differences-title">
        <h3 id="differences-title" className="text-h3">
          Different because…
        </h3>
        {differences.length === 0 ? (
          <p className="mt-2 text-body text-muted">
            On every axis we can compare, these routes say the same thing. That is unusual and
            worth asking for another set.
          </p>
        ) : (
          <div className="mt-4 space-y-4">
            {differences.map((row) => (
              <ComparisonRowView key={row.label} row={row} directions={directions} />
            ))}
          </div>
        )}
      </section>

      {shared.length > 0 ? (
        <section aria-labelledby="shared-title">
          <h3 id="shared-title" className="text-h3">
            What they all share
          </h3>
          <div className="mt-4 space-y-4">
            {shared.map((row) => (
              <ComparisonRowView key={row.label} row={row} directions={directions} shared />
            ))}
          </div>
        </section>
      ) : null}
    </Reveal>
  );
}

/**
 * One axis across the three routes.
 *
 * A row rather than a table: at three columns a table adds a header a reader
 * has to keep looking back at, and below `lg` it collapses into something
 * unreadable. Each cell names its own direction.
 */
function ComparisonRowView({
  row,
  directions,
  shared,
}: {
  row: ComparisonRow;
  directions: readonly DirectionView[];
  shared?: boolean;
}) {
  return (
    <Card padding={false} className={cx(shared && 'bg-transparent')}>
      <p className="border-b border-line px-5 py-2.5 text-label uppercase text-muted">
        {row.label}
      </p>
      <dl className="grid divide-y divide-line lg:grid-cols-3 lg:divide-x lg:divide-y-0">
        {row.values.map((value, i) => {
          const direction = directions[i];
          return (
            <div key={direction?.id ?? i} className="px-5 py-4">
              <dt className="text-label uppercase text-muted">
                {direction ? `${direction.number} ${direction.title}` : '—'}
              </dt>
              <dd className={cx('mt-1.5 text-small', !value && 'text-muted')}>
                {/* Not every direction fills every axis, and an empty cell is
                    the truth about that one — never the neighbour's value. */}
                {value ?? 'Not specified for this route'}
              </dd>
            </div>
          );
        })}
      </dl>
    </Card>
  );
}

// ----------------------------------------------------------- human approval

/**
 * The governance moment.
 *
 * Deliberately a separate block with its own heading rather than a button on a
 * card: choosing a route decides what the rest of the campaign becomes, and the
 * interface should say so before it happens.
 */
function CreativeReview({
  directions,
  campaignSpecification,
  brandName,
  capabilities,
  busy,
  onRequestChanges,
}: {
  directions: readonly DirectionView[];
  campaignSpecification: CampaignSpecification | null;
  brandName: string | null;
  capabilities: Capabilities;
  busy: boolean;
  onRequestChanges: (feedback: string) => void;
}) {
  const [asking, setAsking] = useState(false);
  const [feedback, setFeedback] = useState('');
  const chosen = directions.find((d) => d.selected);
  const canRevise = capabilities.can('request_revision');

  return (
    <Card className="border-l-2 border-l-accent">
      <p className="text-label uppercase text-accent">Creative review</p>
      <h3 className="mt-2 text-h2">
        {chosen
          ? `Direction ${chosen.number} is chosen`
          : 'You are choosing the concept that guides the rest of the campaign'}
      </h3>
      <p className="mt-2 max-w-content text-body text-muted">
        {chosen
          ? 'Campaign OS is turning this route into the Creative Plan — the document every visual is generated from.'
          : 'Whichever route you choose becomes the Creative Plan, and every visual is generated from it. The other two are not kept.'}
      </p>

      {/* What survives the choice. Only facts the backend genuinely pins: the
          Creative Director overwrites the model's cta and key_message with the
          Campaign Specification's after both calls, so these really are
          carried forward unchanged. */}
      {!chosen ? <CarriedForward specification={campaignSpecification} brandName={brandName} /> : null}

      {canRevise ? (
        <div className="mt-6 border-t border-line pt-5">
          {asking ? (
            <div>
              <label htmlFor="creative-feedback" className="text-label uppercase text-muted">
                What needs to change?
              </label>
              <Textarea
                id="creative-feedback"
                rows={4}
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                placeholder="Too corporate. Show the product being used, not a hero shot."
                className="mt-2"
              />
              <p className="mt-2 text-caption text-muted">
                Campaign OS develops another set of routes from your brief and this note. The
                campaign objective, audience, market and approved claims are carried over
                unchanged.
              </p>
              <div className="mt-4 flex flex-wrap gap-3">
                <Button
                  variant="primary"
                  disabled={busy || !feedback.trim()}
                  onClick={() => onRequestChanges(feedback.trim())}
                >
                  Ask for another set
                </Button>
                <Button variant="ghost" onClick={() => setAsking(false)} disabled={busy}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <Button variant="secondary" onClick={() => setAsking(true)} disabled={busy}>
              None of these work — request changes
            </Button>
          )}
        </div>
      ) : null}
    </Card>
  );
}

/** The facts a choice does not put at risk. */
function CarriedForward({
  specification,
  brandName,
}: {
  specification: CampaignSpecification | null;
  brandName: string | null;
}) {
  const rows = [
    { label: 'Campaign objective', value: specification?.objective ?? null },
    { label: 'Audience', value: specification?.audience ?? null },
    { label: 'Market', value: specification?.region ?? null },
    { label: 'Brand', value: brandName },
  ].filter((r) => r.value);
  if (rows.length === 0) return null;
  return (
    <div className="mt-5 border-t border-line pt-4">
      <p className="text-label uppercase text-muted">Carried forward whichever you choose</p>
      <dl className="mt-3 grid gap-x-8 gap-y-3 sm:grid-cols-2">
        {rows.map((r) => (
          <div key={r.label} className="min-w-0">
            <dt className="text-label uppercase text-muted">{r.label}</dt>
            <dd className="mt-0.5 truncate text-small" title={r.value ?? undefined}>
              {r.value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
