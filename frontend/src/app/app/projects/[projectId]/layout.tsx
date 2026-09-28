'use client';

/**
 * The project frame.
 *
 * A client-component layout, for the same reason the campaign one is: it is not
 * unmounted as the child route changes, so the project's identity persists
 * rather than being re-fetched and re-rendered by whatever page you land on.
 *
 * It resolves the project, its campaigns, the brands those campaigns use and
 * the markets they run in — then states all four in the header, which is the
 * audit's "a project should be a scope, not a page" finding turned into
 * something a person can see.
 */

import { use, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AppShell } from '@/components/app-shell';
import { ErrorState, SkeletonRows } from '@/components/ui';
import {
  ApiError,
  api,
  type Brand,
  type Campaign,
  type CampaignSpecification,
  type Project,
} from '@/lib/api';
import { ProjectScopeProvider } from '@/lib/project-context';
import { groupByMarket, type MarketGroup } from '@/lib/market';
import { mapWithConcurrency } from '@/lib/concurrency';
import { useWorkspace } from '@/lib/use-workspace';

const SPEC_CONCURRENCY = 6;

export default function ProjectLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = use(params);
  const workspace = useWorkspace();
  const { organizationId } = workspace;

  const [project, setProject] = useState<Project | null>(null);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [markets, setMarkets] = useState<MarketGroup[]>([]);
  const [specs, setSpecs] = useState<Map<string, CampaignSpecification | null>>(new Map());
  const [resolving, setResolving] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!organizationId) return undefined;
    const controller = new AbortController();
    // Cleared first: switching organizations must not leave the previous
    // organization's project on screen while the new one loads.
    setProject(null);
    setCampaigns([]);
    setBrands([]);
    setMarkets([]);
    setSpecs(new Map());
    setResolving(true);
    setError(null);

    Promise.all([
      api.getProject(projectId, organizationId, controller.signal),
      api.listCampaigns(organizationId, controller.signal),
      api.listBrands(organizationId, controller.signal),
    ])
      .then(async ([result, campaignPage, brandPage]) => {
        if (controller.signal.aborted) return;
        const mine = campaignPage.items.filter((c) => c.project_id === projectId);
        const brandIds = new Set(mine.map((c) => c.brand_id));
        setProject(result);
        setCampaigns(mine);
        setBrands(brandPage.items.filter((b) => brandIds.has(b.id)));

        // Markets need each campaign's specification; there is no aggregate
        // endpoint. Bounded fan-out over this project's campaigns only.
        const resolved = await mapWithConcurrency(mine, SPEC_CONCURRENCY, async (campaign) => {
          const view = await api.getCreativeContext(campaign.id, organizationId, controller.signal);
          return { campaignId: campaign.id, specification: view.context.specification };
        });
        if (controller.signal.aborted) return;
        const entries = resolved.filter((r): r is NonNullable<typeof r> => r !== null);
        setSpecs(new Map(entries.map((e) => [e.campaignId, e.specification])));
        setMarkets(groupByMarket(entries));
        setResolving(false);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
        setResolving(false);
      });

    return () => controller.abort();
  }, [projectId, organizationId, nonce]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  if (workspace.loading) {
    return (
      <div className="mx-auto max-w-page px-gutter py-10 sm:px-gutter-lg">
        <SkeletonRows rows={4} />
      </div>
    );
  }
  if (workspace.error) {
    return (
      <div className="mx-auto max-w-page px-gutter py-10 sm:px-gutter-lg">
        <ErrorState
          title="Cannot load your workspace"
          message={workspace.error.message}
          code={workspace.error.code}
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
      header={
        <div>
          <Link
            href="/app"
            className="text-label uppercase text-muted transition-colors duration-fast hover:text-ink"
          >
            ← Command Center
          </Link>
          <h1 className="mt-2 text-h1">{project?.name ?? 'Project'}</h1>
          {project?.description ? (
            <p className="mt-1 max-w-content text-small text-muted">{project.description}</p>
          ) : null}

          {/*
            The scope, stated. Every value is derived from this project's own
            campaigns — a project row carries none of it — so each says what it
            was counted from rather than presenting itself as a stored figure.
          */}
          <dl className="mt-5 flex flex-wrap gap-x-8 gap-y-3 border-t border-line pt-4">
            <ScopeFact label="Brand" value={brands.map((b) => b.name).join(' · ')} />
            <ScopeFact
              label={markets.length === 1 ? 'Market' : 'Markets'}
              value={markets.map((m) => m.region).join(' · ')}
              pending={resolving}
            />
            <ScopeFact
              label="Campaigns"
              value={campaigns.length > 0 ? String(campaigns.length) : ''}
            />
          </dl>
        </div>
      }
    >
      {error ? (
        // A project in another organization returns 404, exactly as a
        // non-existent one does (API_SPEC §Scope).
        <ErrorState
          title={error.code === 'NOT_FOUND' ? 'Project not found' : 'Could not load this project'}
          message={error.message}
          code={error.code}
          requestId={error.requestId}
          onRetry={error.isRetryable ? refresh : undefined}
        />
      ) : (
        <ProjectScopeProvider
          value={{
            projectId,
            organizationId,
            project,
            campaigns,
            brands,
            markets,
            specs,
            resolving,
            refresh,
          }}
        >
          {children}
        </ProjectScopeProvider>
      )}
    </AppShell>
  );
}

/**
 * One line of project scope.
 *
 * An empty value renders an em dash rather than being hidden: "this project has
 * no market yet" is information, and a row that disappears reads as a layout
 * that forgot it.
 */
function ScopeFact({
  label,
  value,
  pending,
}: {
  label: string;
  value: string;
  pending?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-label uppercase text-muted">{label}</dt>
      <dd className="mt-0.5 truncate text-small text-ink">
        {pending && !value ? (
          <span className="text-muted">Resolving…</span>
        ) : value ? (
          value
        ) : (
          <span className="text-muted">—</span>
        )}
      </dd>
    </div>
  );
}
