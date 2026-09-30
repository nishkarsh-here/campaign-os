'use client';

/**
 * FINAL ASSET — what the deterministic renderer produced, and how to take it.
 *
 * ## Preview is not the deliverable
 *
 * The canvas is a browser's reading of a `LayoutSpec`. This is the file the
 * Pillow renderer actually wrote, fetched back through a signed URL. The
 * distinction is drawn out loud because it is the product's whole claim:
 * typography and the logo are composed by deterministic code, not by an image
 * model (ADR-006), and "what I saw" and "what shipped" must be the same thing
 * for a reason a person can point at.
 *
 * ## Provenance travels with the file
 *
 * Every row beside the asset is stamped on it at render time — the channel, the
 * layout version, the creative plan version, the renderer version. None is read
 * from the campaign's current state, so an asset that has gone to a client keeps
 * saying what it said even after the layout moves on. When the layout *has*
 * moved on, the panel says so rather than letting the file look current.
 */

import { useState } from 'react';
import {
  Button,
  Card,
  Plate,
  SectionHeader,
  StatusBadge,
  cx,
  type Tone,
} from '@/components/ui';
import { mediaUrl, type FinalAssetView, type LayoutSpecView } from '@/lib/api';
import type { Capabilities } from '@/lib/capabilities';
import { EXPORT_FORMATS, aspectLabel, finalAssetFacts, type LayoutCheck } from '@/lib/compose';

// ------------------------------------------------------------------ rendering

export interface RenderPanelProps {
  check: LayoutCheck;
  /** True while the server is composing the file. */
  rendering: boolean;
  busy: boolean;
  capabilities: Capabilities;
  hasLayout: boolean;
  onRender: (format: 'PNG' | 'JPEG') => void;
  /** The server's sentence when a render was refused. */
  error: string | null;
}

/**
 * The step that turns a layout into a file.
 *
 * Disabled while the layout check is blocking — not to be obstructive, but
 * because `render_final` would refuse and the reason is already on screen. The
 * button says which, so a person is never left guessing why it is grey.
 */
export function RenderPanel({
  check,
  rendering,
  busy,
  capabilities,
  hasLayout,
  onRender,
  error,
}: RenderPanelProps) {
  const [format, setFormat] = useState<'PNG' | 'JPEG'>('PNG');
  const canRender = capabilities.can('edit_campaign');

  if (!hasLayout) return null;

  return (
    <Card>
      <SectionHeader
        level={3}
        title="Final render"
        description="Campaign OS composes the deliverable itself — the same layout always produces the same file."
      />

      <div className="mt-4 flex flex-wrap items-center gap-2" role="group" aria-label="File format">
        {EXPORT_FORMATS.map((option) => (
          <Button
            key={option.format}
            variant={format === option.format ? 'primary' : 'secondary'}
            size="sm"
            aria-pressed={format === option.format}
            disabled={busy || rendering}
            onClick={() => setFormat(option.format)}
          >
            {option.label}
          </Button>
        ))}
        <span className="text-caption text-muted">
          {EXPORT_FORMATS.find((o) => o.format === format)?.detail}
        </span>
      </div>

      <div className="mt-5 border-t border-line pt-4">
        {!canRender ? (
          <p className="text-caption text-muted">
            Rendering the final asset needs edit rights on this campaign.
          </p>
        ) : check.blocked ? (
          <>
            <Button variant="primary" disabled>
              Fix the layout before rendering
            </Button>
            <p className="mt-2 text-caption text-muted">
              The layout check found {check.blocking} blocking{' '}
              {check.blocking === 1 ? 'issue' : 'issues'}. The renderer would refuse it for the
              same reason.
            </p>
          </>
        ) : (
          <>
            <Button variant="primary" disabled={busy || rendering} onClick={() => onRender(format)}>
              {rendering ? 'Creating final asset…' : `Render the ${format}`}
            </Button>
            <p className="mt-2 text-caption text-muted">
              This writes a new deliverable. Earlier renders stay exactly as they were.
            </p>
          </>
        )}

        {error ? (
          <p role="alert" className="mt-3 text-small text-danger">
            {error}
          </p>
        ) : null}
      </div>
    </Card>
  );
}

// -------------------------------------------------------------- the deliverable

export interface FinalAssetPanelProps {
  asset: FinalAssetView;
  layout: LayoutSpecView | null;
  /** Campaign context, so the file is placed rather than floating. */
  campaign: string | null;
  brand: string | null;
  market: string | null;
  /** The brand check's standing, where one exists. Never invented. */
  guardian: { label: string; tone: Tone } | null;
  /** True when this is the newest render for its channel. */
  latest: boolean;
}

