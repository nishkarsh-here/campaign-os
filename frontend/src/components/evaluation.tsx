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
import { comparisonColumns, comparisonRows } from '@/lib/evaluation';
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

/**
 * Scores side by side, so two close creatives can actually be compared.
 *
 * Alignment is by dimension name, in `lib/evaluation.ts`. It was by array
 * position, which put one evaluation's score under another's label as soon as
 * the two scored different dimensions, and invented a `0` where a dimension was
 * missing (audit finding DH-2). A dimension nobody scored says so.
 */
export function ComparisonTable({ view }: { view: EvaluationView }) {
  const columns = comparisonColumns(view.ranked, view.evaluations);
  if (columns.length < 2) return null;
  const rows = comparisonRows(columns);
  const anyPartial = rows.some((row) => row.partial);

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
            {rows.map((dimension) => (
              <tr key={dimension.dimension} className="border-b border-line/50">
                <td className="py-1.5 text-muted">{dimension.label}</td>
                {dimension.cells.map((cell, index) => {
                  const column = columns[index];
                  if (!column) return null;
                  return (
                    <td
                      key={column.row.evaluation_id}
                      className={`py-1.5 text-right ${
                        cell.score === null ? 'text-muted' : scoreTone(cell.score)
                      }`}
                    >
                      {/* Not zero. Zero is a judgement; this is the absence of
                          one, and the backend renormalises rather than scoring
                          an unmeasured dimension. */}
                      {cell.score === null ? (
                        <span title="This evaluation did not score this dimension">—</span>
                      ) : (
                        cell.score
                      )}
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

      {anyPartial ? (
        <p className="mt-3 text-caption text-muted">
          A dash means that evaluation did not score that dimension. Each overall score is the
          weighted mean of the dimensions its own evaluation measured, not of the whole table.
        </p>
      ) : null}
    </section>
  );
}
