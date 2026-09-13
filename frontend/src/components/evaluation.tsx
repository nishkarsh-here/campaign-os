'use client';

/**
 * Creative evaluation and the recommendation.
 *
 * The screen has one job: make "which of these should we use?" answerable in a
 * few seconds, and defensible if anyone asks why. So the recommendation leads,
 * every score is shown next to the words that explain it, and the thresholds
 * that produced a disposition are stated rather than implied.
 *
 * The ranking is advice. The human selects, including against the
 * recommendation — a tool that only lets you agree with it is not a tool.
 */

import { useState } from 'react';
import { mediaUrl } from '@/lib/api';
import type {
  Disposition,
  EvaluationDetailView,
  EvaluationView,
  RankedAssetView,
} from '@/lib/api';

const DISPOSITION_LABEL: Record<Disposition, string> = {
  PASS: 'Pass',
  NEEDS_REVIEW: 'Needs review',
  REJECT: 'Reject',
};

const DISPOSITION_TONE: Record<Disposition, string> = {
  PASS: 'border-emerald-500/50 text-emerald-400',
  NEEDS_REVIEW: 'border-amber-500/50 text-amber-400',
  REJECT: 'border-red-500/50 text-red-400',
};

/** Green / amber / red on the same scale the thresholds use. */
function scoreTone(score: number): string {
  if (score >= 72) return 'text-emerald-400';
  if (score >= 55) return 'text-amber-400';
  return 'text-red-400';
}

function barTone(score: number): string {
  if (score >= 72) return 'bg-emerald-500/70';
  if (score >= 55) return 'bg-amber-500/70';
  return 'bg-red-500/70';
}

