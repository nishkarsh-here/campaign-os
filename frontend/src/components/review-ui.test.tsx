// @vitest-environment jsdom

/**
 * The generate, evaluate and brand-review screens.
 *
 * These tests are mostly about honesty rather than layout. Three claims the
 * product must never make are pinned here: that a visual belongs to a creative
 * direction, that an unscored plate scored badly, and that a brand check which
 * never finished amounts to brand approval.
 *
 * Nothing here asserts on pixels or screenshots. What is asserted is the text a
 * person reads, the roles a screen reader announces, and which controls exist
 * for which capability.
 */

import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { GenerationStudio } from './generation-studio';
import { EvaluationStudio } from './evaluation-studio';
import { GuardianReview } from './guardian-review';
import { capabilitiesFor } from '@/lib/capabilities';
import type {
  CheckStatus,
  EvaluationDetailView,
  EvaluationView,
  GeneratedAssetView,
  GenerationJobView,
  GenerationView,
  GuardianCheckView,
  GuardianResultView,
  GuardianView,
  RankedAssetView,
} from '@/lib/api';

/** Full rights, so a hidden control is never a false negative. */
const admin = capabilitiesFor('admin');
/** Makes work, cannot sign it off. */
const designer = capabilitiesFor('designer');
/** Reads only. */
const viewer = capabilitiesFor('viewer');

const noop = () => undefined;

// ----------------------------------------------------------------- fixtures

function job(over: Partial<GenerationJobView> = {}): GenerationJobView {
  return {
    id: 'j-1',
    provider: 'mock',
    model: 'mock-image-1',
    status: 'COMPLETED',
    attempt: 1,
    can_retry: false,
    error_message: null,
    error_code: null,
    started_at: '2026-01-01T10:00:00Z',
    finished_at: '2026-01-01T10:00:02Z',
    created_at: '2026-01-01T10:00:00Z',
    ...over,
  };
}

function asset(over: Partial<GeneratedAssetView> = {}): GeneratedAssetView {
  return {
    id: 'a-1',
    generation_job_id: 'j-1',
    provider: 'mock',
    model: 'mock-image-1',
    kind: 'VISUAL_PLATE' as GeneratedAssetView['kind'],
    width: 1080,
    height: 1350,
    mime_type: 'image/png',
    url: '/v1/assets/a-1/bytes',
    specification_version: 2,
    created_at: '2026-01-01T10:00:02Z',
    ...over,
  };
}

function generation(over: Partial<GenerationView> = {}): GenerationView {
  return {
    campaign_id: 'c-1',
    batch_id: 'b-1',
    canonical_prompt: null,
    prompts: [],
    jobs: [job()],
    assets: [asset()],
    outcome: '1/1 providers succeeded.',
    complete: true,
    specification_version: 2,
    can_generate: true,
    blocked_reason: null,
    ...over,
  };
}

/** The ten dimensions a live evaluation actually returns. */
const DIMENSIONS = [
  'brand_alignment',
  'campaign_objective_fit',
  'audience_fit',
  'creative_direction_alignment',
  'visual_quality',
  'composition',
  'product_representation',
  'regional_fit',
  'reference_style_alignment',
  'plate_readiness',
] as const;

function dimensionScores() {
  return DIMENSIONS.map((dimension, i) => ({
    dimension,
    label: dimension.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()),
    score: 50 + i * 3,
    note: `What the model said about ${dimension}.`,
    weight: 0.1,
  }));
}

function evaluation(over: Partial<EvaluationDetailView> = {}): EvaluationDetailView {
  return {
    id: 'e-1',
    generated_asset_id: 'a-1',
    status: 'COMPLETED',
    evaluator_version: 'v1',
    evaluator_model: 'mock-llm-1',
    specification_version: 2,
    dimensions: dimensionScores(),
    overall_score: 61.4,
    disposition: 'NEEDS_REVIEW',
    disposition_reasons: ['Overall 61.4 is above the 55.0 threshold.'],
    strengths: ['The palette is unmistakably the brand’s.'],
    concerns: ['The product sits too far from the eye line.'],
    rationale: 'It reads as the brand, with a soft product moment.',
    error_message: null,
    error_code: null,
    can_retry: false,
    evaluated_at: '2026-01-01T10:05:00Z',
    ...over,
  };
}

function ranked(over: Partial<RankedAssetView> = {}): RankedAssetView {
  return {
    rank: 1,
    generated_asset_id: 'a-1',
    evaluation_id: 'e-1',
    overall_score: 61.4,
    disposition: 'NEEDS_REVIEW',
    reason: 'Highest overall, strongest on brand alignment.',
    recommended: true,
    asset: asset(),
    ...over,
  };
}

