'use client';

/**
 * Final composition: the layout, the constrained editor, and the exports.
 *
 * Two ideas shape this screen.
 *
 * **The layout is what you edit; the image is what you get.** Every control
 * changes a field on the `LayoutSpec` and the picture is re-rendered from it.
 * That is why an edit can be refused with a reason, why a channel variant
 * costs nothing, and why the version list is meaningful.
 *
 * **This is not a canvas app.** There is no drawing, no new shapes, no layers
 * panel, no free typography. The editor moves, resizes, restyles, rewrites and
 * hides what the composition already has — and the call to action, the legal
 * line and the logo are protected, because they carry approved facts. A refusal
 * arrives as a sentence, never as a silently ignored control.
 */

import { useEffect, useState } from 'react';
import {
  CHANNEL_LABELS,
  type Channel,
  type CompositionView,
  type ElementEdit,
  type FinalAssetView,
  type LayoutElementView,
  type LayoutReportView,
  mediaUrl,
} from '@/lib/api';

const ROLE_LABELS: Record<string, string> = {
  eyebrow: 'Eyebrow',
  headline: 'Headline',
  subhead: 'Subhead',
  cta: 'Call to action',
  logo: 'Logo',
  legal: 'Legal line',
};

/** Roles whose words are approved campaign facts. */
const PROTECTED_ROLES = new Set(['cta', 'legal']);

function elementLabel(element: LayoutElementView): string {
  if (element.role) return ROLE_LABELS[element.role] ?? element.role;
  if (element.type === 'logo') return 'Logo';
  if (element.type === 'image') return 'Plate';
  return 'Backdrop';
}

function percent(value: number): number {
  return Math.round(value * 1000) / 10;
}

