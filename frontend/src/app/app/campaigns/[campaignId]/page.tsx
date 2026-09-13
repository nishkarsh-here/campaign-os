'use client';

/**
 * The campaign discovery workspace.
 *
 * Conversation on the left, the running picture of what we know on the right,
 * and the Campaign Specification once discovery has produced one.
 */

import { use, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AppShell } from '@/components/app-shell';
import {
  CompletenessRail,
  Conversation,
  SpecificationPanel,
} from '@/components/campaign-discovery';
import { ErrorState, SkeletonRows } from '@/components/states';
import {
  ApiError,
  api,
  type Campaign,
  type CampaignMessage,
  type DiscoveryTurn,
} from '@/lib/api';
import { useWorkspace } from '@/lib/use-workspace';

export default function CampaignPage({ params }: { params: Promise<{ campaignId: string }> }) {
  const { campaignId } = use(params);
  const workspace = useWorkspace();
  const { organizationId } = workspace;

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [turn, setTurn] = useState<DiscoveryTurn | null>(null);
  const [messages, setMessages] = useState<CampaignMessage[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      if (!organizationId) return;
      const [detail, transcript] = await Promise.all([
        api.getCampaign(campaignId, organizationId, signal),
        api.getConversation(campaignId, organizationId, signal),
      ]);
      if (signal?.aborted) return;
      setCampaign(detail);
      setMessages(transcript.items);
    },
    [campaignId, organizationId],
  );

  // Starting is safe to repeat: an existing conversation is resumed, not reset.
  const begin = useCallback(
    async (signal?: AbortSignal) => {
      if (!organizationId) return;
      try {
        const started = await api.startDiscovery(campaignId, organizationId, signal);
        if (!signal?.aborted) {
          setTurn(started);
          setError(null);
        }
      } catch (err) {
        if (signal?.aborted) return;
        // A confirmed campaign refuses to reopen — expected, not a failure.
        if (err instanceof ApiError && err.code === 'CONFLICT') return;
        setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
      }
    },
    [campaignId, organizationId],
  );

  useEffect(() => {
    if (!organizationId) return undefined;
    const controller = new AbortController();
    setCampaign(null);
    setError(null);
    refresh(controller.signal)
      .then(() => begin(controller.signal))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
      });
    return () => controller.abort();
  }, [refresh, begin, organizationId]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await refresh();
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

  const confirmed = campaign?.status === 'SPECIFICATION_CONFIRMED';

  return (
    <AppShell
      me={workspace.me}
      activeOrganizationId={organizationId}
      onOrganizationChange={workspace.setOrganizationId}
    >
      <Link href="/app/campaigns" className="text-sm text-muted hover:underline">
        ← Campaigns
      </Link>

      {error && !campaign ? (
        <div className="mt-4">
          <ErrorState
            title={error.code === 'NOT_FOUND' ? 'Campaign not found' : 'Could not load this campaign'}
            message={error.message}
            requestId={error.requestId}
            onRetry={error.isRetryable ? () => void refresh() : undefined}
          />
        </div>
      ) : !campaign ? (
        <div className="mt-6">
          <SkeletonRows rows={4} />
        </div>
      ) : (
        <div className="mt-4">
          <div className="flex items-start justify-between gap-4">
            <h1 className="text-2xl font-semibold tracking-tight">{campaign.title}</h1>
            <div className="flex shrink-0 gap-2">
              <Link
                href={`/app/campaigns/${campaignId}/inspiration`}
                className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/30"
              >
                Inspiration →
              </Link>
              {/* Only once the facts are settled: directions are built from them. */}
              {confirmed ? (
                <Link
                  href={`/app/campaigns/${campaignId}/creative`}
                  className="rounded-md border border-line bg-line/30 px-3 py-1.5 text-sm hover:bg-line/50"
                >
                  Creative →
                </Link>
              ) : null}
            </div>
          </div>
          <p className="mt-1 text-sm text-muted">
            {confirmed
              ? 'Specification confirmed.'
              : turn?.interview_complete
                ? 'Review the specification below.'
                : 'Discovery in progress.'}
          </p>

          {error ? (
            <div className="mt-4">
              <ErrorState message={error.message} requestId={error.requestId} />
            </div>
          ) : null}

          <div className="mt-6 grid gap-6 lg:grid-cols-[2fr_1fr]">
            <div className="space-y-6">
              <Conversation
                messages={messages}
                question={turn?.question ?? null}
                busy={busy}
                complete={Boolean(turn?.interview_complete)}
                onAnswer={(answer) =>
                  void run(async () => {
                    const next = await api.answerQuestion(campaignId, organizationId, answer);
                    setTurn(next);
                  })
                }
              />

              {turn?.specification ? (
                <SpecificationPanel
                  specification={turn.specification}
                  confirmed={Boolean(confirmed)}
                  busy={busy}
                  onSave={(edits) =>
                    void run(async () => {
                      const updated = await api.updateSpecification(
                        campaignId,
                        organizationId,
                        edits,
                      );
                      setTurn((current) =>
                        current ? { ...current, specification: updated } : current,
                      );
                    })
                  }
                  onConfirm={() =>
                    void run(async () => {
                      const confirmedSpec = await api.confirmSpecification(
                        campaignId,
                        organizationId,
                      );
                      setTurn((current) =>
                        current ? { ...current, specification: confirmedSpec } : current,
                      );
                    })
                  }
                />
              ) : null}
            </div>

            {turn ? (
              <CompletenessRail known={turn.known} missing={turn.missing} />
            ) : (
              <SkeletonRows rows={3} />
            )}
          </div>
        </div>
      )}
    </AppShell>
  );
}