function evaluationView(over: Partial<EvaluationView> = {}): EvaluationView {
  return {
    campaign_id: 'c-1',
    evaluator_version: 'v1',
    ranked: [ranked()],
    recommendation: {
      generated_asset_id: 'a-1',
      rank: 1,
      overall_score: 61.4,
      reason: 'It answers the objective most directly of the three.',
      caveat: null,
    },
    evaluations: [evaluation()],
    outcome: '1/1 creatives scored.',
    in_flight: 0,
    unevaluated_asset_ids: [],
    selected_asset_id: null,
    can_evaluate: true,
    blocked_reason: null,
    ...over,
  };
}

/** The eight checks a live guardian payload actually carries. */
const CHECKS: { check: string; label: string; deterministic: boolean }[] = [
  { check: 'claim_safety', label: 'Claim safety', deterministic: true },
  { check: 'brand_restrictions', label: 'Brand restrictions', deterministic: true },
  { check: 'color_constraints', label: 'Colour constraints', deterministic: true },
  { check: 'brand_tone', label: 'Brand tone', deterministic: false },
  { check: 'visual_identity', label: 'Visual identity', deterministic: false },
  { check: 'product_representation', label: 'Product representation', deterministic: false },
  { check: 'logo_readiness', label: 'Logo readiness', deterministic: false },
  { check: 'policy_compliance', label: 'Policy compliance', deterministic: false },
];

function checks(statuses: Partial<Record<string, CheckStatus>> = {}): GuardianCheckView[] {
  return CHECKS.map((c) => ({
    check: c.check,
    label: c.label,
    status: statuses[c.check] ?? 'PASS',
    severity: null,
    detail: `What the ${c.label.toLowerCase()} check found.`,
    suggested_fix: null,
    deterministic: c.deterministic,
  }));
}

function guardianResult(over: Partial<GuardianResultView> = {}): GuardianResultView {
  return {
    id: 'g-1',
    generated_asset_id: 'a-1',
    status: 'COMPLETED',
    guardian_version: 'v1',
    guardian_model: 'mock-llm-1',
    specification_version: 2,
    verdict: 'PASS',
    checks: checks(),
    critical_issues: [],
    warnings: [],
    summary: 'Nothing in this visual contradicts the brand’s own rules.',
    error_message: null,
    error_code: null,
    can_retry: false,
    evaluated_at: '2026-01-01T10:10:00Z',
    asset: asset(),
    ...over,
  };
}

function guardianView(over: Partial<GuardianView> = {}): GuardianView {
  return {
    campaign_id: 'c-1',
    guardian_version: 'v1',
    results: [guardianResult()],
    in_flight: 0,
    unchecked_asset_ids: [],
    can_check: true,
    blocked_reason: null,
    ...over,
  };
}

function studio(view: GenerationView, capabilities = admin, extra: Record<string, unknown> = {}) {
  return render(
    <GenerationStudio
      view={view}
      capabilities={capabilities}
      busy={false}
      onGenerate={noop}
      onRetry={noop}
      {...extra}
    />,
  );
}

function evaluate(view: EvaluationView, capabilities = admin, extra: Record<string, unknown> = {}) {
  return render(
    <EvaluationStudio
      view={view}
      capabilities={capabilities}
      busy={false}
      onEvaluate={noop}
      onRetry={noop}
      onSelect={noop}
      {...extra}
    />,
  );
}

function guardian(view: GuardianView, capabilities = admin, extra: Record<string, unknown> = {}) {
  return render(
    <GuardianReview
      view={view}
      capabilities={capabilities}
      busy={false}
      pending={false}
      onCheck={noop}
      onRetry={noop}
      onGiveFeedback={noop}
      {...extra}
    />,
  );
}

/** Open a `<details>` by its summary text. */
function disclose(label: RegExp) {
  fireEvent.click(screen.getByText(label));
}

// ---------------------------------------------------------------- GENERATE

