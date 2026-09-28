'use client';

/**
 * EVALUATE — the creative review studio.
 *
 * Judging creative work, not reading model output. The plate is large and
 * first; the scoring sits beside it; the mechanics fold away.
 *
 * ## The chain is shown, not just the verdict
 *
 * The model scores dimensions. The *service* computes the overall score from
 * published weights and the disposition from published thresholds, and states
 * the rule that fired in `disposition_reasons`. That chain is the product's
 * claim to being inspectable, so it is on screen — a bare "REJECT" would be
 * exactly the unaccountable verdict the architecture was built to avoid.
 *
 * There is no "message fit" dimension and no risk score. Neither is shown.
 * `concerns[]` is the model's own words about what is wrong, and is labelled
 * as that.
 */

import { useState } from 'react';
import {
  Button,
  Card,
  EmptyState,
  Plate,
  PlateAbsent,
  Reveal,
  StatusBadge,
  Textarea,
  cx,
} from '@/components/ui';
import {
  mediaUrl,
  type EvaluationDetailView,
  type EvaluationView,
  type GeneratedAssetView,
  type RankedAssetView,
} from '@/lib/api';
import type { Capabilities } from '@/lib/capabilities';
import { dimensionLabel, dispositionMeaning, scoreBand, summarise } from '@/lib/review';
import { aspectRatio, providerLabel } from '@/lib/generation';

export function EvaluationStudio({
  view,
  capabilities,
  busy,
  onEvaluate,
  onRetry,
  onSelect,
}: {
  view: EvaluationView;
  capabilities: Capabilities;
  busy: boolean;
  /**
   * Start scoring. `assetIds` narrows it to specific visuals, which is what
   * "score the remaining two" has to mean — omitting it scores every one.
   */
  onEvaluate: (assetIds?: string[]) => void;
  onRetry: (evaluationId: string) => void;
  onSelect: (assetId: string, note?: string) => void;
}) {
  const canReview = capabilities.can('approve');
  const byAsset = new Map(view.evaluations.map((e) => [e.generated_asset_id, e]));
  const remaining = view.unevaluated_asset_ids;

  if (view.evaluations.length === 0) {
    return (
      <EmptyState
        title="Nothing scored yet"
        description={
          view.can_evaluate
            ? 'Each visual is scored against the approved plan and the brand, then ranked.'
            : (view.blocked_reason ?? 'Generate some visuals first — there is nothing to score.')
        }
        action={
          view.can_evaluate && capabilities.can('edit_campaign') ? (
            <Button variant="primary" size="lg" disabled={busy} onClick={() => onEvaluate()}>
              {busy ? 'Scoring…' : 'Score the visuals'}
            </Button>
          ) : undefined
        }
      />
    );
  }

  return (
    <div className="space-y-lg">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-body">{view.outcome}</p>
          {view.in_flight > 0 ? (
            <p className="mt-1 text-label uppercase text-muted">{view.in_flight} still scoring</p>
          ) : null}
        </div>
        {/*
          One control, never two. The page header used to carry a second one,
          so a batch with unscored visuals offered "Re-evaluate" and "Score the
          remaining 2" side by side — two next actions for one question, with
          different scopes and no way to tell which was which.
        */}
        {view.can_evaluate && capabilities.can('edit_campaign') ? (
          remaining.length > 0 ? (
            <Button variant="primary" disabled={busy} onClick={() => onEvaluate(remaining)}>
              {busy
                ? 'Scoring…'
                : `Score the remaining ${remaining.length === 1 ? 'visual' : `${remaining.length} visuals`}`}
            </Button>
          ) : (
            <Button variant="secondary" disabled={busy} onClick={() => onEvaluate()}>
              {busy ? 'Scoring…' : 'Score every visual again'}
            </Button>
          )
        ) : null}
      </div>

      <Recommendation view={view} />

      <ol className="space-y-5">
        {view.ranked.map((row, i) => (
          <RankedCreative
            key={row.generated_asset_id}
            row={row}
            detail={byAsset.get(row.generated_asset_id)}
            index={i}
            selected={view.selected_asset_id === row.generated_asset_id}
            canReview={canReview}
            busy={busy}
            onSelect={onSelect}
            onRetry={onRetry}
          />
        ))}
      </ol>

      {/* Failures are listed too, so a plate nobody could score is not
          silently missing from the ranking. */}
      <UnjudgedCreatives
        view={view}
        canRetry={capabilities.can('edit_campaign')}
        busy={busy}
        onRetry={onRetry}
      />
    </div>
  );
}

/**
 * What the system puts forward, and who actually decides.
 *
 * The recommendation may legitimately decline — when every asset was rejected
 * it says so rather than putting the least bad one forward. The caveat field
 * exists for exactly that and is shown when present.
 */
