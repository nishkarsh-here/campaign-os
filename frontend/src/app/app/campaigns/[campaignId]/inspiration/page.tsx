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
import { ReferenceCard } from '@/components/reference-moodboard';
import { useCampaignWorkspace } from '@/lib/campaign-context';
import { capabilitiesFor } from '@/lib/capabilities';

export default function InspirationPage({
  params,
}: {
  params: Promise<{ campaignId: string }>;
}) {
  const { campaignId } = use(params);
  const { organizationId, me } = useCampaignWorkspace();
  const membership = me?.organizations.find((m) => m.organization.id === organizationId);
  const canEdit = capabilitiesFor(membership?.role ?? (me ? 'viewer' : null)).can(
    'edit_campaign',
  );

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

  const selected = references.find((r) => r.id === selectedId) ?? null;

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
      ) : !campaign ? (
        <div className="mt-6">
          <SkeletonRows rows={4} />
        </div>
      ) : (
        <div className="mt-4">
          <h2 className="text-h2">Inspiration</h2>
          <p className="mt-1 max-w-content text-body text-muted">
            Show the creative what good looks like. Campaign OS reads the style — the light,
            the framing, the density — and never copies the design.
          </p>

          {error ? (
            <div className="mt-4">
              <ErrorState message={error.message} requestId={error.requestId} />
            </div>
          ) : null}

          {/* Upload stays compact at the top; the board is the screen. */}
          <div className="mt-6">
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
          </div>

          {/* The moodboard. Each card is the reference beside what was read
              from it, and what will deliberately not be reused. */}
          {references.length > 0 ? (
            <ul className="mt-6 space-y-4">
              {references.map((reference, i) => (
                <ReferenceCard
                  key={reference.id}
                  reference={reference}
                  index={i}
                  canEdit={canEdit}
                  busy={busy}
                  onAccept={() =>
                    void run(() =>
                      api.acceptReference(campaignId, reference.id, organizationId),
                    )
                  }
                />
              ))}
            </ul>
          ) : null}

          <div className="mt-section grid gap-6 lg:grid-cols-2 lg:items-start">
            <PreferencePicker
              options={options}
              preferences={preferences}
              busy={busy}
              onChange={(selectedStyles) =>
                void run(() => api.setPreferences(campaignId, organizationId, selectedStyles))
              }
            />
            {context ? <CreativeContextPanel view={context} /> : <SkeletonRows rows={3} />}
          </div>
        </div>
      )}
    </>
  );
}
