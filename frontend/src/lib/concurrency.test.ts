/**
 * Bounded fan-out.
 *
 * The home and project screens resolve one specification per campaign, so this
 * decides both how fast those pages are and whether their market counts are
 * complete.
 */

import { describe, expect, it, vi } from 'vitest';
import { mapWithConcurrency } from '@/lib/concurrency';

describe('mapWithConcurrency', () => {
  it('resolves every item, in order', async () => {
    // Completeness is the point: a partial sweep makes the per-market counts
    // wrong, and a wrong count is worse than a slow page.
    const out = await mapWithConcurrency([1, 2, 3, 4, 5], 2, async (n) => n * 10);
    expect(out).toEqual([10, 20, 30, 40, 50]);
  });

  it('never exceeds the limit', async () => {
    let live = 0;
    let peak = 0;
    await mapWithConcurrency(Array.from({ length: 12 }, (_, i) => i), 3, async () => {
      live += 1;
      peak = Math.max(peak, live);
      await Promise.resolve();
      live -= 1;
      return null;
    });
    expect(peak).toBeLessThanOrEqual(3);
  });

  it('lets one failure cost one result, not the whole sweep', async () => {
    // One campaign whose specification cannot be read should cost that
    // campaign's pin, not every other market on the page.
    const out = await mapWithConcurrency([1, 2, 3], 2, async (n) => {
      if (n === 2) throw new Error('nope');
      return n;
    });
    expect(out).toEqual([1, null, 3]);
  });

  it('handles an empty list without spawning a worker', async () => {
    const fn = vi.fn();
    expect(await mapWithConcurrency([], 4, fn)).toEqual([]);
    expect(fn).not.toHaveBeenCalled();
  });

  it('copes with a limit larger than the list', async () => {
    expect(await mapWithConcurrency([1, 2], 99, async (n) => n)).toEqual([1, 2]);
  });
});
