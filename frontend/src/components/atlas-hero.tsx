'use client';

/**
 * ATLAS — the product's visual signature.
 *
 * One brand truth at the top, lines running down to the markets it has been
 * adapted for. That is the whole product in one image, which is why it is the
 * first thing on the home screen.
 *
 * ## Why this is not WebGL
 *
 * A graticule plane in CSS `perspective` gets the spatial, cartographic feel
 * for roughly two kilobytes and zero runtime cost: the plane is one element
 * with a repeating-gradient background and a `rotateX`, the connectors are one
 * inline SVG, and the parallax is two custom properties set on pointer move.
 * A Three.js scene would mean a ~150KB dependency, a canvas that has to be
 * sized and torn down, a fallback path for when it fails, and a device-class
 * question on every phone — for an illusion this already achieves. The vision
 * document reserves WebGL for surfaces where it earns that cost; a hero
 * graphic is not one.
 *
 * ## Why the pins are real
 *
 * `markets` comes from campaign specifications the caller has already fetched.
 * A market with no campaigns is not drawn, and when nothing is known the plane
 * renders bare with a sentence saying so. An invented pin on a map of a
 * product about locality would be the single most dishonest thing this
 * interface could do.
 *
 * Node positions are derived from a hash of the region string, so a market
 * always lands in the same place — stable across renders and between server
 * and client, with no randomness to desynchronise hydration.
 */

import { useCallback, useRef } from 'react';
import Link from 'next/link';
import type { MarketGroup } from '@/lib/market';
import { buttonStyles, cx } from '@/components/ui';

/**
 * A stable position for a region, inside a safe band of the plane.
 *
 * A deterministic string hash rather than `Math.random`: the same market must
 * sit in the same place on every render, and a random position would also
 * differ between the server's HTML and the client's, which React reports as a
 * hydration mismatch.
 */
function placeOf(region: string, index: number): { left: number; top: number } {
  let hash = 0;
  for (let i = 0; i < region.length; i++) hash = (hash * 31 + region.charCodeAt(i)) | 0;
  const h = Math.abs(hash);
  // Spread horizontally by index first so nodes never collide, then nudge by
  // the hash so the arrangement does not look like a row of tick marks.
  const lane = (index + 0.5) / Math.max(1, TOTAL_LANES);
  return {
    left: Math.round((lane * 100 + ((h % 9) - 4)) * 10) / 10,
    top: 34 + (h % 26),
  };
}
const TOTAL_LANES = 3;

