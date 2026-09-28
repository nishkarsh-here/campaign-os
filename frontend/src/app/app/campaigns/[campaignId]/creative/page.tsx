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
import { ChannelCopyPanel, SpecificationPanel } from '@/components/creative-director';
import { CreativeDirections } from '@/components/creative-directions';
import { CreativePlan } from '@/components/creative-plan';
import { Button, Card, EmptyState, ErrorState, SkeletonRows, buttonStyles } from '@/components/ui';
import { ApiError, api, type Campaign, type CreativeStageView } from '@/lib/api';
import { useCampaignWorkspace } from '@/lib/campaign-context';
import { capabilitiesFor } from '@/lib/capabilities';
import { creativeState } from '@/lib/creative';

export default function CreativePage({
  params,
}: {
  params: Promise<{ campaignId: string }>;
}) {
  const { campaignId } = use(params);
  const { organizationId, me, overview, specification: campaignSpecification } =
    useCampaignWorkspace();
  const membership = me?.organizations.find((m) => m.organization.id === organizationId);
  const capabilities = capabilitiesFor(membership?.role ?? (me ? 'viewer' : null));

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

  const confirmed = campaign?.status === 'SPECIFICATION_CONFIRMED';
  const set = stage?.direction_set ?? null;
  const chosen =
    set?.directions.find((d) => d.id === (stage?.selected_direction_id ?? selectedId)) ?? null;

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
      ) : !campaign || !stage ? (
        <div className="mt-6">
          <SkeletonRows rows={4} />
        </div>
      ) : (
        <div className="mt-4 space-y-6">
          <div>
            <h2 className="text-h2">Creative</h2>
            {/* The stage in the reader's words, derived from the gate and the
                approval flag — never from the campaign row's status, which
                only tracks discovery. */}
            <p className="mt-1 max-w-content text-body text-muted">
              {creativeState(stage).detail}
            </p>
          </div>

          {error ? <ErrorState message={error.message} requestId={error.requestId} /> : null}

          {stage.approved ? (
            <Card className="flex flex-wrap items-center justify-between gap-3 border-l-2 border-l-success">
              <div>
                <p className="text-label uppercase text-success">Creative plan approved</p>
                <p className="mt-1 text-body text-muted">
                  Every visual is generated from this plan, and checked against it.
                </p>
              </div>
              <Link
                href={`/app/campaigns/${campaignId}/generate`}
                className={buttonStyles('primary', 'md', 'shrink-0')}
              >
                Generate the visuals
              </Link>
            </Card>
          ) : null}

          {/* Missing context weakens the directions rather than blocking them,
              so it is stated, not enforced. */}
          {/* Missing context weakens the routes rather than blocking them, so
              it is stated, not enforced. */}
          {stage.gaps.length ? (
            <Card className="border-l-2 border-l-warning">
              <p className="text-label uppercase text-warning">Working with incomplete context</p>
              <ul className="mt-2 space-y-1">
                {stage.gaps.map((gap) => (
                  <li key={gap} className="text-small text-muted">
                    {gap}
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}

          {!confirmed && !set ? (
            <EmptyState
              title="Confirm the brief first"
              description="Creative routes are built from confirmed campaign facts. Finish the brief and confirm it, then come back."
              action={
                <Link href={`/app/campaigns/${campaignId}`} className={buttonStyles('primary', 'lg')}>
                  Open the brief
                </Link>
              }
            />
          ) : !set ? (
            <EmptyState
              title="No creative routes yet"
              description="Campaign OS proposes three genuinely different routes from your brand, your brief and the references you liked."
              action={
                capabilities.can('edit_campaign') ? (
                  <Button
                    variant="primary"
                    size="lg"
                    disabled={busy}
                    onClick={() => void run(() => api.startCreative(campaignId, organizationId))}
                  >
                    {busy ? 'Developing routes…' : 'Develop creative routes'}
                  </Button>
                ) : undefined
              }
            />
          ) : (
            <>
              {/* The routes stay visible after Gate 1 closes — the set holds
                  all three, and a person should be able to read back which was
                  chosen and what it was chosen over. Only the decision goes
                  away with the gate. */}
              {set ? (
                <CreativeDirections
                  view={stage}
                  gateOpen={stage.gate === 'strategy_gate'}
                  campaignSpecification={campaignSpecification}
                  brandName={overview?.brand_name ?? null}
                  capabilities={capabilities}
                  busy={busy}
                  onChoose={(directionId) =>
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
                />
              ) : null}

              {/* Gate 2. The plan, read the way a marketer reads a brief. */}
              {stage.specification ? (
                <CreativePlan
                  specification={stage.specification}
                  declaredChannels={stage.channels}
                  approved={stage.approved}
                  gateOpen={stage.gate === 'specification_gate'}
                  capabilities={capabilities}
                  busy={busy}
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

              {/*
                The field-level editor, kept behind a disclosure.

                `CreativePlan` above is how the plan is read; this is how it is
                changed, and it is the existing constrained editor — the one
                that refuses an edit rather than trimming it. Folding it away
                rather than deleting it keeps a working capability that the new
                presentation does not replace.
              */}
              {stage.specification && !stage.approved && capabilities.can('edit_campaign') ? (
                <details className="rounded-lg border border-line">
                  <summary className="cursor-pointer px-5 py-4 text-label uppercase text-muted transition-colors duration-fast hover:text-ink">
                    Edit the plan field by field
                  </summary>
                  <div className="space-y-6 border-t border-line p-5">
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
                    <ChannelCopyPanel
                      specification={stage.specification}
                      channels={stage.channels}
                      busy={busy}
                      approved={stage.approved}
                      onSave={(overrides) =>
                        void run(() =>
                          api.updateCreativeSpecification(campaignId, organizationId, {
                            channel_copy: overrides,
                          }),
                        )
                      }
                    />
                  </div>
                </details>
              ) : null}
            </>
          )}
        </div>
      )}
    </>
  );
}
