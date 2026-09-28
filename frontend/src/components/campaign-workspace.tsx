'use client';

/**
 * The persistent campaign workspace furniture.
 *
 * Two pieces, both owned by the campaign layout so neither resets as a person
 * moves between stages:
 *
 *   - `CampaignIdentityBar` — a compact ledger strip answering "what am I
 *     working on?" without taking a third of the screen to do it.
 *   - `CampaignContextRail` — the right-hand column: what needs deciding, where
 *     this campaign runs, and what has been produced.
 *
 * ## One next action, in one place
 *
 * The rail is the single canonical home for "what do I do now" — on every
 * stage, in the same position. The command centre deliberately no longer
 * repeats it as a hero card: two next-action affordances on one screen is how a
 * person learns to trust neither. The command centre is the fuller read
 * (progress, market, provenance, assets); the rail is the standing instruction.
 */

import Link from 'next/link';
import {
  Card,
  StatusBadge,
  buttonStyles,
  cx,
} from '@/components/ui';
import type { CampaignOverview, CampaignSpecification } from '@/lib/api';
import type { Capabilities } from '@/lib/capabilities';
import { statusMeaning } from '@/lib/campaign-status';
import { displayLanguage, hasMarket, marketFacts } from '@/lib/market';
import { resolveJourney, type ResolvedNode } from '@/lib/nav';

// ------------------------------------------------------------- identity bar

/**
 * Who, what, where — in one strip.
 *
 * The brief's seven facts (campaign, brand, market, language, audience, status,
 * next action) with the campaign name as the anchor and the rest as small
 * labelled metadata. The Atlas "Ledger" device: a distinct, quiet voice for
 * facts about the work, so they do not compete with the work.
 *
 * A fact with no value is omitted rather than rendered as a dash — this is a
 * strip, not a form, and six em dashes read as a broken header.
 */
