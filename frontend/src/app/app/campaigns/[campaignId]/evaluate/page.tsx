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
import { ComparisonTable } from '@/components/evaluation';
import { EvaluationStudio } from '@/components/evaluation-studio';
import { ErrorState, SkeletonRows } from '@/components/ui';
import { ApiError, api, type Campaign, type EvaluationView } from '@/lib/api';
import { useCampaignWorkspace } from '@/lib/campaign-context';
import { capabilitiesFor } from '@/lib/capabilities';

const POLL_MS = 1500;
const SLOW_POLL_MS = 5000;
const BACKOFF_AFTER_MS = 60_000;

export default function EvaluatePage({
  params,
}: {
  params: Promise<{ campaignId: string }>;
}) {
  const { campaignId } = use(params);
  const { organizationId, me } = useCampaignWorkspace();
  const membership = me?.organizations.find((m) => m.organization.id === organizationId);
  const capabilities = capabilitiesFor(membership?.role ?? (me ? 'viewer' : null));

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

  const hasResults = (view?.ranked.length ?? 0) > 0;
  // Anything at all to show — including failures. Gating the board on ranked
  // results alone made a batch where every evaluation failed look like one
  // that had never been started, with no way to see why and no retry.
  const hasAnything = (view?.evaluations.length ?? 0) > 0;

  return (
    <>
      {error && !campaign ? (
        <div className="mt-4">
          <ErrorState
            title={error.code === 'NOT_FOUND' ? 'Campaign not found' : 'Could not load this page'}
            message={error.message}
            code={error.code}
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
          {/* The heading and the stage, and nothing that acts. Every control
              belongs to the studio below, which knows what it would act on. */}
          <div>
            <h2 className="text-h2">Review</h2>
            <p className="mt-1 max-w-content text-body text-muted">
              {hasResults && view.selected_asset_id
                ? 'A creative has been selected.'
                : hasResults
                  ? 'Review the scores and choose a creative.'
                  : hasAnything && !pending
                    ? 'No creative could be evaluated. Retry below.'
                    : 'Which of these creatives fits the campaign?'}
            </p>
          </div>

          {error ? <ErrorState message={error.message} requestId={error.requestId} /> : null}

          <EvaluationStudio
            view={view}
            capabilities={capabilities}
            busy={busy || pending}
            onEvaluate={(assetIds) =>
              void run(() => api.startEvaluation(campaignId, organizationId, assetIds))
            }
            onRetry={(evaluationId) =>
              void run(() => api.retryEvaluation(campaignId, evaluationId, organizationId))
            }
            onSelect={(assetId, note) =>
              void run(() =>
                api.selectCreative(campaignId, organizationId, {
                  generated_asset_id: assetId,
                  ...(note ? { note } : {}),
                }),
              )
            }
          />

          {/* The full score matrix, for someone who wants to read across every
              plate at once. Folded away because the studio above is how the
              work is actually judged. */}
          {view.ranked.length > 1 ? (
            <details className="rounded-lg border border-line">
              <summary className="cursor-pointer px-5 py-4 text-label uppercase text-muted transition-colors duration-fast hover:text-ink">
                Compare every score side by side
              </summary>
              <div className="border-t border-line p-5">
                <ComparisonTable view={view} />
              </div>
            </details>
          ) : null}
        </div>
      )}
    </>
  );
}
