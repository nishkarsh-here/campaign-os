'use client';

/**
 * COMPOSE — the production workspace.
 *
 * The last step: take the selected plate, lay the brand-critical layer over it
 * deterministically, adjust what is safe to adjust, and render the channel sizes
 * the campaign asked for.
 *
 * ## The one fact the screen is arranged around
 *
 * **The layout is the source of truth and the image is its output** (ADR-014).
 * So the canvas is labelled `Preview`, every control changes a field on the
 * `LayoutSpec`, and `Render` is an explicit act that produces a file which then
 * exists. Nothing here edits an image, and the browser never claims to be the
 * renderer.
 *
 * ## Why the plate is resolved rather than read
 *
 * `layout.plate_storage_key` is a storage key, and no route takes a key from a
 * request (M10) — correctly, since that is the arbitrary-object-access hole the
 * scoped repositories exist to close. The plate is therefore found by matching
 * `layout.source_asset_id` against the signed assets the generation, evaluation
 * and guardian surfaces return, exactly as the refine screen does. The logo is
 * matched by brand-asset `kind`, which is a documented gap: the composition API
 * projects no signed URL for an element's own image.
 *
 * ## Three zones, and what happens below 1280px
 *
 * Layers left, canvas centre, inspector and checks right. Below `xl` the side
 * panels become disclosures the canvas sits above — stacking three columns
 * would turn the work into a strip above a wall of controls, and the work is
 * the thing being judged.
 */

