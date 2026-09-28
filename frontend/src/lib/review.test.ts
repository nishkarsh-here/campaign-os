/**
 * Reading the review stages: evaluation and the brand check.
 *
 * The two vocabularies are the thing worth pinning. Evaluation's
 * `NEEDS_REVIEW` and the guardian's `NEEDS_REVISION` are different enums on
 * different surfaces, and a screen that renders them with the same words tells
 * a reader the two stages agreed when they were never asked the same question.
 *
 * The rest is about what does not exist: no message-fit dimension, no risk
 * score, and no backend "why it matters" field.
 */

import { describe, expect, it } from 'vitest';
import * as review from './review';
import {
  checkMeaning,
  checkTally,
  dimensionLabel,
  dispositionMeaning,
  orderChecks,
  scoreBand,
  summarise,
  verdictMeaning,
  whyItMatters,
} from './review';
import type { CheckStatus, EvaluationDetailView, GuardianCheckView } from './api';

function detail(over: Partial<EvaluationDetailView> = {}): EvaluationDetailView {
  return {
    id: 'e-1',
    generated_asset_id: 'a-1',
    status: 'COMPLETED',
    evaluator_version: 'v1',
    evaluator_model: 'mock-llm-1',
    specification_version: 2,
    dimensions: [],
    overall_score: 61.4,
    disposition: 'NEEDS_REVIEW',
    disposition_reasons: ['Overall 61.4 is above the 55.0 threshold.'],
    strengths: [],
    concerns: [],
    rationale: 'It reads as the brand, with a soft product moment.',
    error_message: null,
    error_code: null,
    can_retry: false,
    evaluated_at: '2026-01-01T10:05:00Z',
    ...over,
  };
}

function check(over: Partial<GuardianCheckView> = {}): GuardianCheckView {
  return {
    check: 'claim_safety',
    label: 'Claim safety',
    status: 'PASS',
    severity: null,
    detail: 'No prohibited claim appears in the approved copy.',
    suggested_fix: null,
    deterministic: true,
    ...over,
  };
}

describe('dispositions', () => {
  it('reads each disposition in the product’s own words', () => {
    expect(dispositionMeaning('PASS')?.label).toBe('Ready for review');
    expect(dispositionMeaning('NEEDS_REVIEW')?.label).toBe('Needs attention');
    expect(dispositionMeaning('REJECT')?.label).toBe('Not usable');
  });

  it('is null when nothing was decided, never a default verdict', () => {
    expect(dispositionMeaning(null)).toBeNull();
  });

  it('never says the same thing as a guardian verdict', () => {
    // The two enums are neighbours in a reader's mind and strangers in the
    // domain. If these labels ever collide, the screens start implying that
    // scoring and brand governance reached the same conclusion.
    expect(dispositionMeaning('NEEDS_REVIEW')?.label).not.toBe(
      verdictMeaning('NEEDS_REVISION')?.label,
    );
  });
});

describe('dimensionLabel', () => {
  it('renames only the one label that leaks schema vocabulary', () => {
    expect(dimensionLabel('plate_readiness', 'Plate readiness')).toBe('Ready to build on');
  });

  it('falls through to the server’s own label rather than guessing', () => {
    expect(dimensionLabel('brand_alignment', 'Brand alignment')).toBe('Brand alignment');
    expect(dimensionLabel('a_dimension_added_later', 'A dimension added later')).toBe(
      'A dimension added later',
    );
  });
});

describe('scoreBand', () => {
  it('reads a score without relying on colour', () => {
    expect(scoreBand(88).label).toBe('Strong');
    expect(scoreBand(75).label).toBe('Strong');
    expect(scoreBand(60).label).toBe('Adequate');
    expect(scoreBand(55).label).toBe('Adequate');
    expect(scoreBand(54).label).toBe('Weak');
  });
});

