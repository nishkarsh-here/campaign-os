'use client';

/**
 * Final composition.
 *
 * The last step: take the selected plate, lay the brand-critical layer over it
 * deterministically, adjust what is safe to adjust, and export the channel
 * sizes the campaign asked for.
 *
 * The screen is arranged around one fact — the layout is the source of truth
 * and the image is its output. So the render sits beside the layout rather than
 * being the thing you manipulate, and "Render" is an explicit action: what you
 * see is always a file that exists, never an optimistic preview of one.
 */

import { use, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  ChannelVariants,
  ExportHistory,
  LayoutEditor,
  LayoutHealth,
  RenderedAsset,
} from '@/components/composition';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/states';
import {
  ApiError,
  CHANNEL_LABELS,
  api,
  type Campaign,
  type Channel,
  type CompositionView,
  type ElementEdit,
} from '@/lib/api';
import { useCampaignWorkspace } from '@/lib/campaign-context';

const DEFAULT_CHANNEL: Channel = 'instagram_post';

export default function ComposePage({
  params,
}: {
  params: Promise<{ campaignId: string }>;
}) {
  const { campaignId } = use(params);
  const { organizationId } = useCampaignWorkspace();

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [view, setView] = useState<CompositionView | null>(null);
  const [channel, setChannel] = useState<Channel>(DEFAULT_CHANNEL);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!organizationId) return;
      const [detail, composition] = await Promise.all([
        api.getCampaign(campaignId, organizationId, signal),
        api.getComposition(campaignId, organizationId, channel, signal),
      ]);
      if (signal?.aborted) return;
      setCampaign(detail);
      setView(composition);
    },
    [campaignId, channel, organizationId],
  );

  useEffect(() => {
    if (!organizationId) return undefined;
    const controller = new AbortController();
    setError(null);
    load(controller.signal).catch((err: unknown) => {
      if (controller.signal.aborted) return;
      setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
    });
    return () => controller.abort();
  }, [load, organizationId]);

  /**
   * Run one action, then reload.
   *
   * A refused edit keeps the error on screen and leaves the stored layout
   * alone — which is exactly what the server did, so the two agree.
   */
  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
      await load().catch(() => undefined);
    } finally {
      setBusy(false);
    }
  }

  const latest =
    view?.final_assets.find((asset) => asset.channel === channel) ?? null;
  const blocked = view?.report ? view.report.verdict !== 'PASS' : false;

  return (
    <>
      {error && !view ? (
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
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-h2">Compose & export</h2>
              <p className="mt-1 text-sm text-muted">
                Final branded asset — {CHANNEL_LABELS[channel]}.
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              {view.layout ? (
                <>
                  <button
                    type="button"
                    disabled={busy || blocked}
                    title={blocked ? 'Fix the layout problems first.' : undefined}
                    onClick={() =>
                      void run(() =>
                        api.renderComposition(campaignId, organizationId, channel, 'PNG'),
                      )
                    }
                    className="rounded-md border border-line bg-line/30 px-3 py-1.5 text-sm hover:bg-line/50 disabled:opacity-50"
                  >
                    {busy ? 'Working…' : latest ? 'Re-render PNG' : 'Render PNG'}
                  </button>
                  <button
                    type="button"
                    disabled={busy || blocked}
                    onClick={() =>
                      void run(() =>
                        api.renderComposition(campaignId, organizationId, channel, 'JPEG'),
                      )
                    }
                    className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40 disabled:opacity-50"
                  >
                    JPEG
                  </button>
                </>
              ) : view.can_compose ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void run(() => api.compose(campaignId, organizationId, channel))}
                  className="rounded-md border border-line bg-line/30 px-3 py-1.5 text-sm hover:bg-line/50 disabled:opacity-50"
                >
                  {busy ? 'Composing…' : 'Compose final asset'}
                </button>
              ) : null}
            </div>
          </div>

          {error ? (
            <ErrorState
              /* A refused edit is not a malfunction. Calling it "something
                 went wrong" would read as a bug in the tool rather than as
                 the rule it actually is. */
              title={
                error.code === 'VALIDATION_FAILED' || error.code === 'CONFLICT'
                  ? 'That change was not applied'
                  : undefined
              }
              message={error.message}
              code={error.code}
              requestId={error.requestId}
            />
          ) : null}

          {!view.layout && !view.can_compose ? (
            <EmptyState
              title="Nothing to compose yet"
              description={
                view.blocked_reason ??
                'Generate and select a creative first — composition needs a plate to build on.'
              }
              action={
                <Link
                  href={`/app/campaigns/${campaignId}/generate`}
                  className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40"
                >
                  Go to generation
                </Link>
              }
            />
          ) : (
            <>
              <LayoutHealth report={view.report} />
              <RenderedAsset asset={latest} channel={channel} />
              <LayoutEditor
                view={view}
                busy={busy}
                onEdit={(elementId, edit: ElementEdit) =>
                  void run(() =>
                    api.editComposition(campaignId, organizationId, channel, {
                      elements: { [elementId]: edit },
                    }),
                  )
                }
              />
              <ChannelVariants
                view={view}
                busy={busy}
                onSelect={setChannel}
                onAdd={(target) =>
                  void run(async () => {
                    await api.addCompositionVariant(
                      campaignId,
                      organizationId,
                      target,
                      channel,
                    );
                    setChannel(target);
                  })
                }
              />
              <ExportHistory view={view} />
            </>
          )}
        </div>
      )}
    </>
  );
}
