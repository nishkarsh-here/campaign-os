/**
 * Map over items with a bounded number of requests in flight.
 *
 * The product's home screen needs each campaign's market, and the market lives
 * on the campaign specification — there is no endpoint that returns markets
 * across an organization (`docs/UI_UX_VISION.md` §12). So the page resolves
 * them one campaign at a time.
 *
 * Bounded, because the honest alternatives are both worse: firing sixteen
 * parallel requests stalls the connection pool and every other request on the
 * page behind it, and capping the list to the first handful would make the
 * per-market campaign counts wrong — a fabricated number, which is the one
 * thing this interface must not show.
 *
 * Failures resolve to `null` rather than rejecting, because one campaign whose
 * specification cannot be read should cost that campaign's pin, not the whole
 * section.
 */
export async function mapWithConcurrency<T, R>(
  items: readonly T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<(R | null)[]> {
  const results: (R | null)[] = new Array(items.length).fill(null);
  let cursor = 0;

  async function worker(): Promise<void> {
    while (cursor < items.length) {
      const index = cursor++;
      const item = items[index];
      if (item === undefined) continue;
      try {
        results[index] = await fn(item, index);
      } catch {
        // Left as null. An aborted request lands here too, which is correct:
        // the caller is unmounting and nobody will read the result.
        results[index] = null;
      }
    }
  }

  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return results;
}
