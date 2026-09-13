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
  CoveragePanel,
  DocumentsPanel,
  KnowledgePanel,
  ProposalsPanel,
} from '@/components/brand-brain';
import { ErrorState, SkeletonRows } from '@/components/states';
import { ApiError, TERMINAL_STATUSES, api, type BrandBrain } from '@/lib/api';
import { useWorkspace } from '@/lib/use-workspace';

const POLL_MS = 1500;

export default function BrandBrainPage({ params }: { params: Promise<{ brandId: string }> }) {
  const { brandId } = use(params);
  const workspace = useWorkspace();
  const { organizationId } = workspace;

  const [brain, setBrain] = useState<BrandBrain | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

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
            requestId={error.requestId}
            onRetry={error.isRetryable ? () => void load() : undefined}
          />
        </div>
      ) : !brain || !brand ? (
        <div className="mt-6">
          <SkeletonRows rows={4} />
        </div>
      ) : (
        <div className="mt-4 space-y-6">
          <header>
            <h1 className="text-2xl font-semibold tracking-tight">{brand.name}</h1>
            <p className="mt-1 text-sm text-muted">
              {brand.positioning ?? brand.description ?? 'No positioning captured yet.'}
            </p>
            <dl className="mt-4 grid gap-4 sm:grid-cols-3">
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted">Industry</dt>
                <dd className="mt-0.5 text-sm">{brand.industry ?? '—'}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted">Audience</dt>
                <dd className="mt-0.5 text-sm">{brand.audience_description ?? '—'}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-muted">Tone</dt>
                <dd className="mt-0.5 text-sm">
                  {brand.voice.tone_attributes.length
                    ? brand.voice.tone_attributes.join(', ')
                    : '—'}
                </dd>
              </div>
            </dl>
            {brand.colors.length ? (
              <div className="mt-4 flex items-center gap-2">
                {brand.colors.map((colour) => (
                  <span key={colour.hex} className="flex items-center gap-1.5 text-xs text-muted">
                    <span
                      className="inline-block h-4 w-4 rounded border border-line"
                      style={{ background: colour.hex }}
                    />
                    {colour.name}
                  </span>
                ))}
              </div>
            ) : null}
          </header>

          {/* A failure anywhere in the pipeline is stated, not hidden. */}
          {brain.processing_errors.length ? (
            <div role="alert" className="rounded-lg border border-red-500/40 bg-red-500/5 p-4">
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

          <CoveragePanel fields={brain.field_status} />

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