function Recommendation({ view }: { view: EvaluationView }) {
  const rec = view.recommendation;
  if (!rec || !rec.generated_asset_id) {
    return (
      <Card>
        <p className="text-label uppercase text-muted">AI recommendation</p>
        <p className="mt-2 text-body">No recommendation available.</p>
        <p className="mt-1 text-small text-muted">
          {rec?.reason ||
            'Nothing scored well enough to put forward. Choosing one anyway is still yours to do.'}
        </p>
      </Card>
    );
  }
  /**
   * The recommendation and the row it points at are written by the same
   * service from the same ranking, so `reason` is frequently the identical
   * sentence. Printed in both places it read as two independent judgements
   * that happened to agree, in the same words, a screen apart.
   */
  const row = view.ranked.find((r) => r.generated_asset_id === rec.generated_asset_id);
  const echoes = row?.reason.trim() === rec.reason.trim();

  return (
    <Card className="border-l-2 border-l-info">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="text-label uppercase text-info">AI recommendation</p>
        <p className="text-label uppercase text-muted">Human decision</p>
      </div>
      <p className="mt-2 text-h3">
        Rank {rec.rank}
        {rec.overall_score !== null ? ` · ${rec.overall_score.toFixed(1)}` : ''}
      </p>
      {/* The service's own sentence, not a paraphrase — and said once. */}
      <p className="mt-2 text-body text-muted">
        {echoes
          ? 'Its reasoning, and everything it was compared against, is on the ranked creative below.'
          : rec.reason}
      </p>
      {rec.caveat ? (
        <p className="mt-2 text-body text-warning">{rec.caveat}</p>
      ) : null}
      <p className="mt-3 border-t border-line pt-3 text-caption text-muted">
        A recommendation, not a decision. You may select any of them, or none.
      </p>
    </Card>
  );
}

function RankedCreative({
  row,
  detail,
  index,
  selected,
  canReview,
  busy,
  onSelect,
  onRetry,
}: {
  row: RankedAssetView;
  detail: EvaluationDetailView | undefined;
  index: number;
  selected: boolean;
  canReview: boolean;
  busy: boolean;
  onSelect: (assetId: string, note?: string) => void;
  onRetry: (evaluationId: string) => void;
}) {
  const [noting, setNoting] = useState(false);
  const [note, setNote] = useState('');
  const disposition = dispositionMeaning(row.disposition);
  const asset = row.asset;

  return (
    <Reveal as="li" index={index}>
      <Card padding={false} className={cx('overflow-hidden', selected && 'border-l-2 border-l-accent')}>
        <div className="grid gap-0 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
          {/* The plate: large, in its own aspect ratio, nothing drawn over it. */}
          <div className="bg-line/30">
            {asset ? (
              <Plate
                src={mediaUrl(asset.url)}
                alt={describe(asset, row.rank)}
                ratio={aspectRatio(asset)}
              />
            ) : (
              <PlateAbsent label="Visual unavailable" />
            )}
          </div>

          <div className="min-w-0 p-5 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-label uppercase text-muted">Rank {row.rank}</p>
              <div className="flex flex-wrap items-center gap-2">
                {selected ? <StatusBadge tone="positive">Selected</StatusBadge> : null}
                {row.recommended ? <StatusBadge tone="active">Recommended</StatusBadge> : null}
                {disposition ? (
                  <StatusBadge tone={disposition.tone}>{disposition.label}</StatusBadge>
                ) : null}
              </div>
            </div>

            <p className="mt-3 text-h2 tabular-nums">{row.overall_score.toFixed(1)}</p>
            <p className="mt-1 text-small text-muted">{row.reason}</p>

            {detail ? <Judgement detail={detail} busy={busy} onRetry={onRetry} /> : null}

            <div className="mt-5 border-t border-line pt-4">
              {canReview ? (
                selected ? (
                  <p className="text-label uppercase text-success">
                    This is the campaign’s creative
                  </p>
                ) : noting ? (
                  <div>
                    <label
                      htmlFor={`note-${row.generated_asset_id}`}
                      className="text-label uppercase text-muted"
                    >
                      Why this one? (optional)
                    </label>
                    <Textarea
                      id={`note-${row.generated_asset_id}`}
                      rows={2}
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                      className="mt-2"
                    />
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        variant="primary"
                        disabled={busy}
                        onClick={() => onSelect(row.generated_asset_id, note.trim() || undefined)}
                      >
                        Select this creative
                      </Button>
                      <Button variant="ghost" disabled={busy} onClick={() => setNoting(false)}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <>
                    <Button variant="secondary" disabled={busy} onClick={() => setNoting(true)}>
                      Select this creative
                    </Button>
                    <p className="mt-2 text-caption text-muted">
                      The selected creative is the one the brand check and the final composition
                      work from.
                    </p>
                  </>
                )
              ) : (
                <p className="text-caption text-muted">
                  Selecting the campaign’s creative needs approval rights.
                </p>
              )}
            </div>
          </div>
        </div>
      </Card>
    </Reveal>
  );
}

