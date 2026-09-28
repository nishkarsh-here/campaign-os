/**
 * Reading the generation stage.
 *
 * The contract under test is mostly negative: this module exists so that the
 * generate screen cannot claim a direction identity, a request id, a seed or a
 * provider latency, none of which `GenerationView` carries. The positive half
 * is that one provider means one slot, even when the batch holds three
 * superseded attempts for it.
 */

import { describe, expect, it } from 'vitest';
import {
  anyLive,
  aspectRatio,
  elapsedMs,
  formatElapsed,
  isOfflineProvider,
  jobMeaning,
  providerLabel,
  slots,
  technicalFacts,
} from './generation';
import type { GeneratedAssetView, GenerationJobView, GenerationView } from './api';

function job(over: Partial<GenerationJobView> = {}): GenerationJobView {
  return {
    id: 'j-1',
    provider: 'mock',
    model: 'mock-image-1',
    status: 'COMPLETED',
    attempt: 1,
    can_retry: false,
    error_message: null,
    error_code: null,
    started_at: '2026-01-01T10:00:00Z',
    finished_at: '2026-01-01T10:00:02Z',
    created_at: '2026-01-01T10:00:00Z',
    ...over,
  };
}

function asset(over: Partial<GeneratedAssetView> = {}): GeneratedAssetView {
  return {
    id: 'a-1',
    generation_job_id: 'j-1',
    provider: 'mock',
    model: 'mock-image-1',
    kind: 'VISUAL_PLATE' as GeneratedAssetView['kind'],
    width: 1080,
    height: 1350,
    mime_type: 'image/png',
    url: '/v1/assets/a-1/bytes',
    specification_version: 2,
    created_at: '2026-01-01T10:00:02Z',
    ...over,
  };
}

function view(over: Partial<GenerationView> = {}): GenerationView {
  return {
    campaign_id: 'c-1',
    batch_id: 'b-1',
    canonical_prompt: null,
    prompts: [],
    jobs: [job()],
    assets: [asset()],
    outcome: '1/1 providers succeeded.',
    complete: true,
    specification_version: 2,
    can_generate: true,
    blocked_reason: null,
    ...over,
  };
}

describe('jobMeaning', () => {
  it('names every job status a person can meet', () => {
    expect(jobMeaning('PENDING').label).toBe('Queued');
    expect(jobMeaning('RUNNING').label).toBe('Creating visual');
    expect(jobMeaning('COMPLETED').label).toBe('Visual ready');
    expect(jobMeaning('FAILED').label).toBe('Generation failed');
    expect(jobMeaning('CANCELLED').label).toBe('Cancelled');
  });

  it('marks only the states that are still moving as live', () => {
    expect(jobMeaning('PENDING').live).toBe(true);
    expect(jobMeaning('RUNNING').live).toBe(true);
    for (const terminal of ['COMPLETED', 'FAILED', 'CANCELLED']) {
      expect(jobMeaning(terminal).live).toBe(false);
    }
  });

  it('does not stall a screen on a status it has never seen', () => {
    const unknown = jobMeaning('SOMETHING_NEW');
    expect(unknown.live).toBe(false);
    expect(unknown.label).not.toMatch(/_/);
  });
});

describe('providerLabel', () => {
  it('names the mock provider as a demo generator, never as a model', () => {
    expect(providerLabel('mock')).toBe('Demo generator');
    expect(providerLabel('mock')).not.toMatch(/gemini/i);
    expect(isOfflineProvider('mock')).toBe(true);
  });

  it('names the real providers as themselves', () => {
    expect(providerLabel('gemini')).toBe('Gemini');
    expect(providerLabel('leonardo')).toBe('Leonardo');
    expect(isOfflineProvider('gemini')).toBe(false);
  });

  it('passes an unrecognised provider through rather than guessing', () => {
    expect(providerLabel('someone-else')).toBe('someone-else');
  });
});

describe('elapsed time', () => {
  it('is derived from the two real timestamps', () => {
    expect(elapsedMs(job())).toBe(2000);
    expect(formatElapsed(2000)).toBe('2.0 s');
    expect(formatElapsed(450)).toBe('450 ms');
  });

  it('is null rather than zero when either timestamp is absent', () => {
    expect(elapsedMs(job({ started_at: null }))).toBeNull();
    expect(elapsedMs(job({ finished_at: null }))).toBeNull();
  });

  it('refuses a negative or unreadable interval', () => {
    expect(
      elapsedMs(job({ started_at: '2026-01-01T10:00:05Z', finished_at: '2026-01-01T10:00:00Z' })),
    ).toBeNull();
    expect(elapsedMs(job({ finished_at: 'not a date' }))).toBeNull();
  });
});

