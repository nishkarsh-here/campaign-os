'use client';

/**
 * The campaign workspace frame.
 *
 * This is where UI-2A's information architecture actually lands. A layout
 * rather than a shared component, because a client-component layout is not
 * unmounted when the child route changes — so the Meridian, the organization
 * and the campaign's identity survive a move from Creative to Generate instead
 * of being rebuilt by the next page.
 *
 * It owns what all eight stage screens previously each owned: resolving the
 * caller, the loading gate, the error gate, the shell, and the navigation. The
 * pages are now just their stage.
 */

import { use, useCallback, useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { AppShell } from '@/components/app-shell';
import { ErrorState, Meridian, SkeletonRows } from '@/components/ui';
import { CampaignContextRail, CampaignIdentityBar } from '@/components/campaign-workspace';
import { ApiError, api, type CampaignOverview, type CreativeContext } from '@/lib/api';
import { CampaignWorkspaceProvider } from '@/lib/campaign-context';
import { capabilitiesFor } from '@/lib/capabilities';
import { currentNodeId, resolveJourney } from '@/lib/nav';
import { useWorkspace } from '@/lib/use-workspace';

export default function CampaignLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ campaignId: string }>;
}) {
  const { campaignId } = use(params);
  const workspace = useWorkspace();
  const { organizationId } = workspace;
  const pathname = usePathname();

  const [overview, setOverview] = useState<CampaignOverview | null>(null);
  const [creativeContext, setCreativeContext] = useState<CreativeContext | null>(null);
  const [overviewError, setOverviewError] = useState<ApiError | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!organizationId) return undefined;
    const controller = new AbortController();

    // The summary drives the Meridian. A failure is not fatal to navigation —
    // `resolveJourney` renders every node as "available" rather than guessing —
    // but it must still be *recorded*, or a campaign that cannot be read shows
    // a loading skeleton for ever.
    api
      .getCampaignOverview(campaignId, organizationId, controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) setOverview(next);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setOverviewError(
          err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0),
        );
      });

    // Best-effort, purely for the place stamp. A campaign still in discovery
    // has no specification, which is a normal state and not an error worth
    // showing anyone.
    api
      .getCreativeContext(campaignId, organizationId, controller.signal)
      .then((view) => {
        if (!controller.signal.aborted) setCreativeContext(view.context);
      })
      .catch(() => undefined);

    return () => controller.abort();
  }, [campaignId, organizationId, nonce]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  // Resolved even while `overview` is null, so the rail renders immediately on
  // first paint instead of flickering in once a second request lands.
  const specification = creativeContext?.specification ?? null;
  /**
   * A campaign that is absent or forbidden cannot be worked on at any stage, so
   * the frame reports it instead of handing pages a permanently empty summary.
   * Every other failure — a timeout, a 500 — leaves navigation usable and is
   * surfaced by the page that needs the data.
   */
  const fatal =
    overviewError?.code === 'NOT_FOUND' || overviewError?.code === 'FORBIDDEN';

  // Resolved here rather than in each stage page, so the context rail and every
  // screen beneath it agree about what this person may do.
  const membership = workspace.me?.organizations.find(
    (m) => m.organization.id === organizationId,
  );
  const capabilities = capabilitiesFor(membership?.role ?? (workspace.me ? 'viewer' : null));
  const nodes = resolveJourney(campaignId, overview);
  const currentId = currentNodeId(campaignId, pathname);
  const rail = <Meridian nodes={nodes} currentId={currentId} />;

  /**
   * Compose gets the full width.
   *
   * Every other stage is reading, and the context rail earns its place beside
   * the text. Compose is a production workspace with three zones of its own —
   * layers, canvas, inspector — and a fourth column squeezes the canvas to a
   * couple of hundred pixels, which is the one thing that screen must not do.
   * Nothing is lost: the campaign, brand, market and version are all stated on
   * the final-asset panel, where they belong to the deliverable rather than
   * floating beside it.
   */
  const wantsFullWidth = pathname.endsWith('/compose');

  // The caller has to be known before anything else can render: the shell
  // needs the organization, and every stage request is scoped by it.
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
      rail={rail}
      wide={wantsFullWidth}
      header={
        <CampaignIdentityBar
          overview={overview}
          specification={specification}
          campaignId={campaignId}
        />
      }
      aside={
        wantsFullWidth ? undefined : (
          <CampaignContextRail
            campaignId={campaignId}
            overview={overview}
            specification={specification}
            capabilities={capabilities}
          />
        )
      }
    >
      <CampaignWorkspaceProvider
        value={{
          campaignId,
          organizationId,
          me: workspace.me,
          overview,
          specification,
          creativeContext,
          overviewError,
          refresh,
        }}
      >
        {children}
      </CampaignWorkspaceProvider>
    </AppShell>
  );
}
