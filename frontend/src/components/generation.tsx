'use client';

/**
 * The generation experience: what each provider will be asked, how each job is
 * going, and the plates that came back.
 *
 * Two things this screen is careful about. It never shows a card that spins
 * forever — every job has an explicit status, and a failed one carries a
 * readable reason and a retry. And it calls a generated image a *visual
 * plate*, because that is what it is: the logo, headline, CTA and exact colours
 * are applied later by the deterministic renderer, and a gallery that called
 * these finished creatives would be lying to the person looking at it.
 */

import { useState } from 'react';
import type { CanonicalPrompt, ModelPromptView } from '@/lib/api';
// One vocabulary for a provider across the whole product. This file used to
// capitalise the raw name, so the same provider was "Demo generator" in the
// studio and "Mock" in the prompt panel directly beneath it.
import { providerLabel } from '@/lib/generation';

function Swatches({ palette }: { palette: string[] }) {
  if (!palette.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {palette.map((hex) => (
        <span
          key={hex}
          title={hex}
          className="h-5 w-5 rounded border border-line"
          style={{ background: hex }}
        />
      ))}
    </div>
  );
}

/** What the plate will be asked for, in the structured form it is stored in. */
export function CanonicalPromptPanel({ prompt }: { prompt: CanonicalPrompt }) {
  const rows: [string, string][] = [
    ['Subject', prompt.subject],
    ['Setting', prompt.environment],
    ['Scene', prompt.visual_story],
    ['Composition', prompt.composition],
    ['Focal point', prompt.focal_point],
    ['Camera', prompt.camera ?? ''],
    ['Lighting', prompt.lighting],
    ['Colour', prompt.color_direction],
    ['Product', prompt.product_integration],
    ['People', prompt.people_guidance],
    ['Brand presence', prompt.brand_integration],
  ];

  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">Compiled prompt</h2>
        <span className="text-xs text-muted">
          v{prompt.version} · from specification v{prompt.specification_version} ·{' '}
          {prompt.aspect_ratio}
        </span>
      </div>
      <p className="mt-1 text-xs text-muted">
        The approved plan, rearranged into the controls an image model responds to. Structured,
        not a paragraph — so it can be read, compared and recompiled.
      </p>

      <dl className="mt-4 grid gap-3 sm:grid-cols-2">
        {rows
          .filter(([, value]) => value)
          .map(([label, value]) => (
            <div key={label}>
              <dt className="text-[10px] uppercase tracking-wide text-muted">{label}</dt>
              <dd className="mt-0.5 text-sm">{value}</dd>
            </div>
          ))}
      </dl>

      {prompt.palette.length ? (
        <div className="mt-4">
          <p className="text-[10px] uppercase tracking-wide text-muted">Palette</p>
          <div className="mt-1.5">
            <Swatches palette={prompt.palette} />
          </div>
        </div>
      ) : null}

      {/* The architectural boundary, stated where a user can see it. */}
      <div className="mt-4 rounded-md border border-line/70 p-3">
        <p className="text-[10px] uppercase tracking-wide text-muted">Type is not generated</p>
        <p className="mt-1 text-xs text-muted">{prompt.text_safe_area}</p>
      </div>

      {prompt.reference_characteristics.length ? (
        <div className="mt-4">
          <p className="text-[10px] uppercase tracking-wide text-muted">
            Qualities carried from your references
          </p>
          <ul className="mt-1 space-y-0.5 text-xs text-muted">
            {prompt.reference_characteristics.map((quality) => (
              <li key={quality}>· {quality}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

/** The per-provider wording. Collapsed by default — it is long and technical. */
export function ProviderPrompts({ prompts }: { prompts: ModelPromptView[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!prompts.length) return null;

  return (
    <section className="rounded-lg border border-line p-5">
      <h2 className="text-sm font-semibold">What each provider will be asked</h2>
      <p className="mt-1 text-xs text-muted">
        Same idea, different wording. Adapters change formatting, never meaning.
      </p>
      <div className="mt-4 space-y-2">
        {prompts.map((prompt) => (
          <div key={prompt.id} className="rounded-md border border-line/70">
            <button
              type="button"
              onClick={() => setOpen(open === prompt.id ? null : prompt.id)}
              className="flex w-full items-center justify-between gap-3 p-3 text-left hover:bg-line/20"
            >
              <span className="text-sm font-medium">{providerLabel(prompt.provider)}</span>
              <span className="text-xs text-muted">
                {prompt.model} · {prompt.aspect_ratio} · {open === prompt.id ? 'hide' : 'show'}
              </span>
            </button>
            {open === prompt.id ? (
              <div className="border-t border-line/70 p-3">
                <pre className="overflow-x-auto whitespace-pre-wrap text-xs text-muted">
                  {prompt.text}
                </pre>
                {prompt.negative_text ? (
                  <div className="mt-3">
                    <p className="text-[10px] uppercase tracking-wide text-muted">
                      Must not appear
                    </p>
                    <p className="mt-0.5 text-xs text-muted">{prompt.negative_text}</p>
                  </div>
                ) : null}
                <p className="mt-3 font-mono text-[10px] text-muted">{prompt.trace}</p>
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}
