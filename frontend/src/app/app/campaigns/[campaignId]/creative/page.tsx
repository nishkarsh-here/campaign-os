'use client';

/**
 * The creative stage: three directions, a human decision, then the execution
 * plan and a second human decision.
 *
 * The page is deliberately thin — it holds the stage view and turns clicks
 * into API calls. Every judgement about what the stage *is* (which gate is
 * open, whether anything was approved) comes from the server, because the
 * graph, not the browser, owns that state.
 */

import { use, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AppShell } from '@/components/app-shell';
import { DirectionBoard, SpecificationPanel } from '@/components/creative-director';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import {
  ApiError,
  api,
  type Campaign,
  type CreativeStageView,
} from '@/lib/api';
import { useWorkspace } from '@/lib/use-workspace';

export default function CreativePage({
  params,
}: {
  params: Promise<{ campaignId: string }>;
}) {
  const { campaignId } = use(params);
  const workspace = useWorkspace();
  const { organizationId } = workspace;

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [stage, setStage] = useState<CreativeStageView | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!organizationId) return;
      const [detail, view] = await Promise.all([
        api.getCampaign(campaignId, organizationId, signal),
        api.getCreativeStage(campaignId, organizationId, signal),
      ]);
      if (signal?.aborted) return;
      setCampaign(detail);
      setStage(view);
      setSelectedId(
        (current) =>
          view.selected_direction_id ??
          current ??
          view.direction_set?.directions.find(
            (d) => d.ordinal === view.direction_set?.recommended_ordinal,
          )?.id ??
          view.direction_set?.directions[0]?.id ??
          null,
      );
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

  /** Every mutation returns the whole stage, so the server stays the truth. */
  async function run(action: () => Promise<CreativeStageView | unknown>) {
    setBusy(true);
    setError(null);
    try {
      const result = await action();
      if (result && typeof result === 'object' && 'gate' in result) {
        const view = result as CreativeStageView;
        setStage(view);
        setSelectedId(view.selected_direction_id ?? selectedId);
      }
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

  const confirmed = campaign?.status === 'SPECIFICATION_CONFIRMED';
  const set = stage?.direction_set ?? null;
  const chosen =
    set?.directions.find((d) => d.id === (stage?.selected_direction_id ?? selectedId)) ?? null;

  return (
    <AppShell
      me={workspace.me}
      activeOrganizationId={organizationId}
      onOrganizationChange={workspace.setOrganizationId}
    >
      <div className="flex flex-wrap gap-4">
        <Link href={`/app/campaigns/${campaignId}`} className="text-sm text-muted hover:underline">
          ← Discovery
        </Link>
        <Link
          href={`/app/campaigns/${campaignId}/inspiration`}
          className="text-sm text-muted hover:underline"
        >
          ← Inspiration
        </Link>
        {/* Only once the plan is approved: generation works from an approved
            specification, so the link appears when the door actually opens. */}
        {stage?.approved ? (
          <Link
            href={`/app/campaigns/${campaignId}/generate`}
            className="ml-auto text-sm text-muted hover:underline"
          >
            Generate creatives →
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
      ) : !campaign || !stage ? (
        <div className="mt-6">
          <SkeletonRows rows={4} />
        </div>
      ) : (
        <div className="mt-4 space-y-6">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{campaign.title}</h1>
            <p className="mt-1 text-sm text-muted">
              {stage.approved
                ? 'Specification approved. Ready for generation.'
                : stage.gate === 'specification_gate'
                  ? 'Review the execution plan, edit anything, then approve.'
                  : set
                    ? 'Choose a creative direction.'
                    : 'Creative strategy.'}
            </p>
          </div>

          {error ? <ErrorState message={error.message} requestId={error.requestId} /> : null}

          {stage.approved ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-emerald-500/40 bg-emerald-500/5 p-4">
              <div>
                <p className="text-sm font-medium">Specification approved</p>
                <p className="mt-0.5 text-xs text-muted">
                  Ready to generate visual plates. Nothing has been generated yet.
                </p>
              </div>
              <Link
                href={`/app/campaigns/${campaignId}/generate`}
                className="shrink-0 rounded-md border border-line bg-line/30 px-3 py-1.5 text-sm hover:bg-line/50"
              >
                Generate creatives →
              </Link>
            </div>
          ) : null}

          {/* Missing context weakens the directions rather than blocking them,
              so it is stated, not enforced. */}
          {stage.gaps.length ? (
            <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
              <p className="text-xs font-medium">Working with incomplete context</p>
              <ul className="mt-1 space-y-0.5 text-xs text-muted">
                {stage.gaps.map((gap) => (
                  <li key={gap}>· {gap}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {!confirmed && !set ? (
            <EmptyState
              title="Confirm the campaign specification first"
              description="Creative directions are built from confirmed campaign facts. Finish discovery and confirm the specification, then come back."
              action={
                <Link
                  href={`/app/campaigns/${campaignId}`}
                  className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40"
                >
                  Back to discovery
                </Link>
              }
            />
          ) : !set ? (
            <EmptyState
              title="No directions yet"
              description="We will propose three genuinely different routes from your brand, your specification and the references you liked."
              action={
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void run(() => api.startCreative(campaignId, organizationId))
                  }
                  className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40 disabled:opacity-50"
                >
                  {busy ? 'Thinking…' : 'Generate creative directions'}
                </button>
              }
            />
          ) : (
            <>
              {stage.gate === 'strategy_gate' ? (
                <DirectionBoard
                  set={set}
                  selectedId={selectedId}
                  busy={busy}
                  onSelect={setSelectedId}
                  onApprove={(directionId) =>
                    void run(() =>
                      api.decideStrategy(campaignId, organizationId, {
                        decision: 'APPROVE',
                        direction_id: directionId,
                      }),
                    )
                  }
                  onRequestChanges={(feedback) =>
                    void run(() =>
                      api.decideStrategy(campaignId, organizationId, {
                        decision: 'REQUEST_REVISION',
                        feedback,
                      }),
                    )
                  }
                  onReject={(feedback) =>
                    void run(() =>
                      api.decideStrategy(campaignId, organizationId, {
                        decision: 'REJECT',
                        feedback,
                      }),
                    )
                  }
                />
              ) : null}

              {stage.specification ? (
                <SpecificationPanel
                  specification={stage.specification}
                  direction={chosen}
                  busy={busy}
                  approved={stage.approved}
                  onSave={(edits) =>
                    void run(() =>
                      api.updateCreativeSpecification(campaignId, organizationId, edits),
                    )
                  }
                  onApprove={() =>
                    void run(() =>
                      api.decideCreativeSpecification(campaignId, organizationId, {
                        decision: 'APPROVE',
                      }),
                    )
                  }
                  onRequestChanges={(feedback) =>
                    void run(() =>
                      api.decideCreativeSpecification(campaignId, organizationId, {
                        decision: 'REQUEST_REVISION',
                        feedback,
                      }),
                    )
                  }
                />
              ) : null}
            </>
          )}
        </div>
      )}
    </AppShell>
  );
}
