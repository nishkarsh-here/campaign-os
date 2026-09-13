'use client';

/**
 * A single project: its details, and the campaigns inside it.
 *
 * The campaign list is filtered client-side from the organization's campaigns
 * rather than through a project-scoped endpoint. That keeps the API surface as
 * it is for a list that is small by construction — a project holds a handful
 * of campaigns, not thousands — and adding a filter parameter for it would be
 * a schema change for a page that already has the data.
 */

import { use, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AppShell } from '@/components/app-shell';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import { ApiError, api, type Campaign, type Project } from '@/lib/api';
import { useWorkspace } from '@/lib/use-workspace';

export default function ProjectPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = use(params);
  const workspace = useWorkspace();
  const { organizationId } = workspace;

  const [project, setProject] = useState<Project | null>(null);
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(() => {
    if (!organizationId) return undefined;
    const controller = new AbortController();
    // Clear first: switching organizations must not leave the previous
    // organization's project on screen while the new one loads.
    setProject(null);
    setCampaigns(null);
    setError(null);
    Promise.all([
      api.getProject(projectId, organizationId, controller.signal),
      api.listCampaigns(organizationId, controller.signal),
    ])
      .then(([result, page]) => {
        if (controller.signal.aborted) return;
        setProject(result);
        setCampaigns(page.items.filter((c) => c.project_id === projectId));
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
      });
    return () => controller.abort();
  }, [projectId, organizationId]);

  useEffect(load, [load]);

  // A /me failure leaves organizationId null, so this page's own fetch never
  // runs and it would otherwise show a loading skeleton for ever. Surface the
  // workspace error instead — every async surface owes all four states
  // (UI_SPEC "Design principles", CLAUDE.md Definition of Done).
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
      <Link href="/app" className="text-sm text-muted hover:underline">
        ← Projects
      </Link>

      <div className="mt-4">
        {error ? (
          // A project in another organization returns 404, exactly as a
          // non-existent one does (API_SPEC §Scope).
          <ErrorState
            title={error.code === 'NOT_FOUND' ? 'Project not found' : 'Could not load this project'}
            message={error.message}
            requestId={error.requestId}
            onRetry={error.isRetryable ? load : undefined}
          />
        ) : project === null ? (
          <SkeletonRows rows={2} />
        ) : (
          <>
            <h1 className="text-2xl font-semibold tracking-tight">{project.name}</h1>
            <p className="mt-1 text-muted">{project.description ?? 'No description yet.'}</p>

            <h2 className="mt-8 text-sm font-medium">Campaigns</h2>
            {campaigns === null ? (
              <div className="mt-3">
                <SkeletonRows rows={2} />
              </div>
            ) : campaigns.length === 0 ? (
              <div className="mt-3">
                <EmptyState
                  title="No campaigns in this project"
                  description="Start one from the campaigns screen and it will appear here."
                  action={
                    <Link
                      href="/app/campaigns"
                      className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40"
                    >
                      Go to campaigns
                    </Link>
                  }
                />
              </div>
            ) : (
              <ul className="mt-3 divide-y divide-line rounded-lg border border-line">
                {campaigns.map((campaign) => (
                  <li key={campaign.id}>
                    <Link
                      href={`/app/campaigns/${campaign.id}/overview`}
                      className="flex items-center justify-between px-4 py-4 hover:bg-line/20"
                    >
                      <span className="text-sm font-medium">{campaign.title}</span>
                      <span className="text-xs text-muted">
                        {campaign.status.replace(/_/g, ' ').toLowerCase()}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
