'use client';

/**
 * The campaign command centre.
 *
 * The screen you open to find out where a campaign is. It reads one endpoint
 * and mutates nothing: every stage, score and verdict on it is owned by the
 * screen it links to, and this page is a summary of those rather than a second
 * opinion about them.
 */

import { use, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AppShell } from '@/components/app-shell';
import {
  BrandStatusCard,
  CampaignFacts,
  FinalAssetStrip,
  NextAction,
  RecommendationCard,
  StageSpine,
} from '@/components/campaign-overview';
import { ErrorState, SkeletonRows } from '@/components/states';
import { ApiError, api, type CampaignOverview } from '@/lib/api';
import { useWorkspace } from '@/lib/use-workspace';

/** Only while something is actually moving; stops the moment nothing is. */
const POLL_MS = 2500;

export default function OverviewPage({
  params,
}: {
  params: Promise<{ campaignId: string }>;
}) {
  const { campaignId } = use(params);
  const workspace = useWorkspace();
  const { organizationId } = workspace;

  const [view, setView] = useState<CampaignOverview | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!organizationId) return;
      const next = await api.getCampaignOverview(campaignId, organizationId, signal);
      if (!signal?.aborted) setView(next);
    },
    [campaignId, organizationId],
  );

  useEffect(() => {
    if (!organizationId) return undefined;
    const controller = new AbortController();
    setView(null);
    setError(null);
    load(controller.signal).catch((err: unknown) => {
      if (controller.signal.aborted) return;
      setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
    });
    return () => controller.abort();
  }, [load, organizationId]);

  // A dashboard that keeps polling a finished campaign is a dashboard nobody
  // leaves open. This stops as soon as no stage is running.
  const running = view?.stages.some((stage) => stage.state === 'RUNNING') ?? false;
  useEffect(() => {
    if (!running) return undefined;
    const timer = setTimeout(() => {
      void load().catch(() => undefined);
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [running, view, load]);

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

  return (
    <AppShell
      me={workspace.me}
      activeOrganizationId={organizationId}
      onOrganizationChange={workspace.setOrganizationId}
    >
      <div className="flex flex-wrap justify-between gap-4">
        <Link href="/app/campaigns" className="text-sm text-muted hover:underline">
          ← Campaigns
        </Link>
        {view ? (
          <Link
            href={`/app/campaigns/${campaignId}`}
            className="text-sm text-muted hover:underline"
          >
            Campaign Specification →
          </Link>
        ) : null}
      </div>

      {error && !view ? (
        <div className="mt-4">
          <ErrorState
            title={error.code === 'NOT_FOUND' ? 'Campaign not found' : 'Could not load this page'}
            message={error.message}
            requestId={error.requestId}
            onRetry={error.isRetryable ? () => void load() : undefined}
          />
        </div>
      ) : !view ? (
        <div className="mt-6">
          <SkeletonRows rows={5} />
        </div>
      ) : (
        <div className="mt-4 space-y-6">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{view.title}</h1>
            <p className="mt-1 text-sm text-muted">
              {view.brand_name} · {view.status.replace(/_/g, ' ').toLowerCase()}
            </p>
          </div>

          {error ? <ErrorState message={error.message} requestId={error.requestId} /> : null}

          <NextAction view={view} />

          <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
            <div className="space-y-6">
              <StageSpine view={view} />
              <FinalAssetStrip view={view} />
            </div>
            <div className="space-y-6">
              <CampaignFacts view={view} />
              <RecommendationCard view={view} />
              <BrandStatusCard view={view} />
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
