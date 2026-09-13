'use client';

/**
 * The evaluation and recommendation screen.
 *
 * Evaluation is asynchronous for the same reason generation is — a multimodal
 * call per asset — so starting returns immediately with every evaluation
 * PENDING and this page polls until none are in flight. Polling rather than a
 * socket because polling cannot silently die (API_SPEC §Polling contract).
 */

import { use, useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { AppShell } from '@/components/app-shell';
import {
  ComparisonTable,
  EvaluationBoard,
  RecommendationPanel,
} from '@/components/evaluation';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import { ApiError, api, type Campaign, type EvaluationView } from '@/lib/api';
import { useWorkspace } from '@/lib/use-workspace';

const POLL_MS = 1500;
const SLOW_POLL_MS = 5000;
const BACKOFF_AFTER_MS = 60_000;

export default function EvaluatePage({
  params,
}: {
  params: Promise<{ campaignId: string }>;
}) {
  const { campaignId } = use(params);
  const workspace = useWorkspace();
  const { organizationId } = workspace;

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [view, setView] = useState<EvaluationView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const startedPollingAt = useRef<number | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!organizationId) return;
      const [detail, evaluation] = await Promise.all([
        api.getCampaign(campaignId, organizationId, signal),
        api.getEvaluation(campaignId, organizationId, signal),
      ]);
      if (signal?.aborted) return;
      setCampaign(detail);
      setView(evaluation);
    },
    [campaignId, organizationId],
  );

  useEffect(() => {
    if (!organizationId) return undefined;
    const controller = new AbortController();
    setCampaign(null);
    setError(null);
    load(controller.signal).catch((err: unknown) => {
      if (controller.signal.aborted) return;
      setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
    });
    return () => controller.abort();
  }, [load, organizationId]);

  const pending = (view?.in_flight ?? 0) > 0;

  useEffect(() => {
    if (!pending) {
      startedPollingAt.current = null;
      return undefined;
    }
    startedPollingAt.current ??= Date.now();
    const elapsed = Date.now() - (startedPollingAt.current ?? Date.now());
    const interval = elapsed > BACKOFF_AFTER_MS ? SLOW_POLL_MS : POLL_MS;

    const timer = setTimeout(() => {
      void load().catch((err: unknown) => {
        setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
      });
    }, interval);
    return () => clearTimeout(timer);
    // `view` is the dependency on purpose: each completed poll schedules the next.
  }, [pending, view, load]);

  async function run(action: () => Promise<EvaluationView>) {
    setBusy(true);
    setError(null);
    try {
      setView(await action());
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
    } finally {
      setBusy(false);
    }
  }

  if (workspace.error) {
    return (
      <div className="mx-auto max-w-5xl px-6 py-10">
        <ErrorState
          title="Cannot load your workspace"
          message={workspace.error.message}
          requestId={workspace.error.requestId}
          onRetry={workspace.error.isRetryable ? workspace.reload : undefined}
        />
      </div>
    );
  }

  const hasResults = (view?.ranked.length ?? 0) > 0;
  // Anything at all to show — including failures. Gating the board on ranked
  // results alone made a batch where every evaluation failed look like one
  // that had never been started, with no way to see why and no retry.
  const hasAnything = (view?.evaluations.length ?? 0) > 0;

  return (
    <AppShell
      me={workspace.me}
      activeOrganizationId={organizationId}
      onOrganizationChange={workspace.setOrganizationId}
    >
      <div className="flex flex-wrap justify-between gap-4">
        <Link
          href={`/app/campaigns/${campaignId}/generate`}
          className="text-sm text-muted hover:underline"
        >
          ← Generated creatives
        </Link>
        {/* Brand check and refinement, once there is something to check. */}
        {view && view.can_evaluate ? (
          <Link
            href={`/app/campaigns/${campaignId}/refine`}
            className="text-sm text-muted hover:underline"
          >
            Brand check & refine →
          </Link>
        ) : null}
      </div>

      {error && !campaign ? (
        <div className="mt-4">
          <ErrorState
            title={error.code === 'NOT_FOUND' ? 'Campaign not found' : 'Could not load this page'}
            message={error.message}
            requestId={error.requestId}
            onRetry={error.isRetryable ? () => void load() : undefined}
          />
        </div>
      ) : !campaign || !view ? (
        <div className="mt-6">
          <SkeletonRows rows={4} />
        </div>
      ) : (
        <div className="mt-4 space-y-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">{campaign.title}</h1>
              <p className="mt-1 text-sm text-muted">
                {hasResults && view.selected_asset_id
                  ? 'A creative has been selected.'
                  : hasResults
                    ? 'Review the scores and choose a creative.'
                    : hasAnything && !pending
                      ? 'No creative could be evaluated. Retry below.'
                      : 'Which of these creatives fits the campaign?'}
              </p>
            </div>
            {view.can_evaluate ? (
              <button
                type="button"
                disabled={busy || pending}
                onClick={() => void run(() => api.startEvaluation(campaignId, organizationId))}
                className="shrink-0 rounded-md border border-line bg-line/30 px-3 py-1.5 text-sm hover:bg-line/50 disabled:opacity-50"
              >
                {pending
                  ? 'Evaluating…'
                  : hasResults
                    ? 'Re-evaluate'
                    : 'Evaluate creatives'}
              </button>
            ) : null}
          </div>

          {error ? <ErrorState message={error.message} requestId={error.requestId} /> : null}

          {!view.can_evaluate ? (
            <EmptyState
              title="Nothing to evaluate yet"
              description={
                view.blocked_reason ??
                'Generate creatives first — evaluation scores the plates a campaign has produced.'
              }
              action={
                <Link
                  href={`/app/campaigns/${campaignId}/generate`}
                  className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40"
                >
                  Go to generation
                </Link>
              }
            />
          ) : !hasAnything && !pending ? (
            <EmptyState
              title="Not evaluated yet"
              description="Each plate is scored against the approved plan, the campaign and the brand — then ranked, with the reasoning shown."
            />
          ) : (
            <>
              <RecommendationPanel
                view={view}
                busy={busy}
                onSelect={(assetId) =>
                  void run(() =>
                    api.selectCreative(campaignId, organizationId, {
                      generated_asset_id: assetId,
                    }),
                  )
                }
              />
              <EvaluationBoard
                view={view}
                busy={busy}
                onSelect={(assetId) =>
                  void run(() =>
                    api.selectCreative(campaignId, organizationId, {
                      generated_asset_id: assetId,
                    }),
                  )
                }
                onRetry={(evaluationId) =>
                  void run(() => api.retryEvaluation(campaignId, evaluationId, organizationId))
                }
              />
              <ComparisonTable view={view} />
            </>
          )}
        </div>
      )}
    </AppShell>
  );
}
