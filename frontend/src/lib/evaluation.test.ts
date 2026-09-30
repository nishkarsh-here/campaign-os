/**
 * Comparing evaluations that do not agree about their dimensions.
 *
 * Audit finding DH-2. The table read `dimensions[index]` across columns, which
 * is correct only while every evaluation carries the same dimensions in the
 * same order. The backend guarantees neither: `dimensions` needs one entry to be
 * valid, and `aggregate_score` renormalises over what is present specifically so
 * a partial evaluation is not treated as a zeroed one.
 *
 * So the two failure modes are asserted directly: a score under the wrong
 * label, and a fabricated zero where nothing was measured.
 */

import { describe, expect, it } from 'vitest';
import type { DimensionScoreView, EvaluationDetailView, RankedAssetView } from '@/lib/api';
import { comparisonColumns, comparisonRows } from '@/lib/evaluation';

function dimension(
  name: string,
  score: number,
  overrides: Partial<DimensionScoreView> = {},
): DimensionScoreView {
  return {
    dimension: name,
    label: name.replace(/_/g, ' '),
    score,
    note: `${name} note`,
    weight: 0.1,
    ...overrides,
  };
}

function detail(assetId: string, dimensions: DimensionScoreView[]): EvaluationDetailView {
  return {
    evaluation_id: `eval-${assetId}`,
    generated_asset_id: assetId,
    status: 'COMPLETED',
    dimensions,
    overall_score: 70,
    disposition: 'KEEP',
    disposition_reasons: [],
    strengths: [],
    concerns: [],
    rationale: '',
    error_message: null,
  } as unknown as EvaluationDetailView;
}

function ranked(assetId: string, rank: number, overall = 70): RankedAssetView {
  return {
    evaluation_id: `eval-${assetId}`,
    generated_asset_id: assetId,
    rank,
    overall_score: overall,
    recommended: rank === 1,
  } as unknown as RankedAssetView;
}

describe('comparisonColumns', () => {
  it('keeps only ranked assets that have a scored evaluation', () => {
    const columns = comparisonColumns(
      [ranked('a', 1), ranked('b', 2), ranked('c', 3)],
      [detail('a', [dimension('clarity', 80)]), detail('c', [])],
    );

    expect(columns.map((c) => c.row.generated_asset_id)).toEqual(['a']);
  });

  it('follows rank order, not the order evaluations came back in', () => {
    const columns = comparisonColumns(
      [ranked('b', 1), ranked('a', 2)],
      [detail('a', [dimension('clarity', 60)]), detail('b', [dimension('clarity', 90)])],
    );

    expect(columns.map((c) => c.row.rank)).toEqual([1, 2]);
  });
});