export function AtlasHero({
  markets,
  /** Real count, from campaigns the caller actually loaded. */
  campaignCount,
  brandCount,
  /** Absent for a viewer, who cannot create one. */
  canCreate,
}: {
  markets: readonly MarketGroup[];
  campaignCount: number;
  brandCount: number;
  canCreate: boolean;
}) {
  const stage = useRef<HTMLDivElement>(null);

  /**
   * Pointer parallax.
   *
   * Written straight to custom properties rather than through React state:
   * this fires on every mouse move, and a `setState` per move would re-render
   * the hero sixty times a second to move it four pixels.
   *
   * Mouse only. On a touch screen `pointermove` arrives mid-scroll, which
   * would make the hero lurch while the page is being dragged.
   */
  const onPointerMove = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (event.pointerType !== 'mouse') return;
    const el = stage.current;
    if (!el) return;
    const box = el.getBoundingClientRect();
    el.style.setProperty('--px', String(((event.clientX - box.left) / box.width - 0.5).toFixed(3)));
    el.style.setProperty('--py', String(((event.clientY - box.top) / box.height - 0.5).toFixed(3)));
  }, []);

  const reset = useCallback(() => {
    stage.current?.style.setProperty('--px', '0');
    stage.current?.style.setProperty('--py', '0');
  }, []);

  const shown = markets.slice(0, TOTAL_LANES);

  return (
    <section
      aria-labelledby="atlas-title"
      className="relative overflow-hidden border-b border-line"
    >
      <div
        ref={stage}
        onPointerMove={onPointerMove}
        onPointerLeave={reset}
        className="atlas-stage relative mx-auto grid max-w-page gap-8 px-gutter py-10 sm:px-gutter-lg lg:grid-cols-[1.05fr_1fr] lg:items-center lg:gap-12 lg:py-16"
      >
        {/* ------------------------------------------------- the proposition */}
        <div className="relative z-10">
          <p className="text-label uppercase text-muted">Campaign OS</p>
          <h1 id="atlas-title" className="mt-3 text-display">
            Build campaigns that feel local everywhere.
          </h1>
          <p className="mt-4 max-w-content text-body text-muted">
            Turn brand intelligence into locally relevant campaigns, creatives and channel assets.
          </p>

          <div className="mt-7 flex flex-wrap items-center gap-3">
            {canCreate ? (
              <Link href="/app/campaigns" className={buttonStyles('primary', 'lg')}>
                Create campaign
              </Link>
            ) : null}
            <Link href="/app/campaigns" className={buttonStyles(canCreate ? 'secondary' : 'primary', 'lg')}>
              {canCreate ? 'Explore workspace' : 'Browse campaigns'}
            </Link>
          </div>

          {/* Counts, not statistics: each is the length of a list actually
              fetched, and each names what it counted. */}
          <dl className="mt-8 flex flex-wrap gap-x-8 gap-y-3 border-t border-line pt-5">
            <Figure value={campaignCount} one="Campaign" many="Campaigns" />
            <Figure value={brandCount} one="Brand" many="Brands" />
            <Figure value={markets.length} one="Market" many="Markets" />
          </dl>
        </div>

        {/* ------------------------------------------------------- the atlas */}
        <div className="relative h-[280px] sm:h-[340px] lg:h-[400px]" aria-hidden="true">
          {/* The plane. One element: a graticule drawn with two repeating
              gradients, laid back in perspective and faded at the edges with a
              mask so it reads as ground rather than as a table. */}
          <div className="atlas-plane" />

          {/* Connectors from the brand point down to each market. Percentage
              viewBox with `preserveAspectRatio="none"`, so SVG coordinates and
              the nodes' CSS percentages are the same space. */}
          <svg
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            className="absolute inset-0 h-full w-full"
          >
            {shown.map((market, i) => {
              const { left, top } = placeOf(market.region, i);
              return (
                <line
                  key={market.region}
                  x1="50"
                  y1="10"
                  x2={left}
                  y2={top}
                  className="atlas-thread"
                  style={{ animationDelay: `${180 + i * 90}ms` }}
                />
              );
            })}
          </svg>

          {/* The brand: one source, at the top. */}
          <div className="atlas-origin arrive" style={{ left: '50%', top: '10%' }}>
            <span className="atlas-origin-dot" />
            <span className="atlas-origin-label">One brand truth</span>
          </div>

          {shown.map((market, i) => {
            const { left, top } = placeOf(market.region, i);
            return (
              <div
                key={market.region}
                className="atlas-node arrive"
                style={{
                  left: `${left}%`,
                  top: `${top}%`,
                  animationDelay: `${260 + i * 110}ms`,
                }}
              >
                <span className="atlas-node-dot" />
                <span className="atlas-node-label">
                  {/* The region string exactly as the specification holds it —
                      never split into city and state, which it is not. */}
                  <span className="block text-label uppercase text-ink">{market.region}</span>
                  {market.languages[0] ? (
                    <span className="block text-label uppercase text-muted">
                      {market.languages[0]}
                    </span>
                  ) : null}
                </span>
              </div>
            );
          })}
        </div>

        {/* When there is genuinely nothing to plot, the plane stays bare and
            says why. The alternative — decorative pins — would misrepresent an
            empty workspace as a busy one. */}
        {shown.length === 0 ? (
          <p className="pointer-events-none absolute bottom-6 right-gutter-lg z-10 max-w-[18rem] text-right text-caption text-muted lg:bottom-16">
            Markets appear here once a campaign brief names the place it runs in.
          </p>
        ) : null}
      </div>
    </section>
  );
}

function Figure({ value, one, many }: { value: number; one: string; many: string }) {
  // "1 Brands" reads as a bug to everyone who sees it, and it is one.
  const label = value === 1 ? one : many;
  return (
    <div>
      {/* The term for assistive technology, the same word hidden from it
          visually — otherwise a screen reader reads "Campaigns, 3 Campaigns". */}
      <dt className="sr-only">{label}</dt>
      <dd>
        <span className="text-h2 tabular-nums">{value}</span>
        <span aria-hidden="true" className="ml-2 text-label uppercase text-muted">
          {label}
        </span>
      </dd>
    </div>
  );
}
