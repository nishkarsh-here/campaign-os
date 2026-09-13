'use client';

/**
 * Brand check and refinement.
 *
 * Two questions, in order: is this acceptable for the brand, and what would you
 * change? The answer to the second becomes a plan the user reads before
 * anything runs — approving it is the only moment the creative changes, and
 * what runs is exactly what was on the screen.
 *
 * Regeneration is not duplicated here: once a revised specification is
 * approved, the user goes back to the generation screen, which already knows
 * how to compile prompts from the approved version.
 */

import { use, useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { AppShell } from '@/components/app-shell';
import {
  FeedbackBox,
  GuardianBoard,
  ProposedRevision,
  RevisedSpecification,
  RevisionHistory,
} from '@/components/revision';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import {
  ApiError,
  api,
  type Campaign,
  type GuardianView,
  type RevisionView,
} from '@/lib/api';
import { useWorkspace } from '@/lib/use-workspace';

const POLL_MS = 1500;
const SLOW_POLL_MS = 5000;
const BACKOFF_AFTER_MS = 60_000;

export default function RefinePage({
  params,
}: {
  params: Promise<{ campaignId: string }>;
}) {
  const { campaignId } = use(params);
  const workspace = useWorkspace();
  const { organizationId } = workspace;

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [guardian, setGuardian] = useState<GuardianView | null>(null);
  const [revision, setRevision] = useState<RevisionView | null>(null);
  const [sourceAssetId, setSourceAssetId] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const startedPollingAt = useRef<number | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!organizationId) return;
      const [detail, guardianView, revisionView] = await Promise.all([
        api.getCampaign(campaignId, organizationId, signal),
        api.getGuardian(campaignId, organizationId, signal),
        api.getRevision(campaignId, organizationId, signal),
      ]);
      if (signal?.aborted) return;
      setCampaign(detail);
      setGuardian(guardianView);
      setRevision(revisionView);
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

  const pending = (guardian?.in_flight ?? 0) > 0;

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
  }, [pending, guardian, load]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
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

  const approvedRevision = revision?.current?.status === 'APPROVED';
  // A new round may start when nothing is open — either there has never been
  // one, or the last one finished.
  const canGiveFeedback = !revision?.current || approvedRevision;

  return (
    <AppShell
      me={workspace.me}
      activeOrganizationId={organizationId}
      onOrganizationChange={workspace.setOrganizationId}
    >
      <div className="flex flex-wrap justify-between gap-4">
        <Link
          href={`/app/campaigns/${campaignId}/evaluate`}
          className="text-sm text-muted hover:underline"
        >
          ← Evaluation
        </Link>
        <div className="flex flex-wrap gap-4">
          {approvedRevision ? (
            <Link
              href={`/app/campaigns/${campaignId}/generate`}
              className="text-sm text-muted hover:underline"
            >
              Regenerate from the revised plan →
            </Link>
          ) : null}
          {/* The last stage. Reachable even before a brand check, because
              composing is what a user comes here to finish. */}
          <Link
            href={`/app/campaigns/${campaignId}/compose`}
            className="text-sm text-muted hover:underline"
          >
            Final composition →
          </Link>
        </div>
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
      ) : !campaign || !guardian || !revision ? (
        <div className="mt-6">
          <SkeletonRows rows={4} />
        </div>
      ) : (
        <div className="mt-4 space-y-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">{campaign.title}</h1>
              <p className="mt-1 text-sm text-muted">
                {approvedRevision
                  ? 'The revised plan is approved. Regenerate to see it.'
                  : revision.current?.status === 'APPLIED'
                    ? 'Review the revised specification.'
                    : revision.current?.status === 'PROPOSED'
                      ? 'Review the proposed revision.'
                      : 'Brand check and refinement.'}
              </p>
            </div>
            {guardian.can_check ? (
              <button
                type="button"
                disabled={busy || pending}
                onClick={() => void run(() => api.startGuardian(campaignId, organizationId))}
                className="shrink-0 rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40 disabled:opacity-50"
              >
                {pending
                  ? 'Checking…'
                  : guardian.results.length
                    ? 'Re-check brand'
                    : 'Run Brand Guardian'}
              </button>
            ) : null}
          </div>

          {error ? <ErrorState message={error.message} requestId={error.requestId} /> : null}

          {!guardian.can_check && !revision.can_revise ? (
            <EmptyState
              title="Nothing to refine yet"
              description={
                guardian.blocked_reason ??
                'Generate and evaluate creatives first — refinement works on something that exists.'
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
          ) : (
            <>
              <GuardianBoard
                view={guardian}
                busy={busy}
                onRetry={(resultId) =>
                  void run(() => api.retryGuardian(campaignId, resultId, organizationId))
                }
                onGiveFeedback={setSourceAssetId}
              />

              {/* Gate 2 first when it is open — it is what the user is waiting on. */}
              <RevisedSpecification
                view={revision}
                busy={busy}
                onApprove={() =>
                  void run(() => api.approveRevisedSpecification(campaignId, organizationId))
                }
                onReject={() => void run(() => api.rejectRevision(campaignId, organizationId))}
              />

              <ProposedRevision
                view={revision}
                busy={busy}
                onApprove={() =>
                  void run(() => api.approveRevisionDelta(campaignId, organizationId))
                }
                onReject={() => void run(() => api.rejectRevision(campaignId, organizationId))}
                onEdit={(changes) =>
                  void run(() =>
                    api.editRevisionDelta(campaignId, organizationId, {
                      interpretation: revision.current?.delta.interpretation ?? '',
                      keep: revision.current?.delta.keep ?? [],
                      change: changes,
                      rationale: revision.current?.delta.rationale ?? '',
                    }),
                  )
                }
              />

              {approvedRevision ? (
                <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/5 p-4">
                  <p className="text-sm font-medium">
                    Creative Specification v{revision.current?.to_version} approved
                  </p>
                  <p className="mt-0.5 text-xs text-muted">
                    Nothing has been generated yet. Regeneration uses the same pipeline as
                    before, starting from this version.
                  </p>
                  <Link
                    href={`/app/campaigns/${campaignId}/generate`}
                    className="mt-3 inline-block rounded-md border border-line bg-line/30 px-3 py-1.5 text-sm hover:bg-line/50"
                  >
                    Regenerate creatives →
                  </Link>
                </div>
              ) : null}

              {/* Only when nothing is waiting on the user: a round in flight
                  must be resolved before another is proposed. */}
              {revision.can_revise && canGiveFeedback ? (
                <FeedbackBox
                  busy={busy}
                  onSubmit={(feedback) =>
                    void run(() =>
                      api.proposeRevision(campaignId, organizationId, {
                        feedback,
                        ...(sourceAssetId ? { source_asset_id: sourceAssetId } : {}),
                      }),
                    )
                  }
                />
              ) : null}

              <RevisionHistory view={revision} />
            </>
          )}
        </div>
      )}
    </AppShell>
  );
}