describe('GenerationStudio — job states', () => {
  it('shows a queued job as queued, in the frame the image will fill', () => {
    studio(generation({ jobs: [job({ status: 'PENDING' })], assets: [] }));
    expect(screen.getAllByText('Queued').length).toBeGreaterThan(0);
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('shows a running job as working, not as finished', () => {
    studio(generation({ jobs: [job({ status: 'RUNNING' })], assets: [] }));
    expect(screen.getAllByText('Creating visual').length).toBeGreaterThan(0);
    expect(screen.queryByText('Visual ready')).toBeNull();
  });

  it('shows a completed job as its image', () => {
    studio(generation());
    const img = screen.getByRole('img');
    // Alt text says what the picture is and where it came from.
    expect(img.getAttribute('alt')).toBe('Visual from Demo generator, 1080 by 1350 pixels');
    expect(screen.getByText('Visual ready')).toBeTruthy();
  });

  it('frames a plate in its own aspect ratio, from the real pixel dimensions', () => {
    studio(generation({ assets: [asset({ width: 1080, height: 1920 })] }));
    const frame = screen.getByRole('img').parentElement;
    expect(frame?.getAttribute('style')).toContain('1080 / 1920');
  });

  it('reports a failure in the server’s own words, as an alert', () => {
    studio(
      generation({
        jobs: [
          job({
            status: 'FAILED',
            can_retry: true,
            error_message: 'The provider refused the request.',
          }),
        ],
        assets: [],
        outcome: '0/1 providers succeeded — 1 failed.',
      }),
    );
    const alert = screen.getByRole('alert');
    expect(within(alert).getByText('The provider refused the request.')).toBeTruthy();
    expect(within(alert).getByRole('button', { name: 'Try this provider again' })).toBeTruthy();
  });

  it('does not offer a retry the backend says is not available', () => {
    studio(generation({ jobs: [job({ status: 'FAILED', can_retry: false })], assets: [] }));
    expect(screen.queryByRole('button', { name: 'Try this provider again' })).toBeNull();
  });

  it('treats a partial success as a partial success, not as an error', () => {
    studio(
      generation({
        jobs: [
          job({ id: 'j-1', provider: 'mock', status: 'COMPLETED' }),
          job({ id: 'j-2', provider: 'gemini', status: 'COMPLETED' }),
          job({ id: 'j-3', provider: 'leonardo', status: 'FAILED', error_message: 'Timed out.' }),
        ],
        assets: [
          asset({ id: 'a-1', generation_job_id: 'j-1' }),
          asset({ id: 'a-2', generation_job_id: 'j-2', provider: 'gemini' }),
        ],
        outcome: '2/3 providers succeeded — 1 failed.',
      }),
    );
    expect(screen.getByText('2/3 providers succeeded — 1 failed.')).toBeTruthy();
    // The two that worked are still shown as work.
    expect(screen.getAllByRole('img')).toHaveLength(2);
    expect(screen.getByText('Timed out.')).toBeTruthy();
  });

  it('shows one slot per provider, not one per superseded attempt', () => {
    studio(
      generation({
        jobs: [
          job({ id: 'j-1', attempt: 1, status: 'FAILED', error_message: 'First try failed.' }),
          job({ id: 'j-2', attempt: 2, status: 'COMPLETED' }),
        ],
        assets: [asset({ generation_job_id: 'j-2' })],
      }),
    );
    expect(screen.getAllByRole('heading', { level: 3 })).toHaveLength(1);
    expect(screen.queryByText('First try failed.')).toBeNull();
  });
});

describe('GenerationStudio — what it refuses to claim', () => {
  it('never attributes a visual to a creative direction', () => {
    // `GenerationView` carries no direction id, ordinal or title. A slot
    // titled "Direction 01" would be an association the backend never made.
    studio(
      generation({
        jobs: [job({ id: 'j-1' }), job({ id: 'j-2', provider: 'gemini' })],
        assets: [asset({ generation_job_id: 'j-1' })],
      }),
    );
    expect(screen.queryByText(/direction/i)).toBeNull();
  });

  it('names the mock provider as a demo generator and says nothing left the machine', () => {
    studio(generation());
    expect(screen.getByRole('heading', { level: 3 }).textContent).toBe('Demo generator');
    expect(screen.getByText('Offline demo output. Nothing left this machine.')).toBeTruthy();
    expect(screen.queryByText(/gemini/i)).toBeNull();
  });

  it('does not attach the offline note to a provider that is not offline', () => {
    studio(generation({ jobs: [job({ provider: 'gemini' })], assets: [] }));
    expect(screen.queryByText(/nothing left this machine/i)).toBeNull();
  });

  it('offers only technical facts the API carries', () => {
    studio(generation());
    disclose(/Generation details/);
    expect(screen.getByText('Job id')).toBeTruthy();
    expect(screen.getByText('Took')).toBeTruthy();
    expect(screen.getByText('1080 × 1350')).toBeTruthy();
    // None of these exist on the contract.
    expect(screen.queryByText('Request id')).toBeNull();
    expect(screen.queryByText('Seed')).toBeNull();
    expect(screen.queryByText('Latency')).toBeNull();
  });

  it('keeps the technical facts folded away until asked', () => {
    studio(generation());
    // jsdom keeps a closed `<details>` in the DOM — the browser hides it — so
    // what there is to assert is that it starts closed.
    expect(screen.getByText(/Generation details/).closest('details')?.hasAttribute('open')).toBe(
      false,
    );
  });
});

describe('GenerationStudio — capability presentation and empty states', () => {
  it('offers no generate control to someone who cannot edit the campaign', () => {
    studio(generation({ jobs: [], assets: [] }), viewer);
    expect(screen.getByText('No visuals yet')).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('offers the control to a designer, who makes the work', () => {
    studio(generation({ jobs: [], assets: [] }), designer);
    expect(screen.getByRole('button', { name: 'Generate campaign visuals' })).toBeTruthy();
  });

  it('states the backend’s own reason when generation is not open', () => {
    studio(
      generation({
        jobs: [],
        assets: [],
        can_generate: false,
        blocked_reason: 'The creative plan has not been approved.',
      }),
    );
    expect(screen.getByText('The creative plan has not been approved.')).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('calls back with the job the retry belongs to', () => {
    const onRetry = vi.fn();
    studio(
      generation({ jobs: [job({ id: 'j-9', status: 'FAILED', can_retry: true })], assets: [] }),
      admin,
      { onRetry },
    );
    fireEvent.click(screen.getByRole('button', { name: 'Try this provider again' }));
    expect(onRetry).toHaveBeenCalledWith('j-9');
  });
});

// ---------------------------------------------------------------- EVALUATE

describe('EvaluationStudio — the real dimensions', () => {
  it('shows every dimension the evaluator returned, with its share of the total', () => {
    evaluate(evaluationView());
    disclose(/How this score was reached/);
    expect(screen.getByText('Brand alignment')).toBeTruthy();
    expect(screen.getByText('Regional fit')).toBeTruthy();
    expect(screen.getAllByText('10% of the total')).toHaveLength(DIMENSIONS.length);
  });

  it('renames only the dimension whose server label leaks schema vocabulary', () => {
    evaluate(evaluationView());
    disclose(/How this score was reached/);
    expect(screen.getByText('Ready to build on')).toBeTruthy();
    expect(screen.queryByText('Plate readiness')).toBeNull();
  });

  it('shows the rule that produced the disposition, in the service’s words', () => {
    evaluate(evaluationView());
    disclose(/How this score was reached/);
    expect(screen.getByText('Overall 61.4 is above the 55.0 threshold.')).toBeTruthy();
  });

  it('invents no dimension the backend does not score', () => {
    evaluate(evaluationView());
    disclose(/How this score was reached/);
    // The brief asked for message fit and a risk score. Neither exists.
    expect(screen.queryByText(/message fit/i)).toBeNull();
    expect(screen.queryByText(/risk/i)).toBeNull();
  });

  it('labels the model’s concerns as something to watch, not as a score', () => {
    evaluate(evaluationView());
    expect(screen.getByText('What works')).toBeTruthy();
    expect(screen.getByText('What to watch')).toBeTruthy();
    expect(screen.getByText('The product sits too far from the eye line.')).toBeTruthy();
  });
});

describe('EvaluationStudio — recommendation and human decision', () => {
  it('puts the recommendation and the human decision side by side', () => {
    evaluate(evaluationView());
    expect(screen.getByText('AI recommendation')).toBeTruthy();
    expect(screen.getByText('Human decision')).toBeTruthy();
    expect(screen.getByText('It answers the objective most directly of the three.')).toBeTruthy();
    expect(screen.getByText(/A recommendation, not a decision/)).toBeTruthy();
  });

  it('shows the caveat when the best available creative is not actually good', () => {
    evaluate(
      evaluationView({
        recommendation: {
          generated_asset_id: 'a-1',
          rank: 1,
          overall_score: 41.2,
          reason: 'The strongest of the three.',
          caveat: 'All three scored below the threshold.',
        },
      }),
    );
    expect(screen.getByText('All three scored below the threshold.')).toBeTruthy();
  });

  it('lets the recommendation decline rather than naming a least-bad winner', () => {
    evaluate(
      evaluationView({
        recommendation: {
          generated_asset_id: null,
          rank: null,
          overall_score: null,
          reason: 'Every creative was rejected.',
          caveat: null,
        },
      }),
    );
    expect(screen.getByText('No recommendation available.')).toBeTruthy();
    expect(screen.getByText('Every creative was rejected.')).toBeTruthy();
  });

  it('takes a human selection, with an optional reason', () => {
    const onSelect = vi.fn();
    evaluate(evaluationView(), admin, { onSelect });
    fireEvent.click(screen.getByRole('button', { name: 'Select this creative' }));
    const note = screen.getByLabelText('Why this one? (optional)');
    fireEvent.change(note, { target: { value: 'The light is right for the season.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Select this creative' }));
    expect(onSelect).toHaveBeenCalledWith('a-1', 'The light is right for the season.');
  });

  it('does not offer selection to someone without approval rights', () => {
    // A designer makes the work; signing off is a different job.
    evaluate(evaluationView(), designer);
    expect(screen.queryByRole('button', { name: 'Select this creative' })).toBeNull();
    expect(screen.getByText(/needs approval rights/)).toBeTruthy();
  });

  it('says which creative is already the campaign’s', () => {
    evaluate(evaluationView({ selected_asset_id: 'a-1' }));
    expect(screen.getByText('This is the campaign’s creative')).toBeTruthy();
  });
});

describe('EvaluationStudio — not scored is not a low score', () => {
  it('lists an unjudged creative separately, and says what it is', () => {
    evaluate(
      evaluationView({
        ranked: [],
        recommendation: null,
        evaluations: [
          evaluation({
            status: 'FAILED',
            overall_score: null,
            disposition: null,
            dimensions: [],
            error_message: 'The evaluator could not read the asset.',
            can_retry: true,
          }),
        ],
        outcome: '0/1 creatives scored.',
      }),
    );
    expect(screen.getByRole('heading', { name: 'Not scored' })).toBeTruthy();
    expect(screen.getByText(/These are not low scores/)).toBeTruthy();
    expect(screen.getByText('The evaluator could not read the asset.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy();
    // And no zero is printed anywhere in its place.
    expect(screen.queryByText('0.0')).toBeNull();
  });

  it('offers nothing to retry to someone who cannot edit the campaign', () => {
    evaluate(
      evaluationView({
        ranked: [],
        recommendation: null,
        evaluations: [
          evaluation({ status: 'FAILED', overall_score: null, disposition: null, can_retry: true }),
        ],
      }),
      viewer,
    );
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
  });

  it('scopes the remaining-work control to the creatives that have none', () => {
    const onEvaluate = vi.fn();
    evaluate(evaluationView({ unevaluated_asset_ids: ['a-2', 'a-3'] }), admin, { onEvaluate });
    fireEvent.click(screen.getByRole('button', { name: 'Score the remaining 2 visuals' }));
    expect(onEvaluate).toHaveBeenCalledWith(['a-2', 'a-3']);
    // And only one run control, so there is one next action for one question.
    expect(screen.queryByRole('button', { name: /every visual again/ })).toBeNull();
  });

  it('re-scores everything, with no narrowing, once nothing is outstanding', () => {
    const onEvaluate = vi.fn();
    evaluate(evaluationView(), admin, { onEvaluate });
    fireEvent.click(screen.getByRole('button', { name: 'Score every visual again' }));
    expect(onEvaluate).toHaveBeenCalledWith();
  });

  it('does not repeat the ranked creative’s own sentence in the recommendation', () => {
    // Both come from the same ranking, so `reason` is frequently identical.
    evaluate(
      evaluationView({
        ranked: [ranked({ reason: 'Highest overall, strongest on brand alignment.' })],
        recommendation: {
          generated_asset_id: 'a-1',
          rank: 1,
          overall_score: 61.4,
          reason: 'Highest overall, strongest on brand alignment.',
          caveat: null,
        },
      }),
    );
    expect(screen.getAllByText('Highest overall, strongest on brand alignment.')).toHaveLength(1);
    expect(screen.getByText(/is on the ranked creative below/)).toBeTruthy();
  });

  it('says how many are still scoring rather than going quiet', () => {
    evaluate(evaluationView({ in_flight: 2 }));
    expect(screen.getByText('2 still scoring')).toBeTruthy();
  });

  it('states the backend’s reason when there is nothing to score', () => {
    evaluate(
      evaluationView({
        ranked: [],
        evaluations: [],
        recommendation: null,
        can_evaluate: false,
        blocked_reason: 'Generate some visuals first.',
      }),
    );
    expect(screen.getByText('Nothing scored yet')).toBeTruthy();
    expect(screen.getByText('Generate some visuals first.')).toBeTruthy();
  });
});

// ------------------------------------------------------------ BRAND REVIEW

describe('GuardianReview — checks and verdict', () => {
  it('renders every check with what it found', () => {
    guardian(guardianView());
    for (const c of CHECKS) {
      expect(screen.getByText(c.label), c.check).toBeTruthy();
    }
    expect(screen.getAllByText(/What the .* check found\./)).toHaveLength(CHECKS.length);
  });

  it('puts what needs a human first', () => {
    guardian(
      guardianView({
        results: [
          guardianResult({
            verdict: 'NEEDS_REVISION',
            checks: checks({ brand_tone: 'WARN', logo_readiness: 'FAIL' }),
          }),
        ],
      }),
    );
    // Scoped to the list of checks: the card itself is a list item too.
    const list = screen.getByText('Logo readiness').closest('ul');
    const labels = [...(list?.children ?? [])].map((li) => li.querySelector('p')?.textContent);
    expect(labels[0]).toBe('Logo readiness');
    expect(labels[1]).toBe('Brand tone');
  });

  it('reads each check state as a word, never as colour alone', () => {
    guardian(
      guardianView({
        results: [
          guardianResult({
            verdict: 'NEEDS_REVISION',
            checks: checks({
              brand_tone: 'WARN',
              logo_readiness: 'FAIL',
              color_constraints: 'NOT_APPLICABLE',
            }),
          }),
        ],
      }),
    );
    expect(screen.getByText('Failed')).toBeTruthy();
    expect(screen.getByText('Worth a look')).toBeTruthy();
    expect(screen.getByText('Not applicable')).toBeTruthy();
    expect(screen.getAllByText('Passed').length).toBe(5);
  });

  it('states the verdict once, so there is nothing to reconcile', () => {
    guardian(guardianView());
    expect(screen.getAllByText('Within the brand’s rules')).toHaveLength(1);
  });

  it('does not print the verdict again when the backend summary is the verdict', () => {
    // A real clean pass comes back with `summary` set to "Within the brand's
    // rules." — the verdict label, in the backend's own punctuation. Printed
    // beside the heading it put the verdict on the card three times.
    guardian(
      guardianView({
        results: [guardianResult({ summary: "Within the brand's rules." })],
      }),
    );
    expect(screen.getAllByText(/within the brand.s rules/i)).toHaveLength(1);
    // And the supporting sentence is still there, so the card is not bare.
    expect(screen.getByText('Nothing checked contradicts what the brand allows.')).toBeTruthy();
  });

  it('prefers the backend’s sentence when it says something about this visual', () => {
    guardian(
      guardianView({
        results: [guardianResult({ summary: 'The palette leans warmer than usual but holds.' })],
      }),
    );
    expect(screen.getByText('The palette leans warmer than usual but holds.')).toBeTruthy();
    expect(screen.queryByText('Nothing checked contradicts what the brand allows.')).toBeNull();
  });

  it('reads a rejection as a rejection', () => {
    guardian(
      guardianView({
        results: [
          guardianResult({
            verdict: 'REJECT',
            checks: checks({ claim_safety: 'FAIL' }),
            critical_issues: ['The headline implies a performance claim the brand prohibits.'],
          }),
        ],
      }),
    );
    expect(screen.getByText('Cannot ship')).toBeTruthy();
    const alert = screen.getByRole('alert');
    expect(
      within(alert).getByText('The headline implies a performance claim the brand prohibits.'),
    ).toBeTruthy();
  });

  it('counts the checks behind the verdict rather than estimating them', () => {
    guardian(
      guardianView({
        results: [
          guardianResult({
            verdict: 'NEEDS_REVISION',
            checks: checks({ brand_tone: 'WARN', logo_readiness: 'FAIL' }),
          }),
        ],
      }),
    );
    expect(screen.getByText(/6 passed · 1 to look at · 1 failed · 3 decided by code/)).toBeTruthy();
  });

  it('says which findings are facts and which are opinions', () => {
    guardian(guardianView());
    // Three deterministic checks in a live payload; the rest are model judgement.
    expect(screen.getAllByText('Decided by code')).toHaveLength(3);
    expect(
      screen.getAllByText('Judged by a model — a second opinion, not a fact'),
    ).toHaveLength(CHECKS.length - 3);
  });

  it('attributes its own explanation to itself, not to the model', () => {
    guardian(guardianView());
    const explanations = screen.getAllByText('Campaign OS');
    expect(explanations.length).toBe(CHECKS.length);
  });

  it('says nothing about a check it has no explanation for', () => {
    guardian(
      guardianView({
        results: [
          guardianResult({
            checks: [
              {
                check: 'some_future_check',
                label: 'Some future check',
                status: 'PASS',
                severity: null,
                detail: 'It passed.',
                suggested_fix: null,
                deterministic: false,
              },
            ],
          }),
        ],
      }),
    );
    expect(screen.getByText('Some future check')).toBeTruthy();
    // No generic platitude in place of an explanation nobody wrote.
    expect(screen.queryByText('Campaign OS')).toBeNull();
  });

  it('shows the fix the backend supplied, and nothing when it supplied none', () => {
    guardian(
      guardianView({
        results: [
          guardianResult({
            verdict: 'NEEDS_REVISION',
            checks: checks({ logo_readiness: 'FAIL' }).map((c) =>
              c.check === 'logo_readiness'
                ? { ...c, suggested_fix: 'Leave the lower third quiet for the logo.' }
                : c,
            ),
          }),
        ],
      }),
    );
    expect(screen.getByText('Leave the lower third quiet for the logo.')).toBeTruthy();
    expect(screen.getAllByText('What to do')).toHaveLength(1);
  });

  it('names the guardian and the plan version it judged against', () => {
    guardian(guardianView());
    expect(screen.getByText(/Guardian v1 · mock-llm-1 · judged against creative plan v2/)).toBeTruthy();
  });
});

describe('GuardianReview — job states', () => {
  it('shows a check in flight as checking, not as broken', () => {
    guardian(
      guardianView({
        in_flight: 1,
        results: [
          guardianResult({ status: 'RUNNING', verdict: null, checks: [], summary: '' }),
        ],
      }),
      admin,
      { pending: true },
    );
    const card = screen.getByRole('listitem');
    expect(within(card).getByText('Checking…')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('never lets a failed check read as brand approval', () => {
    guardian(
      guardianView({
        results: [
          guardianResult({
            status: 'FAILED',
            verdict: null,
            checks: [],
            summary: '',
            error_message: 'The brand check could not reach the model.',
            error_code: 'PROVIDER_ERROR',
            can_retry: true,
          }),
        ],
      }),
    );
    const alert = screen.getByRole('alert');
    expect(within(alert).getByText('Not checked')).toBeTruthy();
    expect(within(alert).getByText('The brand check could not reach the model.')).toBeTruthy();
    expect(within(alert).getByRole('button', { name: 'Run it again' })).toBeTruthy();
    expect(screen.queryByText('Within the brand’s rules')).toBeNull();
  });

  it('shows the visual being checked, with alt text that says so', () => {
    guardian(guardianView());
    expect(screen.getByRole('img').getAttribute('alt')).toBe(
      'Visual being brand-checked, from Demo generator',
    );
  });

  it('says the visual is unavailable rather than drawing an empty frame', () => {
    guardian(guardianView({ results: [guardianResult({ asset: null })] }));
    expect(screen.getByText('Visual unavailable')).toBeTruthy();
    expect(screen.queryByRole('img')).toBeNull();
  });
});

describe('GuardianReview — controls and capability presentation', () => {
  it('offers one check control, scoped to the visuals that have none', () => {
    const onCheck = vi.fn();
    guardian(guardianView({ unchecked_asset_ids: ['a-2', 'a-3'] }), admin, { onCheck });
    const button = screen.getByRole('button', { name: 'Check the remaining 2 visuals' });
    fireEvent.click(button);
    expect(onCheck).toHaveBeenCalledWith(['a-2', 'a-3']);
    // And only one control, so there is one next action for one question.
    expect(screen.queryByRole('button', { name: /every visual again/ })).toBeNull();
  });

  it('counts one remaining visual as one', () => {
    guardian(guardianView({ unchecked_asset_ids: ['a-2'] }));
    expect(screen.getByRole('button', { name: 'Check the remaining visual' })).toBeTruthy();
  });

  it('re-checks everything, with no narrowing, once nothing is outstanding', () => {
    const onCheck = vi.fn();
    guardian(guardianView(), admin, { onCheck });
    fireEvent.click(screen.getByRole('button', { name: 'Check every visual again' }));
    expect(onCheck).toHaveBeenCalledWith();
  });

  it('offers no check control while one is in flight', () => {
    guardian(guardianView(), admin, { pending: true });
    expect(screen.getByRole('button', { name: 'Checking…' }).hasAttribute('disabled')).toBe(true);
  });

  it('offers no control at all to someone who cannot edit the campaign', () => {
    guardian(guardianView({ unchecked_asset_ids: ['a-2'] }), viewer);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('routes a failing visual into refinement, carrying the asset it is about', () => {
    const onGiveFeedback = vi.fn();
    guardian(
      guardianView({
        results: [
          guardianResult({
            generated_asset_id: 'a-7',
            verdict: 'NEEDS_REVISION',
            checks: checks({ brand_tone: 'WARN' }),
          }),
        ],
      }),
      admin,
      { onGiveFeedback },
    );
    fireEvent.click(screen.getByRole('button', { name: 'Refine this visual' }));
    expect(onGiveFeedback).toHaveBeenCalledWith('a-7');
  });

  it('offers no refinement route for a visual that passed', () => {
    guardian(guardianView());
    expect(screen.queryByRole('button', { name: 'Refine this visual' })).toBeNull();
  });

  it('invites the first check when none has run', () => {
    const onCheck = vi.fn();
    guardian(guardianView({ results: [] }), admin, { onCheck });
    fireEvent.click(screen.getByRole('button', { name: 'Run the brand check' }));
    expect(onCheck).toHaveBeenCalledWith();
  });

  it('states the backend’s reason when there is nothing to check', () => {
    guardian(
      guardianView({
        results: [],
        can_check: false,
        blocked_reason: 'Generate creatives before brand-checking them.',
      }),
    );
    expect(screen.getByText('Generate creatives before brand-checking them.')).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('says the check advises and a person decides', () => {
    guardian(guardianView());
    expect(screen.getByText(/The Brand Guardian advises/)).toBeTruthy();
  });
});

describe('all three screens — a visual whose bytes do not arrive', () => {
  it('says the visual could not be loaded, rather than captioning a dark box', () => {
    // A broken `<img>` renders as its own alt text, which reads like a caption
    // on a picture that is simply dark. On the brand review especially, a
    // verdict beside an image nobody can see has to say so.
    guardian(guardianView());
    fireEvent.error(screen.getByRole('img'));
    expect(screen.getByText('Visual could not be loaded')).toBeTruthy();
    expect(screen.queryByRole('img')).toBeNull();
    // The verdict is still there; the failure is about the picture only.
    expect(screen.getByText('Within the brand’s rules')).toBeTruthy();
  });

  it('does the same on the generate screen', () => {
    studio(generation());
    fireEvent.error(screen.getByRole('img'));
    expect(screen.getByText('Visual could not be loaded')).toBeTruthy();
  });

  it('does the same on the evaluate screen, keeping the score readable', () => {
    evaluate(evaluationView());
    fireEvent.error(screen.getByRole('img'));
    expect(screen.getByText('Visual could not be loaded')).toBeTruthy();
    expect(screen.getByText('61.4')).toBeTruthy();
  });

  it('distinguishes a failure from there being no visual at all', () => {
    guardian(guardianView({ results: [guardianResult({ asset: null })] }));
    expect(screen.getByText('Visual unavailable')).toBeTruthy();
    expect(screen.queryByText('Visual could not be loaded')).toBeNull();
  });
});

// -------------------------------------------------------------- crosscutting

describe('all three screens — accessibility and motion', () => {
  it('reaches every action with a keyboard, because every action is a button', () => {
    const { unmount } = studio(
      generation({ jobs: [job({ status: 'FAILED', can_retry: true })], assets: [] }),
    );
    for (const b of screen.getAllByRole('button')) expect(b.tagName).toBe('BUTTON');
    unmount();

    evaluate(evaluationView());
    for (const b of screen.getAllByRole('button')) expect(b.tagName).toBe('BUTTON');
  });

  it('folds detail into a native disclosure, which is keyboard-operable', () => {
    studio(generation());
    const details = screen.getByText(/Generation details/).closest('details');
    expect(details).toBeTruthy();
    expect(details?.hasAttribute('open')).toBe(false);
    fireEvent.click(screen.getByText(/Generation details/));
    expect(details?.hasAttribute('open')).toBe(true);
  });

  it('labels the selection note, so the field is not an unnamed box', () => {
    evaluate(evaluationView());
    fireEvent.click(screen.getByRole('button', { name: 'Select this creative' }));
    const note = screen.getByLabelText('Why this one? (optional)');
    expect(note.tagName).toBe('TEXTAREA');
  });

  it('announces a failure, and only politely announces progress', () => {
    guardian(
      guardianView({
        results: [
          guardianResult({ id: 'g-1', status: 'RUNNING', verdict: null, checks: [], summary: '' }),
          guardianResult({
            id: 'g-2',
            status: 'FAILED',
            verdict: null,
            checks: [],
            summary: '',
            error_message: 'It did not finish.',
          }),
        ],
      }),
    );
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    expect(screen.getByText('Checking…').closest('[aria-live]')).toBeTruthy();
  });

  it('animates through the class the global reduced-motion rule governs', () => {
    // Motion is CSS: `globals.css` collapses `.arrive` under
    // `prefers-reduced-motion`, so what a component owes is the hook, and
    // content that is already in its final DOM position.
    guardian(guardianView());
    const item = screen.getAllByRole('listitem')[0]!.closest('.arrive');
    expect(item).toBeTruthy();
    expect(screen.getByText('Within the brand’s rules')).toBeTruthy();
  });
});