/** Alt text that says what the picture is, not "image". */
function describe(asset: GeneratedAssetView, rank: number): string {
  return `Generated visual ranked ${rank}, from ${providerLabel(asset.provider)}, ${asset.width} by ${asset.height} pixels`;
}

/** The scoring, in the order a person needs it. */
function Judgement({
  detail,
  busy,
  onRetry,
}: {
  detail: EvaluationDetailView;
  busy: boolean;
  onRetry: (id: string) => void;
}) {
  const summary = summarise(detail);
  if (summary.unjudged) {
    return (
      <div role="alert" className="mt-4">
        <p className="text-small text-danger">{summary.failure ?? 'Not scored.'}</p>
        {summary.canRetry ? (
          <Button
            variant="secondary"
            size="sm"
            className="mt-2"
            disabled={busy}
            onClick={() => onRetry(detail.id)}
          >
            Score it again
          </Button>
        ) : null}
      </div>
    );
  }

  return (
    <div className="mt-4 space-y-4">
      {detail.rationale ? <p className="text-body">{detail.rationale}</p> : null}

      {detail.strengths.length > 0 || detail.concerns.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {detail.strengths.length > 0 ? (
            <div>
              <p className="text-label uppercase text-success">What works</p>
              <ul className="mt-1.5 space-y-1">
                {detail.strengths.map((s) => (
                  <li key={s} className="text-small">
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {detail.concerns.length > 0 ? (
            <div>
              {/* The model's own words about what is wrong. There is no risk
                  score on this surface and none is implied. */}
              <p className="text-label uppercase text-warning">What to watch</p>
              <ul className="mt-1.5 space-y-1">
                {detail.concerns.map((c) => (
                  <li key={c} className="text-small">
                    {c}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      <details className="group">
        <summary className="cursor-pointer list-none text-label uppercase text-muted transition-colors duration-fast hover:text-ink">
          <span className="group-open:hidden">How this score was reached →</span>
          <span className="hidden group-open:inline">Hide the scoring ↑</span>
        </summary>
        <div className="mt-3 space-y-3 border-t border-line pt-3">
          {/* The rule that fired, in the service's own words. This is what
              makes the disposition interrogable rather than a guess. */}
          {detail.disposition_reasons.length > 0 ? (
            <ul className="space-y-1">
              {detail.disposition_reasons.map((r) => (
                <li key={r} className="text-caption text-muted">
                  {r}
                </li>
              ))}
            </ul>
          ) : null}
          <dl className="space-y-2">
            {detail.dimensions.map((d) => {
              const band = scoreBand(d.score);
              return (
                <div key={d.dimension}>
                  <dt className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-small">
                      {dimensionLabel(d.dimension, d.label)}
                      {/* The dimension's share of the total, which is how a
                          reader knows why a low score barely moved things. */}
                      <span className="ml-2 text-caption text-muted">
                        {Math.round(d.weight * 100)}% of the total
                      </span>
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="text-small tabular-nums">{d.score}</span>
                      <StatusBadge tone={band.tone}>{band.label}</StatusBadge>
                    </span>
                  </dt>
                  {d.note ? <dd className="mt-0.5 text-caption text-muted">{d.note}</dd> : null}
                </div>
              );
            })}
          </dl>
        </div>
      </details>
    </div>
  );
}

/** Plates that have no usable judgement, so nothing is a silent gap. */
function UnjudgedCreatives({
  view,
  canRetry,
  busy,
  onRetry,
}: {
  view: EvaluationView;
  canRetry: boolean;
  busy: boolean;
  onRetry: (id: string) => void;
}) {
  const ranked = new Set(view.ranked.map((r) => r.generated_asset_id));
  const rest = view.evaluations.filter((e) => !ranked.has(e.generated_asset_id));
  if (rest.length === 0) return null;

  return (
    <Card>
      <h3 className="text-h3">Not scored</h3>
      <p className="mt-1 text-small text-muted">
        These are not low scores — they are visuals the scorer could not judge.
      </p>
      <ul className="mt-4 space-y-3">
        {rest.map((detail) => {
          const summary = summarise(detail);
          return (
            <li key={detail.id} className="flex flex-wrap items-center justify-between gap-3">
              <span className="min-w-0 text-small text-muted">
                {summary.failure ?? `Status: ${detail.status.toLowerCase()}`}
              </span>
              {canRetry && summary.canRetry ? (
                <Button variant="secondary" size="sm" disabled={busy} onClick={() => onRetry(detail.id)}>
                  Try again
                </Button>
              ) : null}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
