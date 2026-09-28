// @vitest-environment jsdom

/**
 * The refine screen, where the brand review and the revision loop share a page.
 *
 * UI-2C-D wired `GuardianReview` in beside revision controls that UI-2C-E will
 * redesign. The risk of two stages on one page is that they echo each other:
 * two verdicts a reader has to reconcile, or two buttons that start the same
 * work. These tests pin that they do not, and that the revision half still
 * functions exactly as it did.
 */

import { Suspense } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { CampaignWorkspaceProvider } from '@/lib/campaign-context';
import { ApiError } from '@/lib/api';
import type {
  GuardianCheckView,
  GuardianView,
  Me,
  RevisionView,
} from '@/lib/api';
import RefinePage from './page';

// `next/link` wants the App Router context, which a unit test has no business
// mounting. The page only uses it to point somewhere.
vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const getCampaign = vi.fn();
const getGeneration = vi.fn();
const getEvaluation = vi.fn();
const getCreativeStage = vi.fn();
const getGuardian = vi.fn();
const getRevision = vi.fn();
const startGuardian = vi.fn();
const retryGuardian = vi.fn();
const proposeRevision = vi.fn();

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getCampaign: (...a: unknown[]) => getCampaign(...a),
      getGeneration: (...a: unknown[]) => getGeneration(...a),
      getEvaluation: (...a: unknown[]) => getEvaluation(...a),
      getCreativeStage: (...a: unknown[]) => getCreativeStage(...a),
      getGuardian: (...a: unknown[]) => getGuardian(...a),
      getRevision: (...a: unknown[]) => getRevision(...a),
      startGuardian: (...a: unknown[]) => startGuardian(...a),
      retryGuardian: (...a: unknown[]) => retryGuardian(...a),
      proposeRevision: (...a: unknown[]) => proposeRevision(...a),
    },
  };
});

const CHECKS: GuardianCheckView[] = [
  {
    check: 'claim_safety',
    label: 'Claim safety',
    status: 'PASS',
    severity: null,
    detail: 'No prohibited claim appears in the approved copy.',
    suggested_fix: null,
    deterministic: true,
  },
  {
    check: 'brand_tone',
    label: 'Brand tone',
    status: 'WARN',
    severity: 'minor',
    detail: 'The environment reads warmer than the brand’s usual register.',
    suggested_fix: 'Cool the grade a little.',
    deterministic: false,
  },
];

function guardian(over: Partial<GuardianView> = {}): GuardianView {
  return {
    campaign_id: 'c-1',
    guardian_version: 'v1',
    results: [
      {
        id: 'g-1',
        generated_asset_id: 'a-7',
        status: 'COMPLETED',
        guardian_version: 'v1',
        guardian_model: 'mock-llm-1',
        specification_version: 2,
        verdict: 'NEEDS_REVISION',
        checks: CHECKS,
        critical_issues: [],
        warnings: [],
        summary: 'One check wants a look before this ships.',
        error_message: null,
        error_code: null,
        can_retry: false,
        evaluated_at: '2026-01-01T10:10:00Z',
        asset: {
          id: 'a-7',
          generation_job_id: 'j-1',
          provider: 'mock',
          model: 'mock-image-1',
          kind: 'VISUAL_PLATE' as never,
          width: 1080,
          height: 1350,
          mime_type: 'image/png',
          url: '/v1/assets/a-7/bytes',
          specification_version: 2,
          created_at: '2026-01-01T10:00:02Z',
        },
      },
    ],
    in_flight: 0,
    unchecked_asset_ids: [],
    can_check: true,
    blocked_reason: null,
    ...over,
  };
}

function revision(over: Partial<RevisionView> = {}): RevisionView {
  return {
    campaign_id: 'c-1',
    current: null,
    history: [],
    diff: [],
    can_revise: true,
    blocked_reason: null,
    ...over,
  };
}

const me: Me = {
  user: { id: 'u-1', email: 'someone@example.com', display_name: 'Someone' },
  organizations: [
    {
      organization: { id: 'org-1', name: 'Northline', slug: 'northline', created_at: '' },
      role: 'admin',
    },
  ],
} as unknown as Me;

