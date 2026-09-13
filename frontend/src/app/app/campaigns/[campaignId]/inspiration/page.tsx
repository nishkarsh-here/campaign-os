'use client';

/**
 * Campaign inspiration: references, their Style DNA, visual calibration, and
 * the assembled Creative Context.
 *
 * A separate route from discovery on purpose — discovery is a conversation,
 * this is a visual workspace, and cramming both into one page would serve
 * neither.
 */

import { use, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AppShell } from '@/components/app-shell';
import {
  CreativeContextPanel,
  PreferencePicker,
  ReferenceGallery,
  StyleDna,
} from '@/components/reference-intelligence';
import { ErrorState, SkeletonRows } from '@/components/states';
import {
  ApiError,
  api,
  type Campaign,
  type CampaignReference,
  type CreativeContextView,
  type PreferencesView,
  type StyleOption,
} from '@/lib/api';
import { useWorkspace } from '@/lib/use-workspace';

export default function InspirationPage({
  params,
}: {
  params: Promise<{ campaignId: string }>;
}) {
  const { campaignId } = use(params);
  const workspace = useWorkspace();
  const { organizationId } = workspace;

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [references, setReferences] = useState<CampaignReference[]>([]);
  const [options, setOptions] = useState<StyleOption[]>([]);
  const [preferences, setPreferences] = useState<PreferencesView | null>(null);
  const [context, setContext] = useState<CreativeContextView | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!organizationId) return;
      const [detail, refs, styleOptions, prefs, ctx] = await Promise.all([
        api.getCampaign(campaignId, organizationId, signal),
        api.listReferences(campaignId, organizationId, signal),
        api.listStyleOptions(campaignId, organizationId, signal),
        api.getPreferences(campaignId, organizationId, signal),
        api.getCreativeContext(campaignId, organizationId, signal),
      ]);
      if (signal?.aborted) return;
      setCampaign(detail);
      setReferences(refs.items);
      setOptions(styleOptions.items);
      setPreferences(prefs);
      setContext(ctx);
      setSelectedId((current) => current ?? refs.items[0]?.id ?? null);
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

  const selected = references.find((r) => r.id === selectedId) ?? null;

  return (
    <AppShell
      me={workspace.me}
      activeOrganizationId={organizationId}
      onOrganizationChange={workspace.setOrganizationId}
    >
      <div className="flex flex-wrap justify-between gap-4">
        <Link href={`/app/campaigns/${campaignId}`} className="text-sm text-muted hover:underline">
          ← Discovery
        </Link>
        <Link
          href={`/app/campaigns/${campaignId}/creative`}
          className="text-sm text-muted hover:underline"
        >
          Creative directions →
        </Link>
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
      ) : !campaign ? (
        <div className="mt-6">
          <SkeletonRows rows={4} />
        </div>
      ) : (
        <div className="mt-4">
          <h1 className="text-2xl font-semibold tracking-tight">{campaign.title}</h1>
          <p className="mt-1 text-sm text-muted">
            Inspiration and visual direction. We read the style, never copy the design.
          </p>

          {error ? (
            <div className="mt-4">
              <ErrorState message={error.message} requestId={error.requestId} />
            </div>
          ) : null}

          <div className="mt-6 grid gap-6 lg:grid-cols-[1.3fr_1fr]">
            <div className="space-y-6">
              <ReferenceGallery
                references={references}
                selectedId={selectedId}
                busy={busy}
                onSelect={setSelectedId}
                onUpload={(file, note) =>
                  void run(() =>
                    api.uploadReference(campaignId, organizationId, file, note || undefined),
                  )
                }
              />
              {selected ? (
                <StyleDna
                  reference={selected}
                  busy={busy}
                  onAccept={() =>
                    void run(() => api.acceptReference(campaignId, selected.id, organizationId))
                  }
                  onReanalyze={() =>
                    void run(() =>
                      api.reanalyzeReference(campaignId, selected.id, organizationId),
                    )
                  }
                />
              ) : null}
            </div>

            <div className="space-y-6">
              <PreferencePicker
                options={options}
                preferences={preferences}
                busy={busy}
                onChange={(selectedStyles) =>
                  void run(() =>
                    api.setPreferences(campaignId, organizationId, selectedStyles),
                  )
                }
              />
              {context ? <CreativeContextPanel view={context} /> : <SkeletonRows rows={3} />}
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
