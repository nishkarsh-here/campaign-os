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
import { CanonicalPromptPanel, ProviderPrompts } from '@/components/generation';
import { GenerationStudio } from '@/components/generation-studio';
import { Button, ErrorState, SkeletonRows } from '@/components/ui';
import { ApiError, api, type Campaign, type GenerationView } from '@/lib/api';
import { useCampaignWorkspace } from '@/lib/campaign-context';
import { capabilitiesFor } from '@/lib/capabilities';

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
  const { organizationId, me } = useCampaignWorkspace();
  const membership = me?.organizations.find((m) => m.organization.id === organizationId);
  const capabilities = capabilitiesFor(membership?.role ?? (me ? 'viewer' : null));

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [view, setView] = useState<GenerationView | null>(null);
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

  return (
    <>
      {error && !campaign ? (
        <div className="mt-4">
          <ErrorState
            title={error.code === 'NOT_FOUND' ? 'Campaign not found' : 'Could not load this page'}
            message={error.message}
            code={error.code}
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
          {/* The heading and the stage. The control that generates belongs to
              the studio below — a second one here meant two buttons starting
              the same work, one of them labelled differently. */}
          <div>
            <h2 className="text-h2">Generate</h2>
            <p className="mt-1 max-w-content text-body text-muted">
              {view.can_generate
                ? `Building the visuals from approved creative plan v${view.specification_version}.`
                : 'Generation is not open yet.'}
            </p>
          </div>

          {error ? <ErrorState message={error.message} requestId={error.requestId} /> : null}

          <GenerationStudio
            view={view}
            capabilities={capabilities}
            busy={busy || pending}
            onGenerate={() => void run(() => api.startGeneration(campaignId, organizationId))}
            onRetry={(jobId) =>
              void run(() => api.retryGenerationJob(campaignId, jobId, organizationId))
            }
          />

          {/*
            What each provider was actually asked.

            Folded away rather than removed: a prompt is a build artefact and
            the people who need it really need it, but it is not what this
            screen is about. The canonical prompt is provider-neutral; each
            provider's own rendering sits beside it.
          */}
          {view.canonical_prompt || view.prompts.length > 0 ? (
            <details className="rounded-lg border border-line">
              <summary className="cursor-pointer px-5 py-4 text-label uppercase text-muted transition-colors duration-fast hover:text-ink">
                What the providers were asked
              </summary>
              <div className="space-y-6 border-t border-line p-5">
                {view.canonical_prompt ? (
                  <CanonicalPromptPanel prompt={view.canonical_prompt} />
                ) : null}
                <ProviderPrompts prompts={view.prompts} />
                {/* Recompiling belongs beside what it recompiles. In the page
                    header it sat next to "Generate" looking like a step
                    someone had to take first, which it is not — generation
                    compiles for itself. */}
                {view.can_generate && capabilities.can('edit_campaign') ? (
                  <div className="border-t border-line pt-5">
                    <Button
                      variant="secondary"
                      disabled={busy || pending}
                      onClick={() => void run(() => api.compilePrompts(campaignId, organizationId))}
                    >
                      Compile these again from the plan
                    </Button>
                    <p className="mt-2 text-caption text-muted">
                      A prompt is a build artefact: it is regenerated from the approved plan, and
                      never edited here.
                    </p>
                  </div>
                ) : null}
              </div>
            </details>
          ) : null}
        </div>
      )}
    </>
  );
}

function isTerminal(status: string): boolean {
  return status === 'COMPLETED' || status === 'FAILED' || status === 'CANCELLED';
}
