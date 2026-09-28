'use client';

/**
 * Read-only panels for the campaign command centre.
 *
 * Strictly a read model. Nothing here mutates anything and nothing derives its
 * own version of the truth — every number comes from the service that owns it,
 * so these cannot quietly disagree with the screens they summarise.
 *
 * UI-2B moved the parts of this file that had grown a second opinion: stage
 * routing and state vocabulary now live once in `src/lib/nav.ts` and are drawn
 * by the Meridian, and the next action is `command-center.tsx`'s
 * `NextDecision`. What is left is the three panels that only report.
 */

import Link from 'next/link';
import { CHANNEL_LABELS, type CampaignOverview, mediaUrl } from '@/lib/api';

// --------------------------------------------------------------- the numbers
function OverviewFact({
  label,
  value,
  hint,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
}) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm">{value}</dd>
      {hint ? <p className="mt-0.5 text-xs text-muted">{hint}</p> : null}
    </div>
  );
}


// ------------------------------------------------------------ recommendation
export function RecommendationCard({ view }: { view: CampaignOverview }) {
  const top = view.ranked[0];
  if (!top) return null;

  const selected = view.ranked.find((r) => r.generated_asset_id === view.selected_asset_id);
  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium">Recommendation</h2>
        <Link
          href={`/app/campaigns/${view.campaign_id}/evaluate`}
          className="text-xs text-muted hover:underline"
        >
          All {view.ranked.length} scored →
        </Link>
      </div>

      {view.recommended_asset_id ? (
        <>
          <p className="mt-3 text-2xl font-semibold tracking-tight">
            {Math.round(view.recommended_score ?? top.overall_score)}
            <span className="text-base font-normal text-muted">/100</span>
          </p>
          <p className="mt-1 text-xs text-muted">{view.recommended_reason}</p>
        </>
      ) : (
        <p className="mt-3 text-xs text-muted">
          Nothing is recommended — the evaluator declined rather than putting the least bad
          creative forward.
        </p>
      )}

      <div className="mt-4 border-t border-line pt-3">
        <p className="text-xs text-muted">Selected creative</p>
        {selected ? (
          <p className="mt-0.5 text-sm">
            Rank {selected.rank} · {Math.round(selected.overall_score)}/100 ·{' '}
            <span className="text-muted">{selected.disposition.replace('_', ' ').toLowerCase()}</span>
          </p>
        ) : (
          <p className="mt-0.5 text-sm text-muted">None chosen yet.</p>
        )}
      </div>
    </section>
  );
}

// ------------------------------------------------------------ final assets
export function FinalAssetStrip({ view }: { view: CampaignOverview }) {
  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium">Channels</h2>
        <Link
          href={`/app/campaigns/${view.campaign_id}/compose`}
          className="text-xs text-muted hover:underline"
        >
          Final composition →
        </Link>
      </div>

      {view.final_assets.length ? (
        <ul className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3">
          {view.final_assets.map((asset) => (
            <li key={asset.id}>
              {/* A uniform tile, because a story is 1080x1920 and a banner
                  1200x627 and letting each set its own height makes the row
                  look broken. `contain` rather than `cover`: a thumbnail is
                  for recognising the asset, and cropping to the middle of a
                  tall poster shows the one part with nothing in it. */}
              <div className="flex aspect-[4/3] items-center justify-center overflow-hidden rounded-md border border-line bg-black/30 p-1.5">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={mediaUrl(asset.url)}
                  alt={`${CHANNEL_LABELS[asset.channel]} final asset, version ${asset.version}`}
                  loading="lazy"
                  className="max-h-full max-w-full object-contain"
                />
              </div>
              <p className="mt-1.5 text-xs">{CHANNEL_LABELS[asset.channel]}</p>
              <p className="text-xs text-muted">
                v{asset.version} · {asset.width}×{asset.height}
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 rounded-md border border-dashed border-line p-6 text-center text-xs text-muted">
          No final assets yet.
        </p>
      )}

      {view.available_channels.length ? (
        <p className="mt-4 text-xs text-muted">
          Not composed yet: {view.available_channels.map((c) => CHANNEL_LABELS[c]).join(', ')}.
        </p>
      ) : null}
    </section>
  );
}
