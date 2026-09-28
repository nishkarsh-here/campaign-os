'use client';

/** Campaign list and creation. A campaign always names a brand. */

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AppShell } from '@/components/app-shell';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import { ApiError, api, type Brand, type Campaign } from '@/lib/api';
import { useWorkspace } from '@/lib/use-workspace';

const STATUS_LABEL: Record<string, string> = {
  DRAFT: 'Not started',
  INTERVIEWING: 'In discovery',
  SPECIFICATION_READY: 'Specification ready',
  SPECIFICATION_CONFIRMED: 'Confirmed',
  FAILED: 'Failed',
  CANCELLED: 'Cancelled',
};

export default function CampaignsPage() {
  const workspace = useWorkspace();
  const { organizationId } = workspace;

  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [title, setTitle] = useState('');
  const [brandId, setBrandId] = useState('');
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    if (!organizationId) return undefined;
    const controller = new AbortController();
    setCampaigns(null);
    setError(null);
    Promise.all([
      api.listCampaigns(organizationId, controller.signal),
      api.listBrands(organizationId, controller.signal),
    ])
      .then(([campaignPage, brandPage]) => {
        if (controller.signal.aborted) return;
        setCampaigns(campaignPage.items);
        setBrands(brandPage.items);
        setBrandId((current) => current || (brandPage.items[0]?.id ?? ''));
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
      });
    return () => controller.abort();
  }, [organizationId]);

  useEffect(load, [load]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim() || !brandId || !organizationId) return;
    setCreating(true);
    setError(null);
    try {
      const campaign = await api.createCampaign(organizationId, brandId, title.trim());
      setCampaigns((current) => [campaign, ...(current ?? [])]);
      setTitle('');
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
    } finally {
      setCreating(false);
    }
  }

  if (workspace.loading) {
    return (
      <div className="mx-auto max-w-5xl px-6 py-10">
        <SkeletonRows rows={4} />
      </div>
    );
  }
  if (workspace.error) {
    return (
      <div className="mx-auto max-w-5xl px-6 py-10">
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
    >
      <h1 className="text-2xl font-semibold tracking-tight">Campaigns</h1>
      <p className="mt-1 text-sm text-muted">
        Describe a campaign in your own words. We&apos;ll turn it into a specification.
      </p>

      {brands.length === 0 && campaigns !== null ? (
        <div className="mt-6">
          <EmptyState
            title="Create a brand first"
            description="A campaign draws on its brand's knowledge, so it needs one to start from."
            action={
              <Link
                href="/app/brands"
                className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-surface"
              >
                Go to brands
              </Link>
            }
          />
        </div>
      ) : (
        <form onSubmit={create} className="mt-6 flex flex-wrap gap-2">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Campaign name"
            aria-label="Campaign name"
            className="min-w-56 flex-1 rounded-md border border-line bg-transparent px-3 py-2 text-sm"
          />
          <select
            value={brandId}
            onChange={(e) => setBrandId(e.target.value)}
            aria-label="Brand"
            className="rounded-md border border-line bg-transparent px-3 py-2 text-sm"
          >
            {brands.map((brand) => (
              <option key={brand.id} value={brand.id}>
                {brand.name}
              </option>
            ))}
          </select>
          <button
            type="submit"
            disabled={creating || !title.trim() || !brandId}
            className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-surface disabled:opacity-40"
          >
            {creating ? 'Creating…' : 'New campaign'}
          </button>
        </form>
      )}

      <div className="mt-8">
        {error ? (
          <ErrorState
            message={error.message}
            code={error.code}
            requestId={error.requestId}
            onRetry={error.isRetryable ? load : undefined}
          />
        ) : campaigns === null ? (
          <SkeletonRows />
        ) : campaigns.length === 0 ? (
          <EmptyState
            title="No campaigns yet"
            description="Start one and we'll ask what we need to know."
          />
        ) : (
          <ul className="divide-y divide-line rounded-lg border border-line">
            {campaigns.map((campaign) => (
              <li key={campaign.id}>
                <Link
                  href={`/app/campaigns/${campaign.id}/overview`}
                  className="flex items-center justify-between px-4 py-4 hover:bg-line/20"
                >
                  <span className="text-sm font-medium">{campaign.title}</span>
                  <span className="text-xs text-muted">
                    {STATUS_LABEL[campaign.status] ?? campaign.status}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </AppShell>
  );
}