/**
 * Render the page and let its first pass settle.
 *
 * The page reads `params` with `use`, so the tree suspends on the first render
 * and React needs an awaited `act` to resume it — without one the body stays
 * empty for the whole test and every query reports a missing element.
 */
async function mount() {
  await act(async () => {
    renderPage();
  });
}

function renderPage() {
  return render(
    <CampaignWorkspaceProvider
      value={{
        campaignId: 'c-1',
        organizationId: 'org-1',
        me,
        overview: null,
        specification: null,
        creativeContext: null,
        overviewError: null,
        refresh: () => undefined,
      }}
    >
      {/* `params` is a promise the page reads with `use`, so it needs a
          boundary to suspend against — in the app that is the route segment. */}
      <Suspense fallback={null}>
        <RefinePage params={Promise.resolve({ campaignId: 'c-1' })} />
      </Suspense>
    </CampaignWorkspaceProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  getCampaign.mockResolvedValue({ id: 'c-1', status: 'SPECIFICATION_CONFIRMED' });
  getGuardian.mockResolvedValue(guardian());
  getRevision.mockResolvedValue(revision());
  startGuardian.mockResolvedValue(guardian());
  proposeRevision.mockResolvedValue({});
  // Version context. Best-effort on the page, so an empty answer is a normal
  // state rather than a failure.
  getGeneration.mockResolvedValue({
    campaign_id: 'c-1',
    batch_id: null,
    canonical_prompt: null,
    prompts: [],
    jobs: [],
    assets: [],
    outcome: '',
    complete: true,
    specification_version: 2,
    can_generate: true,
    blocked_reason: null,
  });
  getEvaluation.mockResolvedValue({
    campaign_id: 'c-1',
    evaluator_version: 'v1',
    ranked: [],
    recommendation: null,
    evaluations: [],
    outcome: '',
    in_flight: 0,
    unevaluated_asset_ids: [],
    selected_asset_id: null,
    can_evaluate: false,
    blocked_reason: null,
  });
  getCreativeStage.mockResolvedValue({ specification: null });
});

