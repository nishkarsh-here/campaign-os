'use client';

/**
 * The campaign discovery workspace.
 *
 * Conversation on the left, the running picture of what we know on the right,
 * and the Campaign Specification once discovery has produced one.
 */

import { use, useCallback, useEffect, useState } from 'react';
import { Conversation, SpecificationPanel } from '@/components/campaign-discovery';
import {
  CampaignSnapshot,
  fromInputs,
  fromSpecification,
} from '@/components/campaign-snapshot';
import { ErrorState, SkeletonRows } from '@/components/states';
import {
  ApiError,
  api,
  type Campaign,
  type CampaignMessage,
  type DiscoveryTurn,
} from '@/lib/api';
import { useCampaignWorkspace } from '@/lib/campaign-context';

export default function CampaignPage({ params }: { params: Promise<{ campaignId: string }> }) {
  const { campaignId } = use(params);
  const { organizationId, specification } = useCampaignWorkspace();

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

  const confirmed = campaign?.status === 'SPECIFICATION_CONFIRMED';

  return (
    <>
      {error && !campaign ? (
        <div className="mt-4">
          <ErrorState
            title={error.code === 'NOT_FOUND' ? 'Campaign not found' : 'Could not load this campaign'}
            message={error.message}
            code={error.code}
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
          <h2 className="text-h2">Brief</h2>
          <p className="mt-1 max-w-content text-body text-muted">
            {confirmed
              ? 'The brief is settled. Everything downstream is built from it.'
              : turn?.interview_complete
                ? 'Everything needed has been answered. Read it through, change anything, then confirm.'
                : 'A few questions, in your own words. The snapshot fills in as you answer.'}
          </p>

          {error ? (
            <div className="mt-4">
              <ErrorState message={error.message} requestId={error.requestId} />
            </div>
          ) : null}

          {/* Conversation and snapshot side by side: the point of the
              snapshot is watching it fill in while you answer, which a panel
              below the fold cannot do. */}
          <div className="mt-6 grid gap-6 lg:grid-cols-[1.35fr_1fr] lg:items-start">
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

              {/* Same gap: without a turn there was no specification to show.
                  The confirmed one comes from the workspace context. */}
              {turn?.specification || specification ? (
                <SpecificationPanel
                  specification={turn?.specification ?? specification!}
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

            {/*
              A confirmed campaign has no `DiscoveryTurn` — `POST
              /discovery/start` answers 409 and the page deliberately swallows
              it. Before UI-2C that left this column as a permanent skeleton
              and the brief invisible on its own screen, for every seeded
              campaign. The layout already holds the confirmed specification,
              so it is rendered through the same snapshot.
            */}
            {turn ? (
              <CampaignSnapshot
                brief={fromInputs(turn.known)}
                missing={turn.missing}
                asking={turn.question?.field ?? null}
                complete={Boolean(turn.interview_complete)}
              />
            ) : specification ? (
              <CampaignSnapshot
                brief={fromSpecification(specification)}
                complete
                confirmed
              />
            ) : (
              <SkeletonRows rows={3} />
            )}
          </div>
        </div>
      )}
    </>
  );
}
