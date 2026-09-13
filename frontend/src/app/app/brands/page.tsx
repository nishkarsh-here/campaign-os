'use client';

/** Brand list and creation — the entry point to the Brand Brain. */

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AppShell } from '@/components/app-shell';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import { ApiError, api, type Brand } from '@/lib/api';
import { useWorkspace } from '@/lib/use-workspace';

export default function BrandsPage() {
  const workspace = useWorkspace();
  const { organizationId } = workspace;

  const [brands, setBrands] = useState<Brand[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [name, setName] = useState('');
  const [industry, setIndustry] = useState('');
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    if (!organizationId) return undefined;
    const controller = new AbortController();
    setBrands(null);
    setError(null);
    api
      .listBrands(organizationId, controller.signal)
      .then((page) => {
        if (!controller.signal.aborted) setBrands(page.items);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
      });
    return () => controller.abort();
  }, [organizationId]);

  useEffect(load, [load]);

  async function createBrand(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim() || !organizationId) return;
    setCreating(true);
    setError(null);
    try {
      const brand = await api.createBrand(organizationId, {
        name: name.trim(),
        ...(industry.trim() ? { industry: industry.trim() } : {}),
      });
      setBrands((current) => [...(current ?? []), brand]);
      setName('');
      setIndustry('');
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
      <div className="flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Brands</h1>
          <p className="mt-1 text-sm text-muted">
            A brand holds its identity, its source documents, and the knowledge campaigns retrieve
            from.
          </p>
        </div>
      </div>

      <form onSubmit={createBrand} className="mt-6 flex flex-wrap gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Brand name"
          aria-label="Brand name"
          className="min-w-56 flex-1 rounded-md border border-line bg-transparent px-3 py-2 text-sm"
        />
        <input
          value={industry}
          onChange={(e) => setIndustry(e.target.value)}
          placeholder="Industry (optional)"
          aria-label="Industry"
          className="min-w-48 flex-1 rounded-md border border-line bg-transparent px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={creating || !name.trim()}
          className="rounded-md bg-ink px-4 py-2 text-sm font-medium text-surface disabled:opacity-40"
        >
          {creating ? 'Creating…' : 'Create brand'}
        </button>
      </form>

      <div className="mt-8">
        {error ? (
          <ErrorState
            message={error.message}
            requestId={error.requestId}
            onRetry={error.isRetryable ? load : undefined}
          />
        ) : brands === null ? (
          <SkeletonRows />
        ) : brands.length === 0 ? (
          <EmptyState
            title="No brands yet"
            description="Create a brand, then upload its guidelines to build the Brand Brain."
          />
        ) : (
          <ul className="divide-y divide-line rounded-lg border border-line">
            {brands.map((brand) => (
              <li key={brand.id}>
                <Link
                  href={`/app/brands/${brand.id}`}
                  className="flex items-center justify-between px-4 py-4 hover:bg-line/20"
                >
                  <span>
                    <span className="text-sm font-medium">{brand.name}</span>
                    {brand.positioning ? (
                      <span className="mt-0.5 block max-w-xl truncate text-xs text-muted">
                        {brand.positioning}
                      </span>
                    ) : null}
                  </span>
                  <span className="text-xs text-muted">{brand.industry ?? ''}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </AppShell>
  );
}