import { use, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { ComposeCanvas } from '@/components/compose-canvas';
import {
  ChannelPicker,
  CollapsiblePanel,
  Inspector,
  LayerList,
  LayoutCheckPanel,
} from '@/components/compose-workspace';
import { FinalAssetPanel, RenderHistory, RenderPanel } from '@/components/final-asset';
import {
  Card,
  EmptyState,
  ErrorState,
  SkeletonRows,
  StatusBadge,
  buttonStyles,
} from '@/components/ui';
import {
  ApiError,
  CHANNEL_LABELS,
  api,
  mediaUrl,
  type BoxView,
  type Campaign,
  type Channel,
  type CompositionView,
  type ElementEdit,
  type FinalAssetView,
  type GeneratedAssetView,
} from '@/lib/api';
import { useCampaignWorkspace } from '@/lib/campaign-context';
import { capabilitiesFor } from '@/lib/capabilities';
import { channelViews, elementName, layoutCheck } from '@/lib/compose';
import { verdictMeaning } from '@/lib/review';

const DEFAULT_CHANNEL: Channel = 'instagram_post';

export default function ComposePage({
  params,
}: {
  params: Promise<{ campaignId: string }>;
}) {
  const { campaignId } = use(params);
  const { organizationId, me, overview, specification } = useCampaignWorkspace();
  const membership = me?.organizations.find((m) => m.organization.id === organizationId);
  const capabilities = capabilitiesFor(membership?.role ?? (me ? 'viewer' : null));
  const canEdit = capabilities.can('edit_campaign');

  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [view, setView] = useState<CompositionView | null>(null);
  const [channel, setChannel] = useState<Channel>(DEFAULT_CHANNEL);
  const [plates, setPlates] = useState<GeneratedAssetView[]>([]);
  const [logoUrl, setLogoUrl] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [shownAssetId, setShownAssetId] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [rendering, setRendering] = useState(false);
  /**
   * Counts resolved edit attempts, accepted or refused.
   *
   * The inspector's uncontrolled fields key off it, so a value the server
   * refused cannot stay on screen looking like the layout's own.
   */
  const [attempt, setAttempt] = useState(0);
  const justRendered = useRef<string | null>(null);

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
   * The plates, so the canvas can draw the one this layout composes.
   *
   * Three surfaces are asked because each returns a different slice: generation
   * has the latest batch, evaluation keeps earlier versions, and the guardian
   * holds whatever it checked. Best-effort — a campaign whose plate cannot be
   * resolved still composes, on the flat brand ground the renderer would use.
   */
  useEffect(() => {
    if (!organizationId) return undefined;
    const controller = new AbortController();
    const collect = (assets: GeneratedAssetView[]) => {
      if (controller.signal.aborted) return;
      setPlates((current) => {
        const map = new Map(current.map((a) => [a.id, a]));
        for (const asset of assets) map.set(asset.id, asset);
        return [...map.values()];
      });
    };
    api
      .getGeneration(campaignId, organizationId, controller.signal)
      .then((v) => collect(v.assets))
      .catch(() => undefined);
    api
      .getEvaluation(campaignId, organizationId, controller.signal)
      .then((v) => collect(v.ranked.map((r) => r.asset).filter(Boolean) as GeneratedAssetView[]))
      .catch(() => undefined);
    api
      .getGuardian(campaignId, organizationId, controller.signal)
      .then((v) => collect(v.results.map((r) => r.asset).filter(Boolean) as GeneratedAssetView[]))
      .catch(() => undefined);
    return () => controller.abort();
  }, [campaignId, organizationId]);

  /**
   * The brand's logo, by `kind`.
   *
   * The layout's logo element carries a storage key, and brand assets project a
   * signed `url` but no key — so the two cannot be matched exactly. This mirrors
   * `_logo_row`: the first asset of kind `logo` or `logo_mono`. Recorded as a
   * backend gap; the renderer uses the key, so the file is always right even
   * when this preview cannot resolve it.
   */
  useEffect(() => {
    const brandId = overview?.brand_id;
    if (!organizationId || !brandId) return undefined;
    const controller = new AbortController();
    api
      .getBrain(brandId, organizationId, controller.signal)
      .then((brain) => {
        if (controller.signal.aborted) return;
        const logo = brain.assets.find((a) => a.kind === 'logo' || a.kind === 'logo_mono');
        setLogoUrl(logo ? mediaUrl(logo.url) : null);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [organizationId, overview?.brand_id]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setEditError(null);
    try {
      await action();
      await load();
    } catch (err) {
      // The server's own sentence. An edit is refused whole rather than
      // trimmed, so this is the complete reason the layout did not change.
      setEditError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
      setAttempt((n) => n + 1);
    }
  }

  const editElement = useCallback(
    (elementId: string, edit: ElementEdit) => {
      void run(() =>
        api.editComposition(campaignId, organizationId, channel, {
          elements: { [elementId]: edit },
        }),
      );
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [campaignId, channel, organizationId],
  );

  const commitBox = useCallback(
    (elementId: string, box: BoxView) => {
      editElement(elementId, {
        x: box.x,
        y: box.y,
        width: box.width,
        height: box.height,
      });
    },
    [editElement],
  );

  async function renderFinal(format: 'PNG' | 'JPEG') {
    setRendering(true);
    setRenderError(null);
    try {
      const asset = await api.renderComposition(campaignId, organizationId, channel, format);
      justRendered.current = asset.id;
      setShownAssetId(asset.id);
      await load();
    } catch (err) {
      setRenderError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setRendering(false);
    }
  }

  // ------------------------------------------------------------ derived state
  const layout = view?.layout ?? null;
  const check = layoutCheck(view?.report ?? null);
  const channels = useMemo(() => channelViews(view), [view]);
  const selected = layout?.elements.find((e) => e.id === selectedId) ?? null;

  const plateUrl = useMemo(() => {
    if (!layout?.source_asset_id) return null;
    const plate = plates.find((a) => a.id === layout.source_asset_id);
    return plate ? mediaUrl(plate.url) : null;
  }, [layout?.source_asset_id, plates]);

  const flagged = useMemo(
    () =>
      new Set(
        (view?.report?.issues ?? [])
          .map((issue) => issue.element_id)
          .filter((id): id is string => Boolean(id)),
      ),
    [view?.report],
  );

  const channelAssets = useMemo(
    () => (view?.final_assets ?? []).filter((a) => a.channel === channel),
    [view?.final_assets, channel],
  );
  const shown: FinalAssetView | null =
    channelAssets.find((a) => a.id === shownAssetId) ?? channelAssets[0] ?? null;

  const guardian = overview?.guardian_verdict ? verdictMeaning(overview.guardian_verdict) : null;

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
          <div>
            <h2 className="text-h2">Compose &amp; export</h2>
            <p className="mt-1 max-w-content text-body text-muted">
              The approved words, the brand mark and the chosen visual, laid out for each frame.
              Campaign OS renders the file itself — the same layout always produces the same
              image.
            </p>
          </div>

          {!view.can_compose && !layout ? (
            <EmptyState
              title="Nothing to compose yet"
              description={
                view.blocked_reason ??
                'Generate and select a creative before composing the final asset.'
              }
              action={
                <Link
                  href={`/app/campaigns/${campaignId}/generate`}
                  className={buttonStyles('primary', 'lg')}
                >
                  Go to generation
                </Link>
              }
            />
          ) : (
            <>
              {editError ? (
                <Card className="border-l-2 border-l-danger" role="alert">
                  <p className="text-label uppercase text-danger">The layout was not changed</p>
                  {/* The server's own words: an edit is refused whole, so this
                      is the entire reason nothing moved. */}
                  <p className="mt-1 text-small">{editError}</p>
                </Card>
              ) : null}

              <div className="grid gap-5 xl:grid-cols-[minmax(0,15rem)_minmax(0,1fr)_minmax(0,20rem)] xl:items-start">
                {/* ------------------------------------------------ layers */}
                <div className="space-y-4 xl:sticky xl:top-6">
                  <CollapsiblePanel title="Channel">
                    <ChannelPicker
                      channels={channels}
                      busy={busy}
                      canEdit={canEdit}
                      onSwitch={(next) => {
                        setChannel(next);
                        setSelectedId(null);
                        setShownAssetId(null);
                      }}
                      onCompose={(next) => {
                        setChannel(next);
                        setSelectedId(null);
                        void run(() => api.compose(campaignId, organizationId, next));
                      }}
                    />
                  </CollapsiblePanel>

                  {layout ? (
                    <CollapsiblePanel title="Layers">
                      <LayerList
                        layout={layout}
                        report={view.report}
                        selectedId={selectedId}
                        onSelect={setSelectedId}
                      />
                    </CollapsiblePanel>
                  ) : null}
                </div>

                {/* ------------------------------------------------ canvas */}
                <div className="space-y-3">
                  {layout ? (
                    <>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-label uppercase text-muted">
                          Preview · {CHANNEL_LABELS[layout.channel]} · {layout.width} ×{' '}
                          {layout.height}
                        </p>
                        <StatusBadge tone={check.tone}>{check.label}</StatusBadge>
                      </div>

                      <ComposeCanvas
                        layout={layout}
                        plateUrl={plateUrl}
                        logoUrl={logoUrl}
                        selectedId={selectedId}
                        onSelect={setSelectedId}
                        onCommit={commitBox}
                        canEdit={canEdit && !busy}
                        flagged={flagged}
                      />

                      <p className="text-caption text-muted">
                        A preview of the layout. The final asset is rendered by Campaign OS —
                        type, spacing and the logo are composed by the renderer, not by the
                        browser.
                        {canEdit
                          ? ' Drag to move, or select a layer and use the arrow keys.'
                          : ''}
                      </p>
                    </>
                  ) : (
                    <EmptyState
                      title={`No ${CHANNEL_LABELS[channel]} layout yet`}
                      description="Composing builds the default layout from the approved plan, the selected visual and the brand's own mark."
                      action={
                        canEdit ? (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() =>
                              void run(() => api.compose(campaignId, organizationId, channel))
                            }
                            className={buttonStyles('primary', 'lg')}
                          >
                            {busy ? 'Composing…' : `Compose the ${CHANNEL_LABELS[channel]}`}
                          </button>
                        ) : undefined
                      }
                    />
                  )}
                </div>

                {/* --------------------------------------------- inspector */}
                <div className="space-y-4 xl:sticky xl:top-6">
                  <CollapsiblePanel title="Layout check" defaultOpen>
                    <LayoutCheckPanel
                      check={check}
                      report={view.report}
                      layout={layout}
                      onSelect={setSelectedId}
                    />
                  </CollapsiblePanel>

                  {layout && selected ? (
                    <CollapsiblePanel title={`Selected — ${elementName(selected)}`} defaultOpen>
                      <Inspector
                        layout={layout}
                        element={selected}
                        report={view.report}
                        busy={busy}
                        capabilities={capabilities}
                        onEdit={editElement}
                        attempt={attempt}
                      />
                    </CollapsiblePanel>
                  ) : layout ? (
                    <Card>
                      <p className="text-caption text-muted">
                        Select a layer to see its position, size and what is protected about it.
                      </p>
                    </Card>
                  ) : null}
                </div>
              </div>

              {/* ------------------------------------------- render + export */}
              <div className="border-t border-line pt-6">
                <h2 className="text-h2">Final asset</h2>
                <p className="mt-1 max-w-content text-body text-muted">
                  Rendered by Campaign OS from the layout above, and traceable to every version it
                  came from.
                </p>
              </div>

              <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] lg:items-start">
                <div className="space-y-5">
                  {shown ? (
                    <FinalAssetPanel
                      asset={shown}
                      layout={layout}
                      campaign={overview?.title ?? campaign.title ?? null}
                      brand={overview?.brand_name ?? null}
                      market={specification?.region ?? null}
                      guardian={guardian}
                      latest={shown.id === channelAssets[0]?.id}
                    />
                  ) : (
                    <Card>
                      <p className="text-body text-muted">
                        Nothing has been rendered for {CHANNEL_LABELS[channel]} yet.
                      </p>
                    </Card>
                  )}

                  <RenderHistory
                    assets={channelAssets}
                    selectedId={shown?.id ?? null}
                    onSelect={setShownAssetId}
                  />
                </div>

                <RenderPanel
                  check={check}
                  rendering={rendering}
                  busy={busy}
                  capabilities={capabilities}
                  hasLayout={Boolean(layout)}
                  onRender={(format) => void renderFinal(format)}
                  error={renderError}
                />
              </div>
            </>
          )}
        </div>
      )}
    </>
  );
}
