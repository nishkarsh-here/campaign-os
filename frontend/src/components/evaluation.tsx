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

/** Green / amber / red on the same scale the thresholds use. */
function scoreTone(score: number): string {
  if (score >= 72) return 'text-success';
  if (score >= 55) return 'text-warning';
  return 'text-danger';
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
                    <span className="ml-1 text-[10px] text-success">★</span>
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
