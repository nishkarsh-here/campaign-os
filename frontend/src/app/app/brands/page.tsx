'use client';

/**
 * Brands — the intelligence layer, listed.
 *
 * A brand card shows what the brand actually holds: its positioning, its
 * palette, its tone, and how many campaigns have been written from it. All of
 * it comes from the brand row itself plus the campaign list, so the page costs
 * two requests however many brands there are.
 *
 * What a card deliberately omits is how much of the brand is confirmed. That
 * lives in `field_status` on `/brands/:id/brain`, which is one request per
 * brand — an eight-brand list would open eight. It is the first thing on the
 * brand's own page instead.
 */

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AppShell } from '@/components/app-shell';
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Reveal,
  SectionHeader,
  SkeletonRows,
} from '@/components/ui';
import { ApiError, api, type Brand, type Campaign } from '@/lib/api';
import { capabilitiesFor } from '@/lib/capabilities';
import { useWorkspace } from '@/lib/use-workspace';

export default function BrandsPage() {
  const workspace = useWorkspace();
  const { organizationId } = workspace;

  const [brands, setBrands] = useState<Brand[] | null>(null);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [name, setName] = useState('');
  const [industry, setIndustry] = useState('');
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    if (!organizationId) return undefined;
    const controller = new AbortController();
    setBrands(null);
    setError(null);
    Promise.all([
      api.listBrands(organizationId, controller.signal),
      api.listCampaigns(organizationId, controller.signal),
    ])
      .then(([brandPage, campaignPage]) => {
        if (controller.signal.aborted) return;
        setBrands(brandPage.items);
        setCampaigns(campaignPage.items);
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

  const membership = workspace.me?.organizations.find(
    (m) => m.organization.id === organizationId,
  );
  const canEditBrand = capabilitiesFor(
    membership?.role ?? (workspace.me ? 'viewer' : null),
  ).can('edit_brand');

  return (
    <AppShell
      me={workspace.me}
      activeOrganizationId={organizationId}
      onOrganizationChange={workspace.setOrganizationId}
    >
      <SectionHeader
        level={1}
        title="Brands"
        description="A brand holds its identity, its source documents, and the knowledge every campaign is written from."
      />

      <div className="mt-lg">
        {error ? (
          <ErrorState
            message={error.message}
            code={error.code}
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
          <ul className="grid gap-4 lg:grid-cols-2">
            {brands.map((brand, i) => (
              <BrandCard
                key={brand.id}
                brand={brand}
                used={campaigns.filter((c) => c.brand_id === brand.id).length}
                index={i}
              />
            ))}
          </ul>
        )}
      </div>

      {/* Creating a brand changes what campaigns may claim, so it is a brand
          manager's affordance. Presentation only — the endpoint does not yet
          check a role. */}
      {canEditBrand ? (
        <Card className="mt-section">
          <h2 className="text-h3">Add a brand</h2>
          <form onSubmit={createBrand} className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
            <Field label="Brand name" className="flex-1">
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Aarohan Foods" />
            </Field>
            <Field label="Industry" hint="Optional." className="flex-1">
              <Input
                value={industry}
                onChange={(e) => setIndustry(e.target.value)}
                placeholder="Packaged foods"
              />
            </Field>
            <Button type="submit" variant="primary" size="lg" disabled={creating || !name.trim()}>
              {creating ? 'Creating…' : 'Create brand'}
            </Button>
          </form>
        </Card>
      ) : null}
    </AppShell>
  );
}

function BrandCard({ brand, used, index }: { brand: Brand; used: number; index: number }) {
  return (
    <Reveal as="li" index={index}>
      <Card padding={false} className="h-full">
        <Link
          href={`/app/brands/${brand.id}`}
          className="flex h-full flex-col p-5 transition-colors duration-fast hover:bg-line/20"
        >
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h2 className="text-h3">{brand.name}</h2>
              {brand.industry ? (
                <p className="mt-1 text-label uppercase text-muted">{brand.industry}</p>
              ) : null}
            </div>
            {/* The palette, where there is one. No placeholder swatches: an
                invented brand colour is an invented brand asset. */}
            {brand.colors.length > 0 ? (
              <span className="flex shrink-0 gap-1" aria-hidden="true">
                {brand.colors.slice(0, 5).map((colour) => (
                  <span
                    key={colour.hex}
                    title={`${colour.name} ${colour.hex}`}
                    className="h-5 w-5 rounded-sm border border-line"
                    style={{ background: colour.hex }}
                  />
                ))}
              </span>
            ) : null}
          </div>

          {brand.positioning ? (
            <p className="mt-3 line-clamp-2 text-small text-muted">{brand.positioning}</p>
          ) : (
            <p className="mt-3 text-small text-muted">No positioning captured yet.</p>
          )}

          {brand.voice.tone_attributes.length > 0 ? (
            <p className="mt-3 text-caption text-muted">
              <span className="text-label uppercase">Tone</span>{' '}
              {brand.voice.tone_attributes.join(' · ')}
            </p>
          ) : null}

          <p className="mt-auto flex flex-wrap gap-x-5 gap-y-1 border-t border-line pt-3 text-label uppercase text-muted">
            {/* Counted from the campaign list already fetched. */}
            <span>
              {used} {used === 1 ? 'campaign' : 'campaigns'}
            </span>
            {brand.approved_claims.length > 0 ? (
              <span>{brand.approved_claims.length} approved claims</span>
            ) : null}
            {brand.prohibited_claims.length > 0 ? (
              <span>{brand.prohibited_claims.length} prohibited</span>
            ) : null}
          </p>
        </Link>
      </Card>
    </Reveal>
  );
}
