'use client';

/**
 * Reference intelligence: the inspiration gallery, the extracted Style DNA,
 * visual calibration, and the assembled Creative Context.
 *
 * The organising idea is that the system is showing its *reading* of a
 * reference, not proposing to copy it. Every analysis therefore displays what
 * it will deliberately not reuse, right next to what it will.
 */

import { useState } from 'react';
import { mediaUrl } from '@/lib/api';
import type {
  CampaignReference,
  CreativeContextView,
  PreferencesView,
  ReferenceAnalysis,
  StyleOption,
} from '@/lib/api';

const STATUS_LABEL: Record<string, string> = {
  PENDING: 'Queued',
  ANALYZING: 'Reading…',
  COMPLETED: 'Analysed',
  FAILED: 'Could not read',
};

function humanise(value: string | null | undefined): string {
  return value ? value.replace(/_/g, ' ') : '—';
}

function Meter({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="flex justify-between text-[10px] uppercase tracking-wide text-muted">
        <span>{label}</span>
        <span>{Math.round(value * 100)}%</span>
      </div>
      <div className="mt-1 h-1 rounded bg-line">
        <div className="h-1 rounded bg-ink/60" style={{ width: `${value * 100}%` }} />
      </div>
    </div>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border border-line px-2.5 py-1 text-xs capitalize">
      {children}
    </span>
  );
}

