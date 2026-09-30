/**
 * Reading evaluations side by side.
 *
 * One mapping layer, because the Compare table is the one place on this screen
 * where several evaluations are read against each other, and getting that
 * alignment wrong is not a layout bug — it puts a number under the wrong word.
 *
 * ---
 *
 * **Dimensions align by identity, never by position** (audit finding DH-2).
 *
 * The table used to take its row labels from the first column's dimensions and
 * then read every other column positionally, `dimensions[index]`. That is only
 * correct while every evaluation carries the same dimensions in the same order,
 * which nothing guarantees: `CreativeEvaluation.dimensions` is
 * `Field(min_length=1)`, so one scored dimension is a legal evaluation, and
 * `aggregate_score` deliberately renormalises over whichever dimensions are
 * present — its own words are "a degraded evaluation that scored six dimensions
 * reports what it measured rather than pretending the other four were zero".
 *
 * Positional reads broke that promise twice over. A six-dimension evaluation
 * beside a ten-dimension one showed its six scores under the *first six
 * labels*, which are not necessarily the dimensions it scored, and then filled
 * the remaining four with `?? 0` — a fabricated score, coloured red by the
 * threshold palette as though a model had judged it and found it wanting.
 *
 * So a missing dimension is `null` here and renders as "not scored". Not zero,
 * because zero is a judgement and this is the absence of one.
 */

import type { DimensionScoreView, EvaluationDetailView, RankedAssetView } from '@/lib/api';

export interface ComparisonColumn {
  row: RankedAssetView;
  detail: EvaluationDetailView;
}

export interface ComparisonCell {
  /** Null when this evaluation did not score this dimension. */
  score: number | null;
  /** The model's note, when there is one for this dimension. */
  note: string;
}

export interface ComparisonRow {
  /** The stable key the backend uses, e.g. `brand_alignment`. */
  dimension: string;
  /** The human label, taken from an evaluation that actually scored it. */
  label: string;
  /** How much the dimension moved the overall score, when any column says. */
  weight: number | null;
  /** One cell per column, in the same order as the columns. */
  cells: ComparisonCell[];
  /** True when at least one column did not score this dimension. */
  partial: boolean;
}

/**
 * The columns worth comparing: ranked assets that have a scored evaluation.
 *
 * Built as a concrete list rather than filtered so every column is known to
 * carry one, without asserting it away.
 */
export function comparisonColumns(
  ranked: readonly RankedAssetView[],
  evaluations: readonly EvaluationDetailView[],
): ComparisonColumn[] {
  const detailFor = new Map(evaluations.map((item) => [item.generated_asset_id, item]));
  const columns: ComparisonColumn[] = [];
  for (const row of ranked) {
    const detail = detailFor.get(row.generated_asset_id);
    if (detail && detail.dimensions.length) columns.push({ row, detail });
  }
  return columns;
}

/**
 * Every dimension any column scored, each aligned across all columns.
 *
 * The union rather than the first column's set: a dimension only the second
 * evaluation scored is still a real judgement, and dropping it would hide the
 * one number that distinguishes the two creatives.
 *
 * Order follows first appearance across the columns in rank order, so the table
 * is stable for the same data and the best-ranked evaluation's own ordering
 * leads. `weight` is read from the first column that carries the dimension —
 * the backend publishes one weight table, so any column that scored it agrees.
 */
export function comparisonRows(columns: readonly ComparisonColumn[]): ComparisonRow[] {
  const byDimension = new Map<string, DimensionScoreView[]>();
  const order: string[] = [];

  for (const { detail } of columns) {
    for (const scored of detail.dimensions) {
      const existing = byDimension.get(scored.dimension);
      if (existing) {
        existing.push(scored);
      } else {
        byDimension.set(scored.dimension, [scored]);
        order.push(scored.dimension);
      }
    }
  }

  return order.map((dimension) => {
    const scoredBy = byDimension.get(dimension) ?? [];
    const first = scoredBy[0];
    const cells = columns.map(({ detail }) => {
      const match = detail.dimensions.find((d) => d.dimension === dimension);
      return match
        ? { score: match.score, note: match.note }
        : { score: null, note: '' };
    });
    return {
      dimension,
      // Labels come from a column that scored this dimension, so a row is never
      // titled by a dimension it is not showing.
      label: first?.label ?? dimension,
      weight: first?.weight ?? null,
      cells,
      partial: cells.some((cell) => cell.score === null),
    };
  });
}