describe('the refine page', () => {
  it('reads as brand review and then refinement, under one heading each', async () => {
    await mount();
    await screen.findByRole('heading', { name: 'Brand review' });
    expect(screen.getByRole('heading', { name: 'Refinement' })).toBeTruthy();
    expect(screen.getAllByRole('heading', { name: 'Brand review' })).toHaveLength(1);
  });

  it('states a verdict once per thing it is about', async () => {
    // Three scopes legitimately carry a brand standing on this page: the
    // checked plate, the creative being refined, and the plan version. The
    // rule is one statement per object — not one string per page — so this
    // asserts the guardian card, which is where the duplicate actually was.
    await mount();
    await screen.findAllByText('Needs changes');
    const card = screen.getAllByRole('listitem').find((li) => li.querySelector('img'))!;
    expect(within(card).getAllByText('Needs changes')).toHaveLength(1);
  });

  it('offers one control that starts a brand check, not two', async () => {
    await mount();
    await screen.findByRole('heading', { name: 'Brand review' });
    const checkButtons = screen
      .getAllByRole('button')
      .filter((b) => /check/i.test(b.textContent ?? ''));
    expect(checkButtons).toHaveLength(1);
    fireEvent.click(checkButtons[0]!);
    await waitFor(() => expect(startGuardian).toHaveBeenCalledTimes(1));
    // Nothing outstanding, so the check is not narrowed to a subset.
    expect(startGuardian).toHaveBeenCalledWith('c-1', 'org-1', undefined);
  });

  it('does not tell the revision form that a brand check is thinking', async () => {
    // One busy flag for the page relabelled "Propose a revision" as
    // "Thinking…" whenever a brand check started — as though a revision were
    // being composed. The two stages are independent on the server.
    let release: (v: unknown) => void = () => undefined;
    startGuardian.mockReturnValue(new Promise((r) => (release = r)));
    await mount();
    await screen.findByRole('heading', { name: 'Brand review' });
    fireEvent.click(screen.getByRole('button', { name: /check/i }));

    await waitFor(() => expect(startGuardian).toHaveBeenCalled());
    expect(screen.getByRole('button', { name: 'Plan the revision' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Reading your note…' })).toBeNull();
    await act(async () => release(guardian()));
  });

  it('keeps the revision controls available beside the brand review', async () => {
    await mount();
    await screen.findByRole('heading', { name: 'What would you like to change?' });
    expect(screen.getByRole('button', { name: 'Plan the revision' })).toBeTruthy();
  });

  it('still proposes a revision from feedback alone', async () => {
    await mount();
    await screen.findByRole('heading', { name: 'What would you like to change?' });
    fireEvent.change(screen.getByLabelText('What would you like to change?'), {
      target: { value: 'Cool the grade and keep the composition.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Plan the revision' }));
    await waitFor(() => expect(proposeRevision).toHaveBeenCalledTimes(1));
    expect(proposeRevision).toHaveBeenCalledWith('c-1', 'org-1', {
      feedback: 'Cool the grade and keep the composition.',
    });
  });

  it('carries a visual from the brand review into the revision it is about', async () => {
    await mount();
    await screen.findByRole('button', { name: 'Refine this visual' });
    fireEvent.click(screen.getByRole('button', { name: 'Refine this visual' }));
    // The attachment is said out loud, because it changes what is being revised.
    expect(
      screen.getByText('Feedback attached to this visual'),
    ).toBeTruthy();

    fireEvent.change(screen.getByLabelText('What would you like to change?'), {
      target: { value: 'Cool the grade.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Plan the revision' }));
    await waitFor(() => expect(proposeRevision).toHaveBeenCalledTimes(1));
    expect(proposeRevision).toHaveBeenCalledWith('c-1', 'org-1', {
      feedback: 'Cool the grade.',
      source_asset_id: 'a-7',
    });
  });

  it('lets the attachment be undone, so feedback can be about the campaign', async () => {
    await mount();
    await screen.findByRole('button', { name: 'Refine this visual' });
    fireEvent.click(screen.getByRole('button', { name: 'Refine this visual' }));
    fireEvent.click(screen.getByRole('button', { name: 'Detach' }));
    expect(screen.queryByText('Feedback attached to this visual')).toBeNull();
  });

  it('shows a loading state while the stage is still arriving', async () => {
    getGuardian.mockReturnValue(new Promise(() => undefined));
    await mount();
    expect(screen.queryByRole('heading', { name: 'Brand review' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Refinement' })).toBeNull();
    // The skeleton, not a blank page and not an error.
    expect(document.querySelector('.animate-pulse')).toBeTruthy();
  });

  it('reports a failure to load rather than an empty page', async () => {
    getGuardian.mockRejectedValue(new ApiError('INTERNAL', 'The brand check service is down.', 500));
    await mount();
    expect(await screen.findByText('The brand check service is down.')).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Brand review' })).toBeNull();
  });

  it('says there is nothing to refine when neither stage is open', async () => {
    getGuardian.mockResolvedValue(
      guardian({
        results: [],
        can_check: false,
        blocked_reason: 'Generate creatives before brand-checking them.',
      }),
    );
    getRevision.mockResolvedValue(revision({ can_revise: false }));
    await mount();
    expect(await screen.findByText('Nothing to refine yet')).toBeTruthy();
    expect(screen.getByText('Generate creatives before brand-checking them.')).toBeTruthy();
  });

  it('does not describe the revision stage as the brand review’s state', async () => {
    getRevision.mockResolvedValue(
      revision({
        current: {
          id: 'r-1',
          iteration: 1,
          status: 'PROPOSED',
          user_feedback: 'Cool the grade.',
          delta: {
            iteration: 1,
            user_feedback: 'Cool the grade.',
            interpretation: 'Cool the colour grade; keep everything else.',
            keep: ['composition'],
            change: [],
            add: [],
            remove: [],
            explicit_unlocks: [],
            rationale: 'The brand register is cooler than the plate.',
          },
          changed_fields: [],
          from_version: 2,
          to_version: null,
          source_asset_id: 'a-7',
          created_at: '2026-01-01T11:00:00Z',
        },
        history: [],
      }),
    );
    await mount();
    await screen.findByRole('heading', { name: 'Brand review' });
    // The revision sentence lives under Refinement; the brand review describes
    // only itself.
    expect(screen.getByText('Read the plan before it runs.')).toBeTruthy();
    expect(screen.getByText(/Is this work acceptable for this brand\?/)).toBeTruthy();
  });
});
