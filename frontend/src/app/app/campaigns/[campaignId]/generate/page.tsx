'use client';

/**
 * The generation screen.
 *
 * Generation is asynchronous by design: starting a batch returns immediately
 * with every job `PENDING`, and this page polls until each one is terminal.
 * Polling rather than a socket because polling cannot silently die
 * (API_SPEC §Polling contract) — and a generation screen that stops updating
 * without saying so is the worst failure this page could have.
 */

import { use, useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { AppShell } from '@/components/app-shell';
import {
  CanonicalPromptPanel,
  JobBoard,
  PlateGallery,
  ProviderPrompts,
} from '@/components/generation';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import { ApiError, api, type Campaign, type GenerationView } from '@/lib/api';
import { useWorkspace } from '@/lib/use-workspace';

/** Matches the documented polling contract: 1.5s, backing off to 5s after 60s. */
const POLL_MS = 1500;
const SLOW_POLL_MS = 5000;
const BACKOFF_AFTER_MS = 60_000;

export default function GeneratePage({
  params,
}: {
  params: Promise<{ campaignId: string }>;
}) {
  const { campaignId } = use(params);
  const workspace = useWorkspace();
  const { organizationId } = workspace;

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [view, setView] = useState<GenerationView | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const startedPollingAt = useRef<number | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!organizationId) return;
      const [detail, generation] = await Promise.all([
        api.getCampaign(campaignId, organizationId, signal),
        api.getGeneration(campaignId, organizationId, signal),
      ]);
      if (signal?.aborted) return;
      setCampaign(detail);
      setView(generation);
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

  // Poll only while something is actually running. A finished batch stops
  // polling entirely rather than asking the server the same question forever.
  const pending = view ? view.jobs.some((job) => !isTerminal(job.status)) : false;

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
    // `view` is the dependency on purpose: each completed poll schedules the next.
  }, [pending, view, load]);

  async function run(action: () => Promise<GenerationView>) {
    setBusy(true);
    setError(null);
    try {
      setView(await action());
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

  return (
    <AppShell
      me={workspace.me}
      activeOrganizationId={organizationId}
      onOrganizationChange={workspace.setOrganizationId}
    >
      <div className="flex flex-wrap justify-between gap-4">
        <Link
          href={`/app/campaigns/${campaignId}/creative`}
          className="text-sm text-muted hover:underline"
        >
          ← Creative Specification
        </Link>
        {/* Only once there is something to judge. */}
        {view && view.assets.length ? (
          <Link
            href={`/app/campaigns/${campaignId}/evaluate`}
            className="text-sm text-muted hover:underline"
          >
            Evaluate creatives →
          </Link>
        ) : null}
      </div>

      {error && !campaign ? (
        <div className="mt-4">
          <ErrorState
            title={error.code === 'NOT_FOUND' ? 'Campaign not found' : 'Could not load this page'}
            message={error.message}
            requestId={error.requestId}
            onRetry={error.isRetryable ? () => void load() : undefined}
          />
        </div>
      ) : !campaign || !view ? (
        <div className="mt-6">
          <SkeletonRows rows={4} />
        </div>
      ) : (
        <div className="mt-4 space-y-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">{campaign.title}</h1>
              <p className="mt-1 text-sm text-muted">
                {view.can_generate
                  ? `Generating from approved specification v${view.specification_version}.`
                  : 'Generation is not open yet.'}
              </p>
            </div>
            {view.can_generate ? (
              <div className="flex shrink-0 flex-wrap gap-2">
                <button
                  type="button"
                  disabled={busy || pending}
                  onClick={() => void run(() => api.compilePrompts(campaignId, organizationId))}
                  className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40 disabled:opacity-50"
                >
                  Compile prompts
                </button>
                <button
                  type="button"
                  disabled={busy || pending}
                  onClick={() => void run(() => api.startGeneration(campaignId, organizationId))}
                  className="rounded-md border border-line bg-line/30 px-3 py-1.5 text-sm hover:bg-line/50 disabled:opacity-50"
                >
                  {pending ? 'Generating…' : 'Generate creatives'}
                </button>
              </div>
            ) : null}
          </div>

          {error ? <ErrorState message={error.message} requestId={error.requestId} /> : null}

          {!view.can_generate ? (
            <EmptyState
              title="Approve the Creative Specification first"
              description={
                view.blocked_reason ??
                'Generation works from an approved plan, so the image a provider returns can always be traced back to something a human signed off.'
              }
              action={
                <Link
                  href={`/app/campaigns/${campaignId}/creative`}
                  className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40"
                >
                  Back to the specification
                </Link>
              }
            />
          ) : (
            <>
              <JobBoard
                view={view}
                busy={busy}
                onRetry={(jobId) =>
                  void run(() => api.retryGenerationJob(campaignId, jobId, organizationId))
                }
              />

              {view.assets.length ? (
                <PlateGallery
                  assets={view.assets}
                  jobs={view.jobs}
                  selectedIds={selectedIds}
                  onToggleSelect={(id) =>
                    setSelectedIds((current) =>
                      current.includes(id)
                        ? current.filter((existing) => existing !== id)
                        : [...current, id],
                    )
                  }
                />
              ) : view.jobs.length === 0 ? (
                <EmptyState
                  title="Nothing generated yet"
                  description="Compile the prompts to see exactly what each provider will be asked, or generate straight away."
                />
              ) : null}

              {view.canonical_prompt ? (
                <CanonicalPromptPanel prompt={view.canonical_prompt} />
              ) : null}
              <ProviderPrompts prompts={view.prompts} />
            </>
          )}
        </div>
      )}
    </AppShell>
  );
}

function isTerminal(status: string): boolean {
  return status === 'COMPLETED' || status === 'FAILED' || status === 'CANCELLED';
}
