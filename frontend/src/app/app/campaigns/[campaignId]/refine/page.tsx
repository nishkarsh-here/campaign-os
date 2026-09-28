'use client';

/**
 * Brand review, and then refinement.
 *
 * Two questions, in order: is this acceptable for the brand, and what would you
 * change? The answer to the second becomes a plan the user reads before
 * anything runs — approving it is the only moment the creative changes, and
 * what runs is exactly what was on the screen.
 *
 * ## Why this page fetches five things
 *
 * Refinement is the one screen that has to reason about *versions*, and no
 * single endpoint knows the whole story:
 *
 * - `/revision` — the loop, the plan, the history, the before/after diff;
 * - `/guardian` — verdicts, each stamped with the plan version it judged;
 * - `/generation` — the plan version in force, and the latest plates;
 * - `/evaluation` — which plate a person actually chose, and the plates from
 *   earlier versions that generation no longer returns;
 * - `/creative` — `locked_fields`, the only source of the standing locks.
 *
 * `/creative` is used for that field **and nothing else**. Its `specification`
 * comes from the creative graph's checkpoint, which on a revised campaign still
 * reports the version the gate approved — a benchmark campaign here returns v2
 * while the approved plan is v3. Reading a version number from it would not be
 * a gap, it would be a wrong number, so the version facts come from the rows
 * that stamp their own (see `lib/refinement.ts`).
 *
 * ## One page, three sections, no echoes
 *
 * `GuardianReview` owns the brand review entirely. The thread between it and
 * refinement is `sourceAssetId`: "Refine this visual" attaches the feedback to
 * that plate, says so on screen, and can be undone. It fills the form in; it
 * never submits it.
 */

