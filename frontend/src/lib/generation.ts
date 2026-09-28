/**
 * Reading the generation stage.
 *
 * ## The thing this module exists to prevent
 *
 * Generation fans out over image **providers**, not over creative directions.
 * `GenerationView` carries no direction id, ordinal or title anywhere, so a
 * slot labelled "Direction 01" would be an association the backend never made.
 * Jobs are grouped and named by provider, because that is what they are.
 *
 * Also absent, and therefore never shown: a provider request id, a seed, and a
 * latency field. Elapsed time *is* derivable from `started_at`/`finished_at`
 * and is offered as such — labelled as measured wall-clock, not as a provider
 * latency it is not.
 */

import type { GeneratedAssetView, GenerationJobView, GenerationView, JobStatus } from '@/lib/api';
import type { Tone } from '@/components/ui';

export interface JobMeaning {
  label: string;
  tone: Tone;
  /** One sentence, in the reader's words. */
  detail: string;
  /** True while the job is still moving — the screen should keep polling. */
  live: boolean;
}

const MEANING: Record<JobStatus, JobMeaning> = {
  PENDING: {
    label: 'Queued',
    tone: 'neutral',
    detail: 'Waiting for the provider to pick it up.',
    live: true,
  },
  RUNNING: {
    label: 'Creating visual',
    tone: 'active',
    detail: 'The provider is working on this one now.',
    live: true,
  },
  COMPLETED: {
    label: 'Visual ready',
    tone: 'positive',
    detail: 'The provider returned a visual.',
    live: false,
  },
  FAILED: {
    label: 'Generation failed',
    tone: 'negative',
    detail: 'The provider could not produce a visual.',
    live: false,
  },
  CANCELLED: {
    label: 'Cancelled',
    tone: 'neutral',
    detail: 'This job was stopped before it finished.',
    live: false,
  },
};

export function jobMeaning(status: string): JobMeaning {
  return (
    MEANING[status as JobStatus] ?? {
      label: status.replace(/_/g, ' ').toLowerCase(),
      tone: 'neutral' as Tone,
      detail: '',
      live: false,
    }
  );
}

/**
 * A provider's name, as a person should read it.
 *
 * The mock provider is named honestly. The offline demo has to behave exactly
 * like the real workflow, but it must never be dressed up as a real model —
 * "is this real output?" is the first question anyone watching has, and the
 * provenance is the one place that answers it.
 */
export function providerLabel(provider: string): string {
  switch (provider.toLowerCase()) {
    case 'mock':
      return 'Demo generator';
    case 'gemini':
      return 'Gemini';
    case 'leonardo':
      return 'Leonardo';
    default:
      return provider;
  }
}

/** True for a provider that does not leave this machine. */
export function isOfflineProvider(provider: string): boolean {
  return provider.toLowerCase() === 'mock';
}

/**
 * Wall-clock time a job took, in milliseconds.
 *
 * Derived from two real timestamps, not read from a latency field — there is
 * none. It therefore includes queue time and our own overhead, so it is
 * presented as "took", never as the provider's latency.
 */
export function elapsedMs(job: GenerationJobView): number | null {
  if (!job.started_at || !job.finished_at) return null;
  const started = Date.parse(job.started_at);
  const finished = Date.parse(job.finished_at);
  if (Number.isNaN(started) || Number.isNaN(finished) || finished < started) return null;
  return finished - started;
}

export function formatElapsed(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export interface Slot {
  job: GenerationJobView;
  /** Assets this job produced. Usually one; the config permits up to four. */
  assets: GeneratedAssetView[];
  meaning: JobMeaning;
  elapsed: number | null;
}

/**
 * One slot per provider, showing its latest attempt.
 *
 * `GenerationView.jobs` contains every job in the batch *including superseded
 * retry attempts*, so rendering the list as-is shows the same provider three
 * times with two stale failures. Grouping by provider and keeping the highest
 * `attempt` is what a person means by "how did each provider do".
 */
export function slots(view: GenerationView): Slot[] {
  const latest = new Map<string, GenerationJobView>();
  for (const job of view.jobs) {
    const held = latest.get(job.provider);
    if (!held || job.attempt > held.attempt) latest.set(job.provider, job);
  }
  return [...latest.values()]
    .sort((a, b) => a.provider.localeCompare(b.provider))
    .map((job) => ({
      job,
      assets: view.assets.filter((a) => a.generation_job_id === job.id),
      meaning: jobMeaning(job.status),
      elapsed: elapsedMs(job),
    }));
}

/** True while any slot is still moving. Drives polling, and stops it. */
export function anyLive(list: readonly Slot[]): boolean {
  return list.some((s) => s.meaning.live);
}

/**
 * A CSS aspect ratio from the asset's real pixel dimensions.
 *
 * So a 4:5 portrait is framed as 4:5 and a story as 9:16, rather than every
 * plate being squeezed into one thumbnail box. Returns null when the asset
 * reports nothing usable, and the caller falls back to a neutral frame instead
 * of guessing a shape.
 */
export function aspectRatio(asset: GeneratedAssetView): string | null {
  if (!asset.width || !asset.height) return null;
  return `${asset.width} / ${asset.height}`;
}

/** Technical facts that genuinely exist, for the details disclosure. */
export function technicalFacts(slot: Slot): { label: string; value: string }[] {
  const rows: { label: string; value: string | null }[] = [
    { label: 'Provider', value: providerLabel(slot.job.provider) },
    { label: 'Model', value: slot.job.model || null },
    { label: 'Job id', value: slot.job.id },
    { label: 'Attempt', value: slot.job.attempt > 1 ? String(slot.job.attempt) : null },
    { label: 'Took', value: slot.elapsed === null ? null : formatElapsed(slot.elapsed) },
    {
      label: 'Size',
      value: slot.assets[0] ? `${slot.assets[0].width} × ${slot.assets[0].height}` : null,
    },
    { label: 'Format', value: slot.assets[0]?.mime_type ?? null },
    { label: 'Error code', value: slot.job.error_code },
  ];
  // No request id and no seed rows: the API carries neither, and an empty row
  // labelled "Request id" implies one exists and was lost.
  return rows.filter((r): r is { label: string; value: string } => Boolean(r.value));
}
