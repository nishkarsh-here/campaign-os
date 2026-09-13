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
import { mediaUrl } from '@/lib/api';
import type {
  CanonicalPrompt,
  GeneratedAssetView,
  GenerationJobView,
  GenerationView,
  JobStatus,
  ModelPromptView,
} from '@/lib/api';

const STATUS_LABEL: Record<JobStatus, string> = {
  PENDING: 'Queued',
  RUNNING: 'Generating…',
  COMPLETED: 'Complete',
  FAILED: 'Failed',
  CANCELLED: 'Cancelled',
};

const STATUS_TONE: Record<JobStatus, string> = {
  PENDING: 'text-muted',
  RUNNING: 'text-amber-400',
  COMPLETED: 'text-emerald-400',
  FAILED: 'text-red-400',
  CANCELLED: 'text-muted',
};

function providerLabel(name: string): string {
  return name.charAt(0).toUpperCase() + name.slice(1);
}

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

function JobCard({
  job,
  busy,
  onRetry,
}: {
  job: GenerationJobView;
  busy: boolean;
  onRetry: () => void;
}) {
  const running = job.status === 'RUNNING' || job.status === 'PENDING';
  return (
    <div className="rounded-md border border-line p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium">{providerLabel(job.provider)}</p>
          <p className="mt-0.5 text-xs text-muted">{job.model}</p>
        </div>
        <span className={`shrink-0 text-xs ${STATUS_TONE[job.status]}`}>
          {STATUS_LABEL[job.status]}
        </span>
      </div>

      {running ? (
        <div className="mt-3 h-1 overflow-hidden rounded bg-line">
          <div className="h-1 w-1/3 animate-pulse rounded bg-ink/50" />
        </div>
      ) : null}

      {job.attempt > 1 ? (
        <p className="mt-2 text-[10px] uppercase tracking-wide text-muted">
          Attempt {job.attempt}
        </p>
      ) : null}

      {job.error_message ? (
        <div className="mt-3 rounded-md border border-red-500/40 bg-red-500/5 p-2.5">
          {/* A reason a person can act on — never a stack trace. */}
          <p className="text-xs">{job.error_message}</p>
          {job.error_code ? (
            <p className="mt-1 font-mono text-[10px] text-muted">{job.error_code}</p>
          ) : null}
        </div>
      ) : null}

      {job.can_retry ? (
        <button
          type="button"
          disabled={busy}
          onClick={onRetry}
          className="mt-3 rounded-md border border-line px-3 py-1.5 text-xs hover:bg-line/40 disabled:opacity-50"
        >
          {busy ? 'Working…' : 'Retry'}
        </button>
      ) : null}
    </div>
  );
}

export function JobBoard({
  view,
  busy,
  onRetry,
}: {
  view: GenerationView;
  busy: boolean;
  onRetry: (jobId: string) => void;
}) {
  if (!view.jobs.length) return null;

  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">Providers</h2>
        {/* Partial success is success, and is reported as such. */}
        <span className="text-xs text-muted">{view.outcome}</span>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {view.jobs.map((job) => (
          <JobCard key={job.id} job={job} busy={busy} onRetry={() => onRetry(job.id)} />
        ))}
      </div>
    </section>
  );
}

export function PlateGallery({
  assets,
  jobs,
  selectedIds,
  onToggleSelect,
}: {
  assets: GeneratedAssetView[];
  jobs: GenerationJobView[];
  selectedIds: string[];
  onToggleSelect: (id: string) => void;
}) {
  const modelFor = new Map(jobs.map((job) => [job.id, job.model]));

  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">Generated creatives</h2>
        <span className="text-xs text-muted">
          {assets.length} visual {assets.length === 1 ? 'plate' : 'plates'}
        </span>
      </div>
      <p className="mt-1 text-xs text-muted">
        These are visual plates. Logo, headline, call to action and exact brand colours are
        applied by the layout renderer later — the image model never sets type.
      </p>

      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {assets.map((asset) => {
          const selected = selectedIds.includes(asset.id);
          return (
            <figure
              key={asset.id}
              className={`overflow-hidden rounded-md border ${
                selected ? 'border-ink/40' : 'border-line'
              }`}
            >
              <button
                type="button"
                onClick={() => onToggleSelect(asset.id)}
                className="block w-full"
                aria-pressed={selected}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={mediaUrl(asset.url)}
                  alt={`${providerLabel(asset.provider)} visual plate`}
                  className="aspect-square w-full bg-line/30 object-cover"
                />
              </button>
              <figcaption className="space-y-1 p-3">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-sm font-medium">{providerLabel(asset.provider)}</span>
                  <span className="rounded-full border border-line px-2 py-0.5 text-[10px] uppercase tracking-wide text-muted">
                    {asset.kind === 'VISUAL_PLATE' ? 'plate' : 'composed'}
                  </span>
                </div>
                <p className="text-xs text-muted">
                  {modelFor.get(asset.generation_job_id) ?? asset.model}
                </p>
                <p className="text-xs text-muted">
                  {asset.width} × {asset.height} · spec v{asset.specification_version}
                </p>
                <p className="text-[10px] text-muted">
                  {new Date(asset.created_at).toLocaleString()}
                </p>
                <a
                  href={mediaUrl(asset.url)}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-block pt-1 text-xs underline hover:no-underline"
                >
                  View full size
                </a>
              </figcaption>
            </figure>
          );
        })}
      </div>

      {selectedIds.length >= 2 ? (
        <Compare
          assets={assets.filter((asset) => selectedIds.includes(asset.id))}
          modelFor={modelFor}
        />
      ) : assets.length >= 2 ? (
        <p className="mt-4 text-xs text-muted">
          Select two or more plates to compare them side by side.
        </p>
      ) : null}
    </section>
  );
}

function Compare({
  assets,
  modelFor,
}: {
  assets: GeneratedAssetView[];
  modelFor: Map<string, string>;
}) {
  return (
    <div className="mt-6 border-t border-line pt-5">
      <h3 className="text-sm font-semibold">Comparing {assets.length}</h3>
      <div className="mt-3 overflow-x-auto">
        <div className="flex gap-4" style={{ minWidth: `${assets.length * 220}px` }}>
          {assets.map((asset) => (
            <div key={asset.id} className="flex-1">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={mediaUrl(asset.url)}
                alt={`${providerLabel(asset.provider)} plate`}
                className="w-full rounded border border-line bg-line/30 object-contain"
              />
              <p className="mt-2 text-xs font-medium">{providerLabel(asset.provider)}</p>
              <p className="text-[10px] text-muted">
                {modelFor.get(asset.generation_job_id) ?? asset.model} · {asset.width} ×{' '}
                {asset.height}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