import { use, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { GuardianReview } from '@/components/guardian-review';
import {
  CurrentCreative,
  GuardianLoop,
  LocalizationPanel,
  ProtectedPanel,
  RevisedPlanCard,
  RevisionPlanCard,
  RevisionRequest,
} from '@/components/refinement-workspace';
import { VersionHistory } from '@/components/version-history';
import { Card, EmptyState, ErrorState, SkeletonRows, buttonStyles } from '@/components/ui';
import {
  ApiError,
  api,
  type Campaign,
  type CreativeSpecification,
  type EvaluationView,
  type GeneratedAssetView,
  type GenerationView,
  type GuardianView,
  type RevisionView,
} from '@/lib/api';
import { useCampaignWorkspace } from '@/lib/campaign-context';
import { capabilitiesFor } from '@/lib/capabilities';
import {
  localizationContext,
  protectedFields,
  refinementState,
  representativeAsset,
  revisionPlan,
  versionBrandStatus,
  versionTimeline,
} from '@/lib/refinement';

/** The two independent halves of this page. */
type Stage = 'guardian' | 'revision';

const POLL_MS = 1500;
const SLOW_POLL_MS = 5000;
const BACKOFF_AFTER_MS = 60_000;

export default function RefinePage({
  params,
}: {
  params: Promise<{ campaignId: string }>;
}) {
  const { campaignId } = use(params);
  const { organizationId, me, overview, specification } = useCampaignWorkspace();
  const membership = me?.organizations.find((m) => m.organization.id === organizationId);
  const capabilities = capabilitiesFor(membership?.role ?? (me ? 'viewer' : null));

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [guardian, setGuardian] = useState<GuardianView | null>(null);
  const [revision, setRevision] = useState<RevisionView | null>(null);
  const [generation, setGeneration] = useState<GenerationView | null>(null);
  const [evaluation, setEvaluation] = useState<EvaluationView | null>(null);
  const [creativeSpec, setCreativeSpec] = useState<CreativeSpecification | null>(null);
  const [sourceAssetId, setSourceAssetId] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState<Stage | null>(null);
  const startedPollingAt = useRef<number | null>(null);
  const feedbackRef = useRef<HTMLDivElement | null>(null);

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

      // Version context. Best-effort on purpose: a campaign that has not
      // generated or evaluated yet still has a refinement screen, and a
      // failure here must not take the brand review down with it.
      api
        .getGeneration(campaignId, organizationId, signal)
        .then((view) => !signal?.aborted && setGeneration(view))
        .catch(() => undefined);
      api
        .getEvaluation(campaignId, organizationId, signal)
        .then((view) => !signal?.aborted && setEvaluation(view))
        .catch(() => undefined);
      api
        .getCreativeStage(campaignId, organizationId, signal)
        .then((view) => !signal?.aborted && setCreativeSpec(view.specification))
        .catch(() => undefined);
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

  async function run(stage: Stage, action: () => Promise<unknown>) {
    setBusy(stage);
    setError(null);
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
    } finally {
      setBusy(null);
    }
  }

  // ------------------------------------------------------------ derived state
  const versions = useMemo(
    () => versionTimeline(revision, guardian, generation, evaluation),
    [revision, guardian, generation, evaluation],
  );
  const currentVersion = versions.find((v) => v.current) ?? null;
  const selectedAssetId = evaluation?.selected_asset_id ?? null;

  /** Every plate this campaign holds, from whichever surface returned it. */
  const assetsById = useMemo(() => {
    const map = new Map<string, GeneratedAssetView>();
    for (const entry of versions) for (const asset of entry.assets) map.set(asset.id, asset);
    return map;
  }, [versions]);

  const selectedAsset = selectedAssetId ? (assetsById.get(selectedAssetId) ?? null) : null;
  /** What the person is judging: their selection, else the current plan's plate. */
  const shown =
    selectedAsset ?? (currentVersion ? representativeAsset(currentVersion, null) : null);
  const shownVersion = shown
    ? (versions.find((v) => v.version === shown.specification_version) ?? null)
    : null;

  const state = revision ? refinementState(revision) : null;
  const plan = revision?.current ? revisionPlan(revision.current.delta) : null;
  const protectedGroups = protectedFields(revision?.current?.delta ?? null, creativeSpec);
  const localization = localizationContext(specification);
  const attachedAsset = sourceAssetId ? (assetsById.get(sourceAssetId) ?? null) : null;

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
      ) : !campaign || !guardian || !revision || !state ? (
        <div className="mt-6">
          <SkeletonRows rows={4} />
        </div>
      ) : (
        <div className="mt-4 space-y-6">
          <div>
            <h2 className="text-h2">Brand review</h2>
            <p className="mt-1 max-w-content text-body text-muted">
              Is this work acceptable for this brand? Then — if not — what would you change?
            </p>
          </div>

          {error ? <ErrorState message={error.message} requestId={error.requestId} /> : null}

          {!guardian.can_check && !revision.can_revise && !revision.current ? (
            <EmptyState
              title="Nothing to refine yet"
              description={
                guardian.blocked_reason ??
                'Generate and evaluate creatives first — refinement works on something that exists.'
              }
              action={
                <Link
                  href={`/app/campaigns/${campaignId}/generate`}
                  className={buttonStyles('primary', 'lg')}
                >
                  Go to generation
                </Link>
              }
            />
          ) : (
            <>
              <GuardianReview
                view={guardian}
                capabilities={capabilities}
                busy={busy === 'guardian'}
                pending={pending}
                onCheck={(assetIds) =>
                  void run('guardian', () =>
                    api.startGuardian(campaignId, organizationId, assetIds),
                  )
                }
                onRetry={(resultId) =>
                  void run('guardian', () =>
                    api.retryGuardian(campaignId, resultId, organizationId),
                  )
                }
                onGiveFeedback={(assetId) => {
                  setSourceAssetId(assetId);
                  feedbackRef.current?.scrollIntoView?.({ block: 'center' });
                }}
              />

              {/* ------------------------------------------------ refinement */}
              <div className="border-t border-line pt-6">
                <h2 className="text-h2">Refinement</h2>
                <p className="mt-1 max-w-content text-body text-muted">{state.headline}</p>
              </div>

              {/* The work itself stays the largest thing on the screen. */}
              <CurrentCreative
                asset={shown}
                supersededBy={
                  shownVersion && currentVersion && shownVersion.version < currentVersion.version
                    ? currentVersion.version
                    : null
                }
                facts={{
                  campaign: overview?.title ?? campaign.title ?? null,
                  brand: overview?.brand_name ?? null,
                  market: specification?.region ?? null,
                  channels: specification?.channels ?? [],
                  version: shown?.specification_version ?? null,
                  brandStatus: versionBrandStatus(
                    shownVersion ?? {
                      version: 0,
                      revision: null,
                      summary: null,
                      assets: [],
                      verdicts: [],
                      current: false,
                      createdAt: null,
                    },
                  ),
                }}
              />

              <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,20rem)] xl:items-start">
                <div ref={feedbackRef} className="space-y-6">
                  {state.step === 'plan' && plan && revision.current ? (
                    <RevisionPlanCard
                      plan={plan}
                      iteration={revision.current.iteration}
                      fromVersion={revision.current.from_version}
                      busy={busy === 'revision'}
                      capabilities={capabilities}
                      onApprove={() =>
                        void run('revision', () =>
                          api.approveRevisionDelta(campaignId, organizationId),
                        )
                      }
                      onEdit={(changes) =>
                        void run('revision', () =>
                          api.editRevisionDelta(campaignId, organizationId, {
                            interpretation: revision.current?.delta.interpretation ?? '',
                            keep: revision.current?.delta.keep ?? [],
                            change: changes,
                            rationale: revision.current?.delta.rationale ?? '',
                          }),
                        )
                      }
                      onDiscard={() =>
                        void run('revision', () => api.rejectRevision(campaignId, organizationId))
                      }
                    />
                  ) : null}

                  {state.step === 'revised' && revision.current ? (
                    <RevisedPlanCard
                      diff={revision.diff}
                      fromVersion={revision.current.from_version}
                      toVersion={revision.current.to_version}
                      busy={busy === 'revision'}
                      capabilities={capabilities}
                      onApprove={() =>
                        void run('revision', () =>
                          api.approveRevisedSpecification(campaignId, organizationId),
                        )
                      }
                      onDiscard={() =>
                        void run('revision', () => api.rejectRevision(campaignId, organizationId))
                      }
                    />
                  ) : null}

                  {state.step === 'regenerate' && revision.current ? (
                    <Card className="border-l-2 border-l-success">
                      <p className="text-label uppercase text-success">
                        Creative plan v{revision.current.to_version} approved
                      </p>
                      <p className="mt-1 max-w-content text-body text-muted">{state.next}</p>
                      <Link
                        href={`/app/campaigns/${campaignId}/generate`}
                        className={buttonStyles('primary', 'md', 'mt-4 inline-flex')}
                      >
                        Generate from the revised plan
                      </Link>
                    </Card>
                  ) : null}

                  {revision.can_revise && state.canStartRound ? (
                    <RevisionRequest
                      busy={busy === 'revision'}
                      capabilities={capabilities}
                      attachedAsset={attachedAsset}
                      onDetach={() => setSourceAssetId(null)}
                      onSubmit={(feedback) =>
                        void run('revision', () =>
                          api.proposeRevision(campaignId, organizationId, {
                            feedback,
                            ...(sourceAssetId ? { source_asset_id: sourceAssetId } : {}),
                          }),
                        )
                      }
                    />
                  ) : null}

                  <Card>
                    <GuardianLoop state={state} />
                  </Card>
                </div>

                <aside className="space-y-6">
                  <ProtectedPanel groups={protectedGroups} />
                  <LocalizationPanel context={localization} />
                </aside>
              </div>

              {/* --------------------------------------------- the record */}
              <div className="border-t border-line pt-6">
                <h2 className="text-h2">Version history</h2>
                <p className="mt-1 max-w-content text-body text-muted">
                  Every version of the creative plan this campaign has had, and what each one
                  changed.
                </p>
              </div>
              <VersionHistory versions={versions} selectedAssetId={selectedAssetId} />
            </>
          )}
        </div>
      )}
    </>
  );
}
