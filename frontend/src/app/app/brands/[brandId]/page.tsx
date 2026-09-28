'use client';

/**
 * The Brand Brain page: identity, coverage, documents, knowledge, proposals.
 *
 * While any document is mid-pipeline the page polls for status, so ingest
 * progress is visible rather than a blank wait (§17). Polling stops as soon as
 * every document reaches a terminal state.
 */

import { use, useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { AppShell } from '@/components/app-shell';
import {
  AssetsPanel,
  DocumentsPanel,
  KnowledgePanel,
  ProposalsPanel,
} from '@/components/brand-brain';
import { BrandCore, CampaignsUsingBrand } from '@/components/brand-core';
import { ErrorState, SectionHeader, SkeletonRows } from '@/components/ui';
import { ApiError, TERMINAL_STATUSES, api, type BrandBrain, type Campaign } from '@/lib/api';
import { useWorkspace } from '@/lib/use-workspace';

const POLL_MS = 1500;

export default function BrandBrainPage({ params }: { params: Promise<{ brandId: string }> }) {
  const { brandId } = use(params);
  const workspace = useWorkspace();
  const { organizationId } = workspace;

  const [brain, setBrain] = useState<BrandBrain | null>(null);
  /**
   * Campaigns written from this brand.
   *
   * The organization's campaign list filtered by `brand_id` — a real field on
   * every campaign row. Fetched separately from the brain so a slow campaign
   * list never delays the brand itself, and kept out of the poll loop because
   * campaigns do not change while a document is being ingested.
   */
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!organizationId) return undefined;
    const controller = new AbortController();
    setCampaigns(null);
    api
      .listCampaigns(organizationId, controller.signal)
      .then((page) => {
        if (!controller.signal.aborted) {
          setCampaigns(page.items.filter((c) => c.brand_id === brandId));
        }
      })
      // A failure here costs the campaigns section, not the brand page.
      .catch(() => undefined);
    return () => controller.abort();
  }, [brandId, organizationId]);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!organizationId) return;
      try {
        const result = await api.getBrain(brandId, organizationId, signal);
        if (!signal?.aborted) {
          setBrain(result);
          setError(null);
        }
      } catch (err) {
        if (signal?.aborted) return;
        setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
      }
    },
    [brandId, organizationId],
  );

  useEffect(() => {
    if (!organizationId) return undefined;
    const controller = new AbortController();
    setBrain(null);
    setError(null);
    void load(controller.signal);
    return () => controller.abort();
  }, [load, organizationId]);

  // Poll only while something is actually in flight.
  useEffect(() => {
    const pending = brain?.documents.some((d) => !TERMINAL_STATUSES.includes(d.status));
    if (!pending) return undefined;
    timer.current = setTimeout(() => void load(), POLL_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [brain, load]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
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
          code={workspace.error.code}
          requestId={workspace.error.requestId}
          onRetry={workspace.error.isRetryable ? workspace.reload : undefined}
        />
      </div>
    );
  }

  const brand = brain?.brand;

  return (
    <AppShell
      me={workspace.me}
      activeOrganizationId={organizationId}
      onOrganizationChange={workspace.setOrganizationId}
    >
      <Link href="/app/brands" className="text-sm text-muted hover:underline">
        ← Brands
      </Link>

      {error && !brain ? (
        <div className="mt-4">
          <ErrorState
            title={error.code === 'NOT_FOUND' ? 'Brand not found' : 'Could not load this brand'}
            message={error.message}
            code={error.code}
            requestId={error.requestId}
            onRetry={error.isRetryable ? () => void load() : undefined}
          />
        </div>
      ) : !brain || !brand ? (
        <div className="mt-6">
          <SkeletonRows rows={4} />
        </div>
      ) : (
        <div className="mt-4 space-y-section">
          <header>
            <p className="text-label uppercase text-muted">Brand</p>
            <h1 className="mt-2 text-h1">{brand.name}</h1>
            <p className="mt-2 max-w-content text-body text-muted">
              {brand.positioning ?? brand.description ?? 'No positioning captured yet.'}
            </p>
            {/* Industry sits with the name because it is identity, not a
                statistic. Everything else moved into Brand Core below.
                Deliberately not a `PlaceStamp`: that component announces
                itself as "Market", and an industry is not a market. */}
            {brand.industry ? (
              <p className="mt-3 text-label uppercase text-muted">
                <span className="sr-only">Industry: </span>
                {brand.industry}
              </p>
            ) : null}
          </header>

          {/* A failure anywhere in the pipeline is stated, not hidden. */}
          {brain.processing_errors.length ? (
            <div role="alert" className="rounded-lg border border-danger/40 bg-danger/5 p-4">
              <p className="text-sm font-medium">Some documents could not be processed</p>
              <ul className="mt-2 space-y-1 text-xs text-muted">
                {brain.processing_errors.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {error ? (
            <ErrorState message={error.message} requestId={error.requestId} />
          ) : null}

          <BrandCore brain={brain} />

          <CampaignsUsingBrand campaigns={campaigns ?? []} loading={campaigns === null} />

          <SectionHeader
            level={2}
            title="Knowledge sources"
            description="The documents this brand’s answers are retrieved from."
          />

          <DocumentsPanel
            documents={brain.documents}
            busy={busy}
            onUpload={(file) =>
              void run(() => api.uploadDocument(brandId, organizationId, file))
            }
            onAddText={(title, content) =>
              void run(() => api.addTextDocument(brandId, organizationId, title, content))
            }
          />

          <KnowledgePanel
            brandId={brandId}
            organizationId={organizationId}
            ready={brain.knowledge_ready}
            chunkCount={brain.chunk_count}
          />

          <ProposalsPanel
            facts={brain.proposed_facts}
            onDecide={(factId, status) =>
              void run(() => api.decideFact(brandId, factId, organizationId, status))
            }
          />

          <AssetsPanel
            assets={brain.assets}
            busy={busy}
            onUpload={(file, kind) =>
              void run(() => api.uploadAsset(brandId, organizationId, file, kind))
            }
          />
        </div>
      )}
    </AppShell>
  );
}