export function ReferenceGallery({
  references,
  selectedId,
  onSelect,
  onUpload,
  busy,
}: {
  references: CampaignReference[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onUpload: (file: File, note: string) => void;
  busy: boolean;
}) {
  const [note, setNote] = useState('');

  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold">Inspiration</h2>
          <p className="mt-1 text-xs text-muted">
            Upload work you like. We read its visual language — never its content.
          </p>
        </div>
        <label className="shrink-0 cursor-pointer rounded-md border border-line px-3 py-1.5 text-xs hover:bg-line/30">
          {busy ? 'Reading…' : 'Add reference'}
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onUpload(file, note.trim());
              setNote('');
              e.target.value = '';
            }}
          />
        </label>
      </div>

      <input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Optional: what do you like about it?"
        aria-label="What you like about the next reference"
        className="mt-3 w-full rounded-md border border-line bg-transparent px-3 py-2 text-xs"
      />

      {references.length === 0 ? (
        <p className="mt-5 rounded-md border border-dashed border-line p-6 text-center text-xs text-muted">
          No references yet. Add a poster, an ad, a page — anything with the feel you want.
        </p>
      ) : (
        <ul className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
          {references.map((reference) => {
            const active = reference.id === selectedId;
            return (
              <li key={reference.id}>
                <button
                  onClick={() => onSelect(reference.id)}
                  className={`group w-full overflow-hidden rounded-md border text-left transition ${
                    active ? 'border-ink' : 'border-line hover:border-muted'
                  }`}
                >
                  <div className="aspect-[4/3] bg-line/30">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={mediaUrl(reference.url)}
                      alt={reference.filename ?? 'Reference'}
                      className="h-full w-full object-cover"
                    />
                  </div>
                  <div className="px-2 py-1.5">
                    <p className="truncate text-[11px]">{reference.filename ?? 'Reference'}</p>
                    <p
                      className={`text-[10px] ${
                        reference.status === 'FAILED'
                          ? 'text-red-400'
                          : reference.status === 'COMPLETED'
                            ? 'text-emerald-400'
                            : 'text-muted'
                      }`}
                    >
                      {reference.accepted ? 'Accepted' : STATUS_LABEL[reference.status]}
                    </p>
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export function StyleDna({
  reference,
  onAccept,
  onReanalyze,
  busy,
}: {
  reference: CampaignReference;
  onAccept: () => void;
  onReanalyze: () => void;
  busy: boolean;
}) {
  const analysis: ReferenceAnalysis | null = reference.analysis;

  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold">Style DNA</h2>
          <p className="mt-1 text-xs text-muted">
            What we took from {reference.filename ?? 'this reference'}.
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            onClick={onReanalyze}
            disabled={busy}
            className="rounded-md border border-line px-3 py-1.5 text-xs hover:bg-line/30 disabled:opacity-40"
          >
            Re-read
          </button>
          {analysis && !reference.accepted ? (
            <button
              onClick={onAccept}
              disabled={busy}
              className="rounded-md bg-ink px-3 py-1.5 text-xs font-medium text-surface disabled:opacity-40"
            >
              Looks right
            </button>
          ) : null}
        </div>
      </div>

      {reference.status === 'FAILED' ? (
        <div role="alert" className="mt-4 rounded-md border border-red-500/40 bg-red-500/5 p-3">
          <p className="text-xs">{reference.error ?? 'This reference could not be read.'}</p>
        </div>
      ) : !analysis ? (
        <p className="mt-4 text-xs text-muted">
          <span className="mr-1 animate-pulse">●</span>
          Reading the visual language…
        </p>
      ) : (
        <div className="mt-5 space-y-5">
          {analysis.summary ? <p className="text-sm">{analysis.summary}</p> : null}

          <div className="flex flex-wrap gap-1.5">
            {analysis.style_families.map((style) => (
              <Chip key={style}>{humanise(style)}</Chip>
            ))}
            {analysis.mood.map((mood) => (
              <Chip key={mood}>{mood}</Chip>
            ))}
          </div>

          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-xs sm:grid-cols-3">
            {[
              ['Composition', analysis.composition],
              ['Lighting', analysis.lighting],
              ['Imagery', analysis.imagery_style.join(', ')],
              ['Density', analysis.visual_density],
              ['Balance', analysis.layout.image_text_balance],
              ['Placement', analysis.layout.subject_placement],
              ['Type scale', analysis.typography.scale],
              ['Type weight', analysis.typography.weight],
              ['Type class', analysis.typography.classification],
            ].map(([label, value]) => (
              <div key={label as string}>
                <dt className="text-[10px] uppercase tracking-wide text-muted">{label}</dt>
                <dd className="mt-0.5 capitalize">{humanise(value as string | null)}</dd>
              </div>
            ))}
          </dl>

          <div>
            <p className="text-[10px] uppercase tracking-wide text-muted">Colour</p>
            <div className="mt-2 flex gap-1.5">
              {analysis.color.dominant_palette.map((hex) => (
                <span
                  key={hex}
                  title={hex}
                  className="h-7 w-7 rounded border border-line"
                  style={{ background: hex }}
                />
              ))}
            </div>
            <div className="mt-3 grid grid-cols-3 gap-3">
              <Meter label="Brightness" value={analysis.color.brightness} />
              <Meter label="Saturation" value={analysis.color.saturation} />
              <Meter label="Contrast" value={analysis.color.contrast} />
            </div>
          </div>

          {analysis.style_takeaways.length ? (
            <div>
              <p className="text-[10px] uppercase tracking-wide text-muted">What we&apos;ll use</p>
              <ul className="mt-1.5 space-y-1 text-xs">
                {analysis.style_takeaways.map((takeaway) => (
                  <li key={takeaway}>• {takeaway}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {/* The IP boundary, stated in the product and not only in the schema. */}
          {analysis.not_transferable.length ? (
            <div className="rounded-md border border-line bg-line/10 p-3">
              <p className="text-[10px] uppercase tracking-wide text-muted">
                What we won&apos;t reuse
              </p>
              <ul className="mt-1.5 space-y-1 text-xs text-muted">
                {analysis.not_transferable.map((item) => (
                  <li key={item}>• {item}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <p className="text-[10px] text-muted">
            Confidence {Math.round(analysis.confidence * 100)}%
          </p>
        </div>
      )}
    </section>
  );
}

export function PreferencePicker({
  options,
  preferences,
  onChange,
  busy,
}: {
  options: StyleOption[];
  preferences: PreferencesView | null;
  onChange: (selected: string[]) => void;
  busy: boolean;
}) {
  const selected = preferences?.preferences.selected_styles ?? [];

  return (
    <section className="rounded-lg border border-line p-5">
      <h2 className="text-sm font-semibold">Visual direction</h2>
      <p className="mt-1 text-xs text-muted">
        Pick what feels right. No design vocabulary needed.
      </p>

      <ul className="mt-4 grid gap-2 sm:grid-cols-2">
        {options.map((option) => {
          const active = selected.includes(option.style);
          return (
            <li key={option.style}>
              <button
                disabled={busy}
                onClick={() =>
                  onChange(
                    active
                      ? selected.filter((s) => s !== option.style)
                      : [...selected, option.style],
                  )
                }
                className={`w-full rounded-md border p-3 text-left transition disabled:opacity-50 ${
                  active ? 'border-ink bg-line/30' : 'border-line hover:border-muted'
                }`}
              >
                <p className="text-xs font-medium">{option.label}</p>
                <p className="mt-0.5 text-[11px] text-muted">{option.description}</p>
              </button>
            </li>
          );
        })}
      </ul>

      {preferences && preferences.profile.length ? (
        <div className="mt-5">
          <p className="text-[10px] uppercase tracking-wide text-muted">Your style profile</p>
          <div className="mt-2 space-y-2">
            {preferences.profile.map((weight) => (
              <Meter key={weight.style} label={humanise(weight.style)} value={weight.weight} />
            ))}
          </div>
          <p className="mt-3 text-xs text-muted">
            Weighted from your picks and your references.
          </p>
        </div>
      ) : null}
    </section>
  );
}

export function CreativeContextPanel({ view }: { view: CreativeContextView }) {
  const { context } = view;
  const style = context.reference_style;

  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold">Creative Context</h2>
        <span
          className={`text-[10px] ${view.ready ? 'text-emerald-400' : 'text-amber-400'}`}
        >
          {view.ready ? 'Ready' : 'Incomplete'}
        </span>
      </div>
      <p className="mt-2 text-sm">{view.summary}</p>

      {style.reference_count ? (
        <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 text-xs sm:grid-cols-3">
          {[
            ['References', String(style.reference_count)],
            ['Composition', style.common_composition],
            ['Lighting', style.common_lighting],
            ['Density', style.common_density],
          ].map(([label, value]) => (
            <div key={label as string}>
              <dt className="text-[10px] uppercase tracking-wide text-muted">{label}</dt>
              <dd className="mt-0.5 capitalize">{humanise(value as string | null)}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {style.shared_palette.length ? (
        <div className="mt-4">
          <p className="text-[10px] uppercase tracking-wide text-muted">Shared palette</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {style.shared_palette.map((hex) => (
              <span
                key={hex}
                title={hex}
                className="h-6 w-6 rounded border border-line"
                style={{ background: hex }}
              />
            ))}
          </div>
        </div>
      ) : null}

      {/* Disagreement between references is information, not noise to average. */}
      {style.tensions.length ? (
        <div className="mt-4 rounded-md border border-amber-500/40 bg-amber-500/5 p-3">
          <p className="text-xs font-medium">Your references disagree</p>
          <ul className="mt-1 space-y-0.5 text-xs text-muted">
            {style.tensions.map((tension) => (
              <li key={tension}>{tension}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {context.guardrails.prohibited_claims.length ? (
        <div className="mt-4">
          <p className="text-[10px] uppercase tracking-wide text-muted">Brand guardrails</p>
          <p className="mt-1 text-xs text-muted">
            Must avoid: {context.guardrails.prohibited_claims.join(', ')}
          </p>
        </div>
      ) : null}

      {context.gaps.length ? (
        <div className="mt-4">
          <p className="text-[10px] uppercase tracking-wide text-muted">Still missing</p>
          <ul className="mt-1 space-y-0.5 text-xs text-muted">
            {context.gaps.map((gap) => (
              <li key={gap}>• {gap}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