describe('slots', () => {
  it('keeps one slot per provider, showing the latest attempt', () => {
    const list = slots(
      view({
        jobs: [
          job({ id: 'j-1', provider: 'mock', attempt: 1, status: 'FAILED' }),
          job({ id: 'j-2', provider: 'mock', attempt: 2, status: 'COMPLETED' }),
        ],
        assets: [asset({ generation_job_id: 'j-2' })],
      }),
    );
    expect(list).toHaveLength(1);
    expect(list[0]!.job.id).toBe('j-2');
    expect(list[0]!.assets).toHaveLength(1);
  });

  it('orders providers stably, so the grid does not reshuffle between polls', () => {
    const list = slots(
      view({
        jobs: [job({ id: 'j-2', provider: 'gemini' }), job({ id: 'j-1', provider: 'mock' })],
        assets: [],
      }),
    );
    expect(list.map((s) => s.job.provider)).toEqual(['gemini', 'mock']);
  });

  it('attaches each asset to the job that produced it', () => {
    const list = slots(
      view({
        jobs: [job({ id: 'j-1', provider: 'mock' }), job({ id: 'j-2', provider: 'gemini' })],
        assets: [
          asset({ id: 'a-1', generation_job_id: 'j-1' }),
          asset({ id: 'a-2', generation_job_id: 'j-2' }),
        ],
      }),
    );
    expect(list.find((s) => s.job.id === 'j-1')?.assets.map((a) => a.id)).toEqual(['a-1']);
    expect(list.find((s) => s.job.id === 'j-2')?.assets.map((a) => a.id)).toEqual(['a-2']);
  });

  it('names slots by provider and never by a direction', () => {
    const list = slots(view());
    // There is no direction id, ordinal or title anywhere on `GenerationView`,
    // so nothing derived from it may carry one.
    expect(JSON.stringify(list)).not.toMatch(/direction/i);
  });

  it('reports liveness from the slots, which is what drives polling', () => {
    expect(anyLive(slots(view()))).toBe(false);
    expect(anyLive(slots(view({ jobs: [job({ status: 'RUNNING' })] })))).toBe(true);
    expect(anyLive(slots(view({ jobs: [job({ status: 'FAILED' })] })))).toBe(false);
  });
});

describe('aspectRatio', () => {
  it('uses the asset’s real pixel dimensions', () => {
    expect(aspectRatio(asset({ width: 1080, height: 1350 }))).toBe('1080 / 1350');
    expect(aspectRatio(asset({ width: 1080, height: 1920 }))).toBe('1080 / 1920');
  });

  it('returns null rather than inventing a shape', () => {
    expect(aspectRatio(asset({ width: 0, height: 0 }))).toBeNull();
  });
});

describe('technicalFacts', () => {
  it('offers only rows the API actually carries', () => {
    const rows = technicalFacts(slots(view())[0]!);
    const labels = rows.map((r) => r.label);
    expect(labels).toContain('Provider');
    expect(labels).toContain('Job id');
    expect(labels).toContain('Took');
    expect(labels).toContain('Size');
    // None of these exist on the contract. An empty row labelled "Request id"
    // implies one exists and was lost.
    expect(labels).not.toContain('Request id');
    expect(labels).not.toContain('Seed');
    expect(labels).not.toContain('Latency');
    expect(labels).not.toContain('Direction');
  });

  it('omits a row rather than printing an empty one', () => {
    const slot = slots(
      view({ jobs: [job({ model: '', started_at: null, finished_at: null })], assets: [] }),
    )[0]!;
    const labels = technicalFacts(slot).map((r) => r.label);
    expect(labels).not.toContain('Model');
    expect(labels).not.toContain('Took');
    expect(labels).not.toContain('Size');
  });

  it('shows the attempt only once there has been more than one', () => {
    const first = technicalFacts(slots(view())[0]!).map((r) => r.label);
    expect(first).not.toContain('Attempt');
    const retried = technicalFacts(
      slots(view({ jobs: [job({ attempt: 2 })], assets: [] }))[0]!,
    ).find((r) => r.label === 'Attempt');
    expect(retried?.value).toBe('2');
  });

  it('never presents wall-clock time as a provider latency', () => {
    const took = technicalFacts(slots(view())[0]!).find((r) => r.label === 'Took');
    expect(took?.value).toBe('2.0 s');
  });
});
