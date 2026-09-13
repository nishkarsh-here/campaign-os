'use client';

/**
 * The campaign command centre.
 *
 * One screen that answers "where is this campaign, and what is waiting on me?"
 * without making anyone open six others.
 *
 * It is strictly a read model. Nothing here mutates anything, nothing derives
 * its own version of the truth, and every number comes from the service that
 * owns it — so this page cannot quietly disagree with the screen it summarises.
 * What it adds is *order*: the stages in the sequence the product runs them,
 * each with a state and a sentence, and one clear next action.
 */

import Link from 'next/link';
import {
  CHANNEL_LABELS,
  type CampaignOverview,
  type GuardianVerdict,
  type StageState,
  type StageStateView,
  mediaUrl,
} from '@/lib/api';
import { StatusBadge, type Tone } from '@/components/states';

/** Where each stage lives, so "what's next" is one click rather than a hunt. */
const STAGE_ROUTES: Record<string, string> = {
  discovery: '',
  creative: '/creative',
  generation: '/generate',
  evaluation: '/evaluate',
  guardian: '/refine',
  composition: '/compose',
};

const STATE_TONE: Record<StageState, Tone> = {
  DONE: 'positive',
  RUNNING: 'active',
  ATTENTION: 'caution',
  FAILED: 'negative',
  PENDING: 'neutral',
  BLOCKED: 'neutral',
};

const STATE_LABEL: Record<StageState, string> = {
  DONE: 'Done',
  RUNNING: 'Running',
  ATTENTION: 'Needs you',
  FAILED: 'Failed',
  PENDING: 'Not started',
  BLOCKED: 'Blocked',
};

const VERDICT_TONE: Record<GuardianVerdict, Tone> = {
  PASS: 'positive',
  NEEDS_REVISION: 'caution',
  REJECT: 'negative',
  UNKNOWN: 'neutral',
};

const VERDICT_LABEL: Record<GuardianVerdict, string> = {
  PASS: 'Pass',
  NEEDS_REVISION: 'Needs revision',
  REJECT: 'Reject',
  UNKNOWN: 'Not checked',
};

function href(campaignId: string, key: string): string {
  return `/app/campaigns/${campaignId}${STAGE_ROUTES[key] ?? ''}`;
}

// ------------------------------------------------------------------ the spine
export function StageSpine({
  view,
}: {
  view: CampaignOverview;
}) {
  return (
    <section className="rounded-lg border border-line">
      <h2 className="border-b border-line px-5 py-3 text-sm font-medium">Progress</h2>
      <ol className="divide-y divide-line">
        {view.stages.map((stage: StageStateView) => (
          <li key={stage.key}>
            <Link
              href={href(view.campaign_id, stage.key)}
              className="flex items-start gap-4 px-5 py-3 hover:bg-line/20"
            >
              <StatusBadge tone={STATE_TONE[stage.state]}>{STATE_LABEL[stage.state]}</StatusBadge>
              <span className="min-w-0">
                <span className="block text-sm font-medium">{stage.label}</span>
                <span className="mt-0.5 block text-xs text-muted">{stage.detail}</span>
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}

// -------------------------------------------------------------- what's next
export function NextAction({ view }: { view: CampaignOverview }) {
  if (!view.next_stage) {
    return (
      <section className="rounded-lg border border-emerald-500/40 bg-emerald-500/5 p-5">
        <h2 className="text-sm font-medium">Nothing is waiting on you</h2>
        <p className="mt-1 text-xs text-muted">
          Every stage is complete and the final assets are exported.
        </p>
        <Link
          href={`/app/campaigns/${view.campaign_id}/compose`}
          className="mt-4 inline-block rounded-md border border-line bg-line/30 px-3 py-1.5 text-sm hover:bg-line/50"
        >
          Open the final assets →
        </Link>
      </section>
    );
  }

  const stage = view.stages.find((s) => s.key === view.next_stage);
  return (
    <section className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-5">
      <h2 className="text-sm font-medium">Next: {stage?.label ?? 'Continue'}</h2>
      <p className="mt-1 text-xs text-muted">{view.next_action}</p>
      <Link
        href={href(view.campaign_id, view.next_stage)}
        className="mt-4 inline-block rounded-md border border-line bg-line/30 px-3 py-1.5 text-sm hover:bg-line/50"
      >
        Go there →
      </Link>
    </section>
  );
}

// --------------------------------------------------------------- the numbers
function Fact({
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

export function CampaignFacts({ view }: { view: CampaignOverview }) {
  return (
    <section className="rounded-lg border border-line p-5">
      <h2 className="text-sm font-medium">State</h2>
      <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-4">
        <Fact label="Brand" value={view.brand_name} />
        <Fact
          label="Campaign Specification"
          value={
            view.campaign_specification_version
              ? `v${view.campaign_specification_version}`
              : 'Not yet'
          }
        />
        <Fact
          label="Creative Specification"
          value={
            view.creative_specification_version
              ? `v${view.creative_specification_version}`
              : 'Not yet'
          }
          hint={view.creative_specification_approved ? 'Approved' : 'Awaiting approval'}
        />
        <Fact
          label="Layout"
          value={view.latest_layout_version ? `v${view.latest_layout_version}` : 'Not composed'}
        />
        <Fact
          label="Latest generation"
          value={`${view.latest_batch_assets} plate${view.latest_batch_assets === 1 ? '' : 's'}`}
          hint={
            view.failed_generations
              ? `${view.failed_generations} job(s) failed`
              : 'Newest batch only'
          }
        />
        <Fact
          label="Revisions"
          value={view.revision_rounds}
          hint={view.revision_rounds ? 'Earlier versions are kept' : 'None yet'}
        />
      </dl>
    </section>
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

// ------------------------------------------------------------- brand status
export function BrandStatusCard({ view }: { view: CampaignOverview }) {
  const verdict = view.guardian_verdict;
  return (
    <section className="rounded-lg border border-line p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium">Brand check</h2>
        {verdict ? (
          <StatusBadge tone={VERDICT_TONE[verdict]}>{VERDICT_LABEL[verdict]}</StatusBadge>
        ) : (
          <StatusBadge>Not run</StatusBadge>
        )}
      </div>
      <p className="mt-2 text-xs text-muted">
        {verdict
          ? `${view.guardian_checked} creative${view.guardian_checked === 1 ? '' : 's'} checked against the Brand Brain.`
          : 'The Brand Guardian has not run for this campaign.'}
      </p>
      <Link
        href={`/app/campaigns/${view.campaign_id}/refine`}
        className="mt-3 inline-block text-xs text-muted hover:underline"
      >
        Open the findings →
      </Link>
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