describe('comparisonRows', () => {
  it('aligns a dimension by name when the two evaluations ordered them differently', () => {
    // The original defect: read positionally, column two's craft score (30)
    // lands under "clarity" and its clarity score (90) under "craft".
    const columns = comparisonColumns(
      [ranked('a', 1), ranked('b', 2)],
      [
        detail('a', [dimension('clarity', 80), dimension('craft', 40)]),
        detail('b', [dimension('craft', 30), dimension('clarity', 90)]),
      ],
    );

    const rows = comparisonRows(columns);

    const clarity = rows.find((r) => r.dimension === 'clarity');
    const craft = rows.find((r) => r.dimension === 'craft');
    expect(clarity?.cells.map((c) => c.score)).toEqual([80, 90]);
    expect(craft?.cells.map((c) => c.score)).toEqual([40, 30]);
  });

  it('reports a dimension nobody scored in that column as null, never zero', () => {
    const columns = comparisonColumns(
      [ranked('a', 1), ranked('b', 2)],
      [
        detail('a', [dimension('clarity', 80), dimension('craft', 40)]),
        detail('b', [dimension('clarity', 90)]),
      ],
    );

    const rows = comparisonRows(columns);

    const craft = rows.find((r) => r.dimension === 'craft');
    expect(craft?.cells[1]?.score).toBeNull();
    expect(craft?.cells[1]?.score).not.toBe(0);
  });

  it('marks a row partial when any column is missing it', () => {
    const columns = comparisonColumns(
      [ranked('a', 1), ranked('b', 2)],
      [
        detail('a', [dimension('clarity', 80), dimension('craft', 40)]),
        detail('b', [dimension('clarity', 90)]),
      ],
    );

    const rows = comparisonRows(columns);

    expect(rows.find((r) => r.dimension === 'clarity')?.partial).toBe(false);
    expect(rows.find((r) => r.dimension === 'craft')?.partial).toBe(true);
  });

  it('includes a dimension only the second evaluation scored', () => {
    // Taking the first column's dimensions as the row set would drop this, and
    // it may be the one number that separates the two creatives.
    const columns = comparisonColumns(
      [ranked('a', 1), ranked('b', 2)],
      [
        detail('a', [dimension('clarity', 80)]),
        detail('b', [dimension('clarity', 70), dimension('regional_fit', 95)]),
      ],
    );

    const rows = comparisonRows(columns);

    expect(rows.map((r) => r.dimension)).toEqual(['clarity', 'regional_fit']);
    expect(rows[1]?.cells.map((c) => c.score)).toEqual([null, 95]);
  });

  it('labels a row from an evaluation that actually scored it', () => {
    const columns = comparisonColumns(
      [ranked('a', 1), ranked('b', 2)],
      [
        detail('a', [dimension('clarity', 80, { label: 'Clarity' })]),
        detail('b', [dimension('regional_fit', 95, { label: 'Regional fit' })]),
      ],
    );

    const rows = comparisonRows(columns);

    expect(rows.map((r) => r.label)).toEqual(['Clarity', 'Regional fit']);
  });

  it('carries the weight from a column that scored the dimension', () => {
    const columns = comparisonColumns(
      [ranked('a', 1), ranked('b', 2)],
      [
        detail('a', [dimension('clarity', 80)]),
        detail('b', [dimension('clarity', 70), dimension('regional_fit', 95, { weight: 0.25 })]),
      ],
    );

    const rows = comparisonRows(columns);

    expect(rows.find((r) => r.dimension === 'regional_fit')?.weight).toBe(0.25);
  });

  it('keeps the note beside the score it belongs to', () => {
    const columns = comparisonColumns(
      [ranked('a', 1), ranked('b', 2)],
      [
        detail('a', [dimension('clarity', 80, { note: 'reads at a glance' })]),
        detail('b', [dimension('clarity', 40, { note: 'headline fights the subject' })]),
      ],
    );

    const rows = comparisonRows(columns);

    expect(rows[0]?.cells.map((c) => c.note)).toEqual([
      'reads at a glance',
      'headline fights the subject',
    ]);
  });

  it('gives an identical pair of evaluations no partial rows', () => {
    const shared = [dimension('clarity', 80), dimension('craft', 60)];
    const columns = comparisonColumns(
      [ranked('a', 1), ranked('b', 2)],
      [detail('a', shared), detail('b', shared)],
    );

    const rows = comparisonRows(columns);

    expect(rows.every((r) => !r.partial)).toBe(true);
    expect(rows.map((r) => r.cells.map((c) => c.score))).toEqual([
      [80, 80],
      [60, 60],
    ]);
  });

  it('handles three columns with three different subsets', () => {
    const columns = comparisonColumns(
      [ranked('a', 1), ranked('b', 2), ranked('c', 3)],
      [
        detail('a', [dimension('clarity', 80)]),
        detail('b', [dimension('craft', 55)]),
        detail('c', [dimension('clarity', 60), dimension('craft', 70)]),
      ],
    );

    const rows = comparisonRows(columns);

    expect(rows.map((r) => r.dimension)).toEqual(['clarity', 'craft']);
    expect(rows[0]?.cells.map((c) => c.score)).toEqual([80, null, 60]);
    expect(rows[1]?.cells.map((c) => c.score)).toEqual([null, 55, 70]);
  });

  it('returns nothing to compare when no column carries a dimension', () => {
    expect(comparisonRows([])).toEqual([]);
  });
});