/**
 * One rendered deliverable, presented as the thing the campaign was for.
 *
 * Editorial rather than a table row: the file is large, its provenance is a
 * ledger beside it, and the download is the obvious next move. What it does not
 * do is imply currency — a render made from an older layout says so.
 */
export function FinalAssetPanel({
  asset,
  layout,
  campaign,
  brand,
  market,
  guardian,
  latest,
}: FinalAssetPanelProps) {
  const facts = finalAssetFacts(asset, layout);

  return (
    <Card padding={false} className="final-asset-reveal overflow-hidden">
      <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
        <div className="bg-line/30 p-5 sm:p-6">
          <Plate
            src={mediaUrl(asset.url)}
            alt={`The final ${asset.channel.replace(/_/g, ' ')} asset for ${campaign ?? 'this campaign'}, ${asset.width} by ${asset.height} pixels`}
            ratio={aspectLabel(asset.width, asset.height)?.replace(':', ' / ') ?? null}
          />
        </div>

        <div className="min-w-0 border-t border-line p-5 sm:p-6 lg:border-l lg:border-t-0">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-label uppercase text-accent">Final campaign asset</p>
            {latest ? <StatusBadge tone="positive">Latest</StatusBadge> : null}
          </div>
          <h3 className="mt-1 text-h3">{campaign ?? 'This campaign'}</h3>

          <dl className="mt-5 space-y-3 border-t border-line pt-4">
            {brand ? <Row label="Brand" value={brand} /> : null}
            {market ? <Row label="Market" value={market} /> : null}
            {facts.rows.map((row) => (
              <Row key={row.label} label={row.label} value={row.value} />
            ))}
          </dl>

          {/*
            Outside the ledger, and scoped out loud.

            Every row above is stamped on this file at render time. The brand
            check is not: it is the campaign's *current* verdict, computed for
            the creative selected right now. Inside the same list it read as
            something this file carries — so selecting an older render, or
            revising and re-selecting a plate, showed the new creative's pass
            against a file made from the superseded one.
          */}
          {guardian ? (
            <div className="mt-4 border-t border-line pt-4">
              <p className="text-label uppercase text-muted">
                Brand check · the campaign’s selected creative
              </p>
              <div className="mt-1.5">
                <StatusBadge tone={guardian.tone}>{guardian.label}</StatusBadge>
              </div>
              <p className="mt-1.5 text-caption text-muted">
                A verdict on the creative, not on this file. A file is checked by
                the layout check before it is rendered.
              </p>
            </div>
          ) : null}

          {facts.supersededBy !== null ? (
            <p className="mt-4 border-t border-line pt-4 text-caption text-warning">
              The layout has changed since this was rendered — it is now v
              {facts.supersededBy}. Render again to produce a file from the current layout.
            </p>
          ) : null}

          <div className="mt-5 border-t border-line pt-4">
            {/* The server builds the attachment link: `url` carries a signature
                in its query string, so appending to it breaks the token. */}
            <a
              href={mediaUrl(asset.download_url)}
              className={cx(
                'inline-flex items-center rounded-md border border-line bg-line/30 px-4 py-2 text-small transition-colors duration-fast hover:bg-line/50',
              )}
            >
              Download the {asset.mime_type === 'image/png' ? 'PNG' : 'JPEG'}
            </a>
            <p className="mt-2 text-caption text-muted">
              A signed link that expires. Re-open this screen for a fresh one.
            </p>
          </div>
        </div>
      </div>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-label uppercase text-muted">{label}</dt>
      <dd className="mt-0.5 text-small">{value}</dd>
    </div>
  );
}

/**
 * Everything this campaign has rendered, newest first.
 *
 * Old versions stay: the history is what proves a re-render did not silently
 * replace a file a client already has.
 */
export function RenderHistory({
  assets,
  selectedId,
  onSelect,
}: {
  assets: FinalAssetView[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (assets.length <= 1) return null;
  return (
    <div>
      <p className="text-label uppercase text-muted">Everything rendered</p>
      <ul className="mt-3 flex flex-wrap gap-2">
        {assets.map((asset) => (
          <li key={asset.id}>
            <button
              type="button"
              aria-pressed={asset.id === selectedId}
              onClick={() => onSelect(asset.id)}
              className={cx(
                'rounded-md border px-3 py-1.5 text-caption transition-colors duration-fast',
                asset.id === selectedId
                  ? 'border-accent/60 bg-accent/5'
                  : 'border-line hover:border-accent/40',
              )}
            >
              {asset.channel.replace(/_/g, ' ')} · v{asset.version}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