// ---------------------------------------------------------------- the report
export function LayoutHealth({ report }: { report: LayoutReportView | null }) {
  if (!report) return null;
  const blocking = report.issues.filter((issue) => issue.severity === 'blocking');
  const warnings = report.issues.filter((issue) => issue.severity === 'warning');

  if (report.verdict === 'PASS' && warnings.length === 0) {
    return (
      <p className="text-xs text-emerald-400">
        ✓ Layout checks pass — every element is inside the canvas and clear of the safe area.
      </p>
    );
  }

  return (
    <div
      className={`rounded-md border p-3 ${
        blocking.length ? 'border-red-500/50 bg-red-500/5' : 'border-amber-500/50 bg-amber-500/5'
      }`}
    >
      <p className="text-sm font-medium">
        {blocking.length
          ? 'This layout cannot be rendered yet'
          : 'This layout renders, with things worth checking'}
      </p>
      <ul className="mt-2 space-y-1.5">
        {[...blocking, ...warnings].map((issue, index) => (
          <li key={`${issue.element_id ?? 'canvas'}-${index}`} className="text-xs">
            <span className={issue.severity === 'blocking' ? 'text-red-400' : 'text-amber-400'}>
              {issue.severity === 'blocking' ? '✕' : '⚠'}
            </span>{' '}
            <span>{issue.detail}</span>
            {issue.suggested_fix ? (
              <span className="text-muted"> — {issue.suggested_fix}</span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ----------------------------------------------------------------- the image
export function RenderedAsset({
  asset,
  channel,
}: {
  asset: FinalAssetView | null;
  channel: Channel;
}) {
  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium">Final branded asset</h2>
        <span className="text-xs text-muted">
          {asset
            ? `${CHANNEL_LABELS[channel]} · ${asset.width}×${asset.height} · v${asset.version}`
            : CHANNEL_LABELS[channel]}
        </span>
      </div>
      <p className="mt-1 text-xs text-muted">
        Composed by deterministic software, not by the image model. The logo, the headline, the
        call to action and the colours come from approved brand and campaign data.
      </p>

      {asset ? (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={mediaUrl(asset.url)}
            alt={`${CHANNEL_LABELS[channel]} final asset, version ${asset.version}`}
            className="mt-4 w-full rounded-md border border-line bg-black/20"
          />
          <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-muted sm:grid-cols-3">
            <div>
              <dt className="inline">Layout version </dt>
              <dd className="inline text-fg">v{asset.layout_version}</dd>
            </div>
            <div>
              <dt className="inline">Specification </dt>
              <dd className="inline text-fg">v{asset.specification_version}</dd>
            </div>
            <div>
              <dt className="inline">Renderer </dt>
              <dd className="inline text-fg">{asset.renderer_version}</dd>
            </div>
          </dl>
        </>
      ) : (
        <p className="mt-4 rounded-md border border-dashed border-line p-6 text-center text-xs text-muted">
          Nothing rendered yet for this channel.
        </p>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- the editor
function ElementControls({
  element,
  busy,
  onApply,
}: {
  element: LayoutElementView;
  busy: boolean;
  onApply: (edit: ElementEdit) => void;
}) {
  const [content, setContent] = useState(element.content ?? '');
  const protectedContent = PROTECTED_ROLES.has(element.role ?? '');
  const isText = element.type === 'text';
  const isLogo = element.type === 'logo';

  // The server is the source of truth: after a refused edit the draft must go
  // back to what is actually stored, not stay on the rejected text.
  useEffect(() => {
    setContent(element.content ?? '');
  }, [element.content]);

  return (
    <details className="rounded-md border border-line">
      <summary className="cursor-pointer px-3 py-2 text-sm">
        <span className="font-medium">{elementLabel(element)}</span>
        {element.content ? (
          <span className="ml-2 text-xs text-muted">{element.content.slice(0, 48)}</span>
        ) : null}
        {!element.visible ? <span className="ml-2 text-xs text-muted">(hidden)</span> : null}
      </summary>

      <div className="space-y-3 border-t border-line px-3 py-3">
        {isText ? (
          <label className="block">
            <span className="text-xs text-muted">Text</span>
            <textarea
              value={content}
              disabled={busy || protectedContent}
              onChange={(event) => setContent(event.target.value)}
              rows={2}
              className="mt-1 w-full rounded-md border border-line bg-transparent px-2 py-1.5 text-sm disabled:opacity-60"
            />
            {protectedContent ? (
              <span className="text-xs text-muted">
                {element.role === 'cta'
                  ? 'The call to action is an approved campaign fact. Change it through a revision.'
                  : 'The legal line comes from the Brand Brain.'}
              </span>
            ) : null}
          </label>
        ) : null}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <NumberField
            label="Left %"
            value={percent(element.box.x)}
            disabled={busy}
            onCommit={(value) => onApply({ x: value / 100 })}
          />
          <NumberField
            label="Top %"
            value={percent(element.box.y)}
            disabled={busy}
            onCommit={(value) => onApply({ y: value / 100 })}
          />
          <NumberField
            label="Width %"
            value={percent(element.box.width)}
            disabled={busy}
            onCommit={(value) => onApply({ width: value / 100 })}
          />
          {isText && element.text_style ? (
            <NumberField
              label="Text size %"
              value={percent(element.text_style.size)}
              disabled={busy}
              step={0.5}
              onCommit={(value) => onApply({ size: value / 100 })}
            />
          ) : null}
        </div>

        {isText && element.text_style ? (
          <div className="flex flex-wrap items-center gap-2">
            {(['left', 'center', 'right'] as const).map((align) => (
              <button
                key={align}
                type="button"
                disabled={busy}
                onClick={() => onApply({ align })}
                className={`rounded-md border px-2 py-1 text-xs disabled:opacity-50 ${
                  element.text_style?.align === align
                    ? 'border-fg/40 bg-line/40'
                    : 'border-line hover:bg-line/30'
                }`}
              >
                {align}
              </button>
            ))}
            <label className="ml-2 flex items-center gap-1.5 text-xs text-muted">
              <input
                type="color"
                value={element.text_style.color}
                disabled={busy}
                onChange={(event) => onApply({ color: event.target.value.toUpperCase() })}
                className="h-6 w-8 cursor-pointer rounded border border-line bg-transparent"
              />
              Colour
            </label>
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          {isText ? (
            <button
              type="button"
              disabled={busy || protectedContent || content === (element.content ?? '')}
              onClick={() => onApply({ content })}
              className="rounded-md border border-line px-2.5 py-1 text-xs hover:bg-line/40 disabled:opacity-50"
            >
              Apply text
            </button>
          ) : null}
          <button
            type="button"
            disabled={busy || isLogo}
            title={isLogo ? 'A branded asset always carries the mark.' : undefined}
            onClick={() => onApply({ visible: !element.visible })}
            className="rounded-md border border-line px-2.5 py-1 text-xs hover:bg-line/40 disabled:opacity-50"
          >
            {element.visible ? 'Hide' : 'Show'}
          </button>
          {isLogo ? (
            <span className="text-xs text-muted">The logo cannot be hidden.</span>
          ) : null}
        </div>
      </div>
    </details>
  );
}

function NumberField({
  label,
  value,
  disabled,
  step = 1,
  onCommit,
}: {
  label: string;
  value: number;
  disabled: boolean;
  step?: number;
  onCommit: (value: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => {
    setDraft(String(value));
  }, [value]);

  return (
    <label className="block">
      <span className="text-xs text-muted">{label}</span>
      <input
        type="number"
        value={draft}
        step={step}
        disabled={disabled}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => {
          const parsed = Number(draft);
          if (Number.isFinite(parsed) && parsed !== value) onCommit(parsed);
          else setDraft(String(value));
        }}
        className="mt-1 w-full rounded-md border border-line bg-transparent px-2 py-1 text-sm disabled:opacity-60"
      />
    </label>
  );
}

export function LayoutEditor({
  view,
  busy,
  onEdit,
}: {
  view: CompositionView;
  busy: boolean;
  onEdit: (elementId: string, edit: ElementEdit) => void;
}) {
  if (!view.layout) return null;
  // Reading order, so the panel matches the poster rather than the z-buffer.
  const elements = [...view.layout.elements].sort((a, b) => a.box.y - b.box.y);

  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium">Layout · v{view.layout.version}</h2>
        <span className="text-xs text-muted">
          {view.layout.width}×{view.layout.height}
        </span>
      </div>
      <p className="mt-1 text-xs text-muted">
        Every change writes a new layout version and leaves the old one exactly as it was. Nothing
        here edits the rendered image — re-render to see a change.
      </p>

      <div className="mt-4 space-y-2">
        {elements.map((element) => (
          <ElementControls
            key={element.id}
            element={element}
            busy={busy}
            onApply={(edit) => onEdit(element.id, edit)}
          />
        ))}
      </div>

      <p className="mt-4 text-xs text-muted">
        Safe area: {percent(view.layout.safe_area.top)}% top,{' '}
        {percent(view.layout.safe_area.bottom)}% bottom, {percent(view.layout.safe_area.left)}%
        sides. Nothing important is placed inside it.
      </p>
    </section>
  );
}

// --------------------------------------------------------------- the variants
export function ChannelVariants({
  view,
  busy,
  onSelect,
  onAdd,
}: {
  view: CompositionView;
  busy: boolean;
  onSelect: (channel: Channel) => void;
  onAdd: (channel: Channel) => void;
}) {
  return (
    <section className="rounded-lg border border-line p-5">
      <h2 className="text-sm font-medium">Channels</h2>
      <p className="mt-1 text-xs text-muted">
        A variant is a re-layout, not a regeneration: the same plate, the same approved words, the
        same logo, laid out for a different frame. No model is called.
      </p>

      <div className="mt-3 flex flex-wrap gap-2">
        {view.composed_channels.map((channel) => (
          <button
            key={channel}
            type="button"
            disabled={busy}
            onClick={() => onSelect(channel)}
            className={`rounded-md border px-2.5 py-1 text-xs disabled:opacity-50 ${
              channel === view.channel
                ? 'border-fg/40 bg-line/40'
                : 'border-line hover:bg-line/30'
            }`}
          >
            {CHANNEL_LABELS[channel]}
          </button>
        ))}
      </div>

      {view.available_channels.length ? (
        <div className="mt-4">
          <p className="text-xs text-muted">Add another channel</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {view.available_channels.map((channel) => (
              <button
                key={channel}
                type="button"
                disabled={busy}
                onClick={() => onAdd(channel)}
                className="rounded-md border border-dashed border-line px-2.5 py-1 text-xs hover:bg-line/30 disabled:opacity-50"
              >
                + {CHANNEL_LABELS[channel]}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------- the history
export function ExportHistory({ view }: { view: CompositionView }) {
  if (!view.final_assets.length) return null;

  return (
    <section className="rounded-lg border border-line p-5">
      <h2 className="text-sm font-medium">Exports</h2>
      <p className="mt-1 text-xs text-muted">
        Every render is kept. A new version never replaces the file someone already has.
      </p>

      <ul className="mt-3 divide-y divide-line">
        {view.final_assets.map((asset) => (
          <li key={asset.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2 text-xs">
            <span className="font-medium">{CHANNEL_LABELS[asset.channel]}</span>
            <span className="text-muted">v{asset.version}</span>
            <span className="text-muted">
              {asset.width}×{asset.height}
            </span>
            <span className="text-muted">{asset.mime_type.replace('image/', '').toUpperCase()}</span>
            <span className="text-muted">layout v{asset.layout_version}</span>
            <span className="text-muted">spec v{asset.specification_version}</span>
            <span className="text-muted">{new Date(asset.created_at).toLocaleString()}</span>
            <a
              href={`${mediaUrl(asset.url)}?download=true`}
              className="ml-auto rounded-md border border-line px-2 py-0.5 hover:bg-line/40"
            >
              Download
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