function Pill({ disposition }: { disposition: Disposition }) {
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide ${DISPOSITION_TONE[disposition]}`}
    >
      {DISPOSITION_LABEL[disposition]}
    </span>
  );
}

/** The headline answer. Leads the screen because it is what was asked. */
export function RecommendationPanel({
  view,
  busy,
  onSelect,
}: {
  view: EvaluationView;
  busy: boolean;
  onSelect: (assetId: string) => void;
}) {
  const recommendation = view.recommendation;
  if (!recommendation) return null;

  const row = view.ranked.find(
    (candidate) => candidate.generated_asset_id === recommendation.generated_asset_id,
  );

  // Nothing worth recommending: say so rather than putting forward the least
  // bad option as though it were a choice.
  if (!recommendation.generated_asset_id || !row) {
    return (
      <section className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-5">
        <h2 className="text-sm font-semibold">No recommendation</h2>
        <p className="mt-1 text-sm">{recommendation.reason}</p>
        {recommendation.caveat ? (
          <p className="mt-2 text-xs text-muted">{recommendation.caveat}</p>
        ) : null}
      </section>
    );
  }

  const selected = view.selected_asset_id === row.generated_asset_id;
  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">Recommended</h2>
        <span className="text-xs text-muted">
          evaluator {view.evaluator_version} · {view.outcome}
        </span>
      </div>

      <div className="mt-4 flex flex-col gap-5 sm:flex-row">
        {row.asset ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={mediaUrl(row.asset.url)}
            alt={`Recommended plate, rank ${row.rank}`}
            className="w-full shrink-0 rounded-md border border-line bg-line/30 object-cover sm:w-56"
          />
        ) : null}

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-3">
            <span className="text-2xl font-semibold tracking-tight">
              #{recommendation.rank}
            </span>
            <span className={`text-2xl font-semibold ${scoreTone(row.overall_score)}`}>
              {row.overall_score}
              <span className="text-sm text-muted"> / 100</span>
            </span>
            <Pill disposition={row.disposition} />
          </div>

          <p className="mt-3 text-[10px] uppercase tracking-wide text-muted">Why</p>
          <p className="mt-0.5 text-sm">{recommendation.reason}</p>

          {recommendation.caveat ? (
            <p className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/5 p-2.5 text-xs">
              {recommendation.caveat}
            </p>
          ) : null}

          <button
            type="button"
            disabled={busy || selected}
            onClick={() => onSelect(row.generated_asset_id)}
            className="mt-4 rounded-md border border-line bg-line/30 px-3 py-1.5 text-sm hover:bg-line/50 disabled:opacity-50"
          >
            {selected ? 'Selected' : 'Use this creative'}
          </button>
        </div>
      </div>
    </section>
  );
}

function DimensionBar({
  label,
  score,
  note,
  weight,
}: {
  label: string;
  score: number;
  note: string;
  weight: number;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span>{label}</span>
        <span className="text-muted">
          <span className={scoreTone(score)}>{score}</span>
          {/* The weight is shown so a weak dimension's impact is legible. */}
          <span className="ml-1 text-[10px]">×{weight.toFixed(2)}</span>
        </span>
      </div>
      <div className="mt-1 h-1 rounded bg-line">
        <div className={`h-1 rounded ${barTone(score)}`} style={{ width: `${score}%` }} />
      </div>
      {note ? <p className="mt-1 text-[11px] text-muted">{note}</p> : null}
    </div>
  );
}

function EvaluationCard({
  row,
  detail,
  selected,
  busy,
  expanded,
  onToggle,
  onSelect,
  onRetry,
}: {
  row: RankedAssetView;
  detail: EvaluationDetailView | undefined;
  selected: boolean;
  busy: boolean;
  expanded: boolean;
  onToggle: () => void;
  onSelect: () => void;
  onRetry: () => void;
}) {
  return (
    <article
      className={`rounded-lg border p-4 ${selected ? 'border-ink/40 bg-line/20' : 'border-line'}`}
    >
      <div className="flex items-start gap-4">
        {row.asset ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={mediaUrl(row.asset.url)}
            alt={`Plate ranked ${row.rank}`}
            className="h-24 w-24 shrink-0 rounded border border-line bg-line/30 object-cover"
          />
        ) : null}

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="text-sm font-medium">#{row.rank}</span>
            <span className={`text-lg font-semibold ${scoreTone(row.overall_score)}`}>
              {row.overall_score}
            </span>
            <Pill disposition={row.disposition} />
            {row.recommended ? (
              <span className="rounded-full border border-emerald-500/50 px-2 py-0.5 text-[10px] uppercase tracking-wide text-emerald-400">
                Recommended
              </span>
            ) : null}
            {selected ? (
              <span className="rounded-full border border-line px-2 py-0.5 text-[10px] uppercase tracking-wide">
                Selected
              </span>
            ) : null}
          </div>

          <p className="mt-1.5 text-xs text-muted">{row.reason}</p>
          {row.asset ? (
            <p className="mt-1 text-[10px] text-muted">
              {row.asset.provider} · {row.asset.model} · {row.asset.width}×{row.asset.height}
            </p>
          ) : null}

          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={onToggle}
              className="rounded-md border border-line px-3 py-1 text-xs hover:bg-line/40"
            >
              {expanded ? 'Hide scores' : 'Inspect scores'}
            </button>
            <button
              type="button"
              disabled={busy || selected}
              onClick={onSelect}
              className="rounded-md border border-line px-3 py-1 text-xs hover:bg-line/40 disabled:opacity-50"
            >
              {selected ? 'Selected' : 'Select'}
            </button>
            {detail?.can_retry ? (
              <button
                type="button"
                disabled={busy}
                onClick={onRetry}
                className="rounded-md border border-line px-3 py-1 text-xs hover:bg-line/40 disabled:opacity-50"
              >
                Retry
              </button>
            ) : null}
          </div>
        </div>
      </div>

      {expanded && detail ? (
        <div className="mt-4 border-t border-line pt-4">
          <div className="grid gap-3 sm:grid-cols-2">
            {detail.dimensions.map((dimension) => (
              <DimensionBar
                key={dimension.dimension}
                label={dimension.label}
                score={dimension.score}
                note={dimension.note}
                weight={dimension.weight}
              />
            ))}
          </div>

          {detail.disposition_reasons.length ? (
            <div className="mt-4">
              <p className="text-[10px] uppercase tracking-wide text-muted">
                Why {DISPOSITION_LABEL[detail.disposition ?? 'PASS'].toLowerCase()}
              </p>
              <ul className="mt-1 space-y-0.5 text-xs text-muted">
                {detail.disposition_reasons.map((reason) => (
                  <li key={reason}>· {reason}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            {detail.strengths.length ? (
              <div>
                <p className="text-[10px] uppercase tracking-wide text-muted">Strengths</p>
                <ul className="mt-1 space-y-0.5 text-xs">
                  {detail.strengths.map((item) => (
                    <li key={item}>· {item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {detail.concerns.length ? (
              <div>
                <p className="text-[10px] uppercase tracking-wide text-muted">Concerns</p>
                <ul className="mt-1 space-y-0.5 text-xs text-muted">
                  {detail.concerns.map((item) => (
                    <li key={item}>· {item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>

          <p className="mt-4 text-[10px] text-muted">
            Judged against Creative Specification v{detail.specification_version} by evaluator{' '}
            {detail.evaluator_version}
            {detail.evaluator_model ? ` (${detail.evaluator_model})` : ''}.
          </p>
        </div>
      ) : null}
    </article>
  );
}

export function EvaluationBoard({
  view,
  busy,
  onSelect,
  onRetry,
}: {
  view: EvaluationView;
  busy: boolean;
  onSelect: (assetId: string) => void;
  onRetry: (evaluationId: string) => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const detailFor = new Map(view.evaluations.map((item) => [item.generated_asset_id, item]));

  const pending = view.evaluations.filter(
    (item) => item.status === 'PENDING' || item.status === 'RUNNING',
  );
  const failed = view.evaluations.filter((item) => item.status === 'FAILED');

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">Creative evaluation</h2>
        <span className="text-xs text-muted">{view.outcome}</span>
      </div>

      {/* A card is never left spinning: a running evaluation says so, and a
          failed one says why and offers a retry. */}
      {pending.length ? (
        <div className="rounded-md border border-line p-4">
          <p className="text-xs">
            Evaluating {pending.length} {pending.length === 1 ? 'creative' : 'creatives'}…
          </p>
          <div className="mt-2 h-1 overflow-hidden rounded bg-line">
            <div className="h-1 w-1/3 animate-pulse rounded bg-ink/50" />
          </div>
        </div>
      ) : null}

      {failed.length ? (
        <div className="rounded-md border border-red-500/40 bg-red-500/5 p-4">
          <p className="text-xs font-medium">
            {failed.length} {failed.length === 1 ? 'evaluation' : 'evaluations'} failed
          </p>
          <ul className="mt-2 space-y-2">
            {failed.map((item) => (
              <li key={item.id} className="flex flex-wrap items-center gap-2 text-xs">
                <span className="text-muted">{item.error_message}</span>
                {item.error_code ? (
                  <span className="font-mono text-[10px] text-muted">{item.error_code}</span>
                ) : null}
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onRetry(item.id)}
                  className="rounded-md border border-line px-2 py-0.5 text-[11px] hover:bg-line/40 disabled:opacity-50"
                >
                  Retry
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {view.ranked.map((row) => (
        <EvaluationCard
          key={row.evaluation_id}
          row={row}
          detail={detailFor.get(row.generated_asset_id)}
          selected={view.selected_asset_id === row.generated_asset_id}
          busy={busy}
          expanded={expanded === row.evaluation_id}
          onToggle={() =>
            setExpanded(expanded === row.evaluation_id ? null : row.evaluation_id)
          }
          onSelect={() => onSelect(row.generated_asset_id)}
          onRetry={() => onRetry(row.evaluation_id)}
        />
      ))}
    </section>
  );
}

/** Scores side by side, so two close creatives can actually be compared. */
export function ComparisonTable({ view }: { view: EvaluationView }) {
  const detailFor = new Map(view.evaluations.map((item) => [item.generated_asset_id, item]));
  // Built as a concrete list rather than filtered, so every column is known to
  // carry a scored evaluation without asserting it away.
  const columns: { row: RankedAssetView; detail: EvaluationDetailView }[] = [];
  for (const row of view.ranked) {
    const detail = detailFor.get(row.generated_asset_id);
    if (detail && detail.dimensions.length) columns.push({ row, detail });
  }

  const first = columns[0];
  if (columns.length < 2 || !first) return null;
  const dimensions = first.detail.dimensions;

  return (
    <section className="rounded-lg border border-line p-5">
      <h2 className="text-sm font-semibold">Compare</h2>
      <p className="mt-1 text-xs text-muted">
        Every dimension, side by side. The overall score is the weighted mean of these.
      </p>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[520px] text-xs">
          <thead>
            <tr className="border-b border-line text-left">
              <th className="pb-2 font-normal text-muted">Dimension</th>
              {columns.map(({ row }) => (
                <th key={row.evaluation_id} className="pb-2 text-right font-medium">
                  #{row.rank}
                  {row.recommended ? (
                    <span className="ml-1 text-[10px] text-emerald-400">★</span>
                  ) : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dimensions.map((dimension, index) => (
              <tr key={dimension.dimension} className="border-b border-line/50">
                <td className="py-1.5 text-muted">{dimension.label}</td>
                {columns.map(({ row, detail }) => {
                  const score = detail.dimensions[index]?.score ?? 0;
                  return (
                    <td
                      key={row.evaluation_id}
                      className={`py-1.5 text-right ${scoreTone(score)}`}
                    >
                      {score}
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr>
              <td className="pt-2 font-medium">Overall</td>
              {columns.map(({ row }) => (
                <td
                  key={row.evaluation_id}
                  className={`pt-2 text-right font-semibold ${scoreTone(row.overall_score)}`}
                >
                  {row.overall_score}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}