describe('summarise', () => {
  it('reports a completed judgement with its own score', () => {
    const s = summarise(detail());
    expect(s.score).toBe(61.4);
    expect(s.unjudged).toBe(false);
    expect(s.failure).toBeNull();
  });

  it('does not turn a failure into a zero', () => {
    const s = summarise(
      detail({
        status: 'FAILED',
        overall_score: null,
        disposition: null,
        error_message: 'The evaluator could not read the asset.',
        can_retry: true,
      }),
    );
    expect(s.score).toBeNull();
    expect(s.score).not.toBe(0);
    expect(s.unjudged).toBe(true);
    expect(s.failure).toBe('The evaluator could not read the asset.');
    expect(s.canRetry).toBe(true);
  });

  it('separates “still running” from “judged badly”', () => {
    const running = summarise(detail({ status: 'RUNNING', overall_score: null, disposition: null }));
    expect(running.unjudged).toBe(true);
    // Running is not a failure, so there is no failure sentence to show.
    expect(running.failure).toBeNull();
  });

  it('ignores a stale score on a row that is not complete', () => {
    expect(summarise(detail({ status: 'FAILED', overall_score: 61.4 })).score).toBeNull();
  });
});

describe('guardian checks', () => {
  it('reads each check status as a word', () => {
    expect(checkMeaning('PASS').label).toBe('Passed');
    expect(checkMeaning('WARN').label).toBe('Worth a look');
    expect(checkMeaning('FAIL').label).toBe('Failed');
    expect(checkMeaning('NOT_APPLICABLE').label).toBe('Not applicable');
  });

  it('does not leak a raw enum for a status it has not met', () => {
    expect(checkMeaning('DEFERRED').label).not.toMatch(/_/);
  });

  it('reads each verdict, including the absence of one', () => {
    expect(verdictMeaning('PASS')?.label).toBe('Within the brand’s rules');
    expect(verdictMeaning('NEEDS_REVISION')?.label).toBe('Needs changes');
    expect(verdictMeaning('REJECT')?.label).toBe('Cannot ship');
    expect(verdictMeaning('UNKNOWN')?.label).toBe('No verdict');
    expect(verdictMeaning(null)).toBeNull();
  });

  it('puts what needs a human first, and not-applicable last', () => {
    const ordered = orderChecks([
      check({ check: 'a', status: 'PASS' }),
      check({ check: 'b', status: 'NOT_APPLICABLE' }),
      check({ check: 'c', status: 'FAIL' }),
      check({ check: 'd', status: 'WARN' }),
    ]);
    expect(ordered.map((c) => c.check)).toEqual(['c', 'd', 'a', 'b']);
  });

  it('keeps the backend’s order within a status', () => {
    const ordered = orderChecks([
      check({ check: 'first', status: 'FAIL' }),
      check({ check: 'second', status: 'FAIL' }),
    ]);
    expect(ordered.map((c) => c.check)).toEqual(['first', 'second']);
  });

  it('does not mutate the view it was handed', () => {
    const checks = [check({ check: 'a', status: 'PASS' }), check({ check: 'b', status: 'FAIL' })];
    orderChecks(checks);
    expect(checks.map((c) => c.check)).toEqual(['a', 'b']);
  });

  it('counts the checks rather than estimating them', () => {
    const statuses: CheckStatus[] = ['PASS', 'PASS', 'WARN', 'FAIL', 'NOT_APPLICABLE'];
    const tally = checkTally(
      statuses.map((status, i) =>
        check({ check: `c-${i}`, status, deterministic: status === 'FAIL' }),
      ),
    );
    expect(tally).toEqual({
      total: 5,
      passed: 2,
      warned: 1,
      failed: 1,
      notApplicable: 1,
      deterministic: 1,
    });
  });
});

describe('whyItMatters', () => {
  it('explains each check the backend actually emits', () => {
    // The eight real check ids, verified against a live guardian payload.
    for (const id of [
      'claim_safety',
      'brand_restrictions',
      'color_constraints',
      'brand_tone',
      'visual_identity',
      'product_representation',
      'logo_readiness',
      'policy_compliance',
    ]) {
      expect(whyItMatters(id), id).toBeTruthy();
    }
  });

  it('says nothing about a check it does not know', () => {
    // A generic platitude beside a model's finding reads as the model's own
    // reasoning. Silence is the honest answer.
    expect(whyItMatters('some_future_check')).toBeNull();
  });
});

describe('what this module deliberately does not provide', () => {
  it('has no message-fit dimension and no risk score', () => {
    // The brief asked for both. Neither exists on the contract, so there is no
    // helper here that could put one on a screen.
    const surface = Object.keys(review).join(' ').toLowerCase();
    expect(surface).not.toMatch(/messagefit|message_fit/);
    expect(surface).not.toMatch(/risk/);
  });
});