export function CampaignIdentityBar({
  overview,
  specification,
  campaignId,
}: {
  overview: CampaignOverview | null;
  specification: CampaignSpecification | null;
  campaignId: string;
}) {
  const status = overview?.status ? statusMeaning(overview.status) : null;
  const facts: { label: string; value: string | null }[] = [
    { label: 'Brand', value: overview?.brand_name ?? null },
    { label: 'Market', value: specification?.region ?? null },
    { label: 'Language', value: displayLanguage(specification?.language) },
    { label: 'Audience', value: specification?.audience ?? null },
  ];
  const present = facts.filter((f) => f.value);

  return (
    <div className="min-w-0">
      <p className="text-label uppercase text-muted">Campaign</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-2">
        {/*
          The one `h1` in the workspace. Stage pages render `h2` and down, so
          the outline follows the hierarchy instead of every page starting a new
          document with the same words this bar just said.
        */}
        <h1 className="min-w-0 text-h1">
          {/* Links to the command centre: from inside a stage there was
              otherwise no way back to the campaign's own summary. */}
          <Link
            href={`/app/campaigns/${campaignId}/overview`}
            className="transition-colors duration-fast hover:text-accent"
          >
            {overview?.title ?? 'Campaign'}
          </Link>
        </h1>
        {status ? <StatusBadge tone={status.tone}>{status.label}</StatusBadge> : null}
      </div>

      {present.length > 0 ? (
        <dl className="mt-4 flex flex-wrap gap-x-8 gap-y-3 border-t border-line pt-3">
          {present.map((fact) => (
            <div key={fact.label} className="min-w-0 max-w-[22rem]">
              <dt className="text-label uppercase text-muted">{fact.label}</dt>
              <dd className="mt-0.5 truncate text-small text-ink" title={fact.value ?? undefined}>
                {fact.value}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  );
}

// -------------------------------------------------------------- context rail

export function CampaignContextRail({
  campaignId,
  overview,
  specification,
  capabilities,
}: {
  campaignId: string;
  overview: CampaignOverview | null;
  specification: CampaignSpecification | null;
  capabilities: Capabilities;
}) {
  const nodes = resolveJourney(campaignId, overview);
  return (
    <div className="space-y-4">
      <NextActionCard
        campaignId={campaignId}
        overview={overview}
        nodes={nodes}
        capabilities={capabilities}
      />
      <MarketGlance campaignId={campaignId} specification={specification} />
      <ProducedGlance campaignId={campaignId} overview={overview} />
    </div>
  );
}

/**
 * Whether the next action is an approval rather than a piece of work.
 *
 * Matched on the backend's wording because the overview does not label its
 * actions by kind. Deliberately conservative: an unmatched action counts as
 * work, so the worst case is offering a control the server refuses — never
 * hiding a step from the person whose job it is.
 */
export function isApprovalGate(action: string): boolean {
  return /approve|confirm|sign off|decision/i.test(action);
}

export function NextActionCard({
  campaignId,
  overview,
  nodes,
  capabilities,
}: {
  campaignId: string;
  overview: CampaignOverview | null;
  nodes: readonly ResolvedNode[];
  capabilities: Capabilities;
}) {
  if (!overview) {
    return (
      <Card>
        <p className="text-label uppercase text-muted">Next</p>
        <p className="mt-2 text-body text-muted">Reading the campaign…</p>
      </Card>
    );
  }

  if (!overview.next_stage || !overview.next_action) {
    return (
      <Card className="border-l-2 border-l-success">
        <p className="text-label uppercase text-success">Nothing waiting</p>
        <p className="mt-2 text-body">This campaign is complete.</p>
        <Link
          href={`/app/campaigns/${campaignId}/compose`}
          className={buttonStyles('secondary', 'md', 'mt-4 w-full')}
        >
          See the final assets
        </Link>
      </Card>
    );
  }

  const node = nodes.find(
    (n) => n.backing.kind === 'stage' && n.backing.stageKey === overview.next_stage,
  );
  const gate = isApprovalGate(overview.next_action);
  const permitted = gate ? capabilities.can('approve') : capabilities.can('edit_campaign');

  return (
    <Card className="border-l-2 border-l-accent">
      <p className="text-label uppercase text-accent">Your next decision</p>
      {/* The backend's own sentence. Not paraphrased — paraphrasing is where a
          second, disagreeing description of the truth comes from. */}
      <p className="mt-2 text-body font-medium">{overview.next_action}</p>
      {node ? (
        <>
          <Link
            href={node.href}
            className={buttonStyles(permitted ? 'primary' : 'secondary', 'md', 'mt-4 w-full')}
          >
            {permitted ? `Go to ${node.label.toLowerCase()}` : `View ${node.label.toLowerCase()}`}
          </Link>
          {!permitted ? (
            // Said, not implied. A person who cannot act deserves to know why
            // rather than to find a button missing.
            <p className="mt-2 text-caption text-muted">
              {gate
                ? 'This needs someone with approval rights.'
                : 'Your role is read-only for this step.'}
            </p>
          ) : null}
        </>
      ) : null}
    </Card>
  );
}

/** Where this campaign runs — at a glance, with the full picture one click on. */
function MarketGlance({
  campaignId,
  specification,
}: {
  campaignId: string;
  specification: CampaignSpecification | null;
}) {
  const facts = marketFacts(specification);
  const known = hasMarket(facts);
  const shown = facts.filter((f) => f.value).slice(0, 3);

  return (
    <Card>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-label uppercase text-muted">Local market</h2>
        <Link
          href={`/app/campaigns/${campaignId}/market`}
          className="text-label uppercase text-muted transition-colors duration-fast hover:text-ink"
        >
          Open
        </Link>
      </div>
      {known ? (
        <dl className="mt-3 space-y-2.5">
          {shown.map((fact) => (
            <div key={fact.key}>
              <dt className="text-label uppercase text-muted">{fact.label}</dt>
              <dd className="mt-0.5 text-small">{fact.value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mt-3 text-small text-muted">
          No market decided yet. The brief settles it.
        </p>
      )}
    </Card>
  );
}

/**
 * What this campaign has actually produced.
 *
 * Four counts, each the value of a field the overview already computed. A zero
 * is rendered as a zero — "nothing yet" is information, and hiding it would
 * make an empty campaign look like a loading one.
 */
function ProducedGlance({
  campaignId,
  overview,
}: {
  campaignId: string;
  overview: CampaignOverview | null;
}) {
  if (!overview) return null;
  const rows: { label: string; value: number; href: string }[] = [
    {
      label: 'Visuals generated',
      value: overview.latest_batch_assets,
      href: `/app/campaigns/${campaignId}/generate`,
    },
    {
      label: 'Scored',
      value: overview.ranked.length,
      href: `/app/campaigns/${campaignId}/evaluate`,
    },
    {
      label: 'Brand checks run',
      value: overview.guardian_checked,
      href: `/app/campaigns/${campaignId}/refine`,
    },
    {
      label: 'Channels composed',
      value: overview.composed_channels.length,
      href: `/app/campaigns/${campaignId}/compose`,
    },
  ];

  return (
    <Card padding={false}>
      <h2 className="px-5 pt-5 text-label uppercase text-muted">Produced so far</h2>
      <dl className="mt-3 divide-y divide-line border-t border-line">
        {rows.map((row) => (
          <Link
            key={row.label}
            href={row.href}
            className="flex items-center justify-between gap-3 px-5 py-2.5 transition-colors duration-fast hover:bg-line/20"
          >
            <dt className="text-small text-muted">{row.label}</dt>
            <dd
              className={cx(
                'shrink-0 text-body tabular-nums',
                row.value === 0 ? 'text-muted' : 'text-ink',
              )}
            >
              {row.value}
            </dd>
          </Link>
        ))}
      </dl>
      {overview.failed_generations > 0 ? (
        <p className="border-t border-line px-5 py-2.5 text-caption text-danger">
          {overview.failed_generations} generation
          {overview.failed_generations === 1 ? '' : 's'} failed
        </p>
      ) : null}
    </Card>
  );
}
