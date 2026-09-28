'use client';

/**
 * A project, as a workspace.
 *
 * The layout above states the scope — project, brand, markets, campaign count.
 * This page is what is *in* it: each campaign with the place it runs in, where
 * it has got to, and the one thing it is waiting for.
 *
 * Every campaign row is real: title and status from the campaign list, market
 * from its specification. What a row deliberately does not show is a thumbnail
 * or a stage indicator, because both would need a per-campaign summary request
 * and this list can hold a dozen — see the note on `CampaignCard`.
 */

import Link from 'next/link';
import {
  Card,
  EmptyState,
  PlaceStamp,
  Reveal,
  SectionHeader,
  SkeletonRows,
  StatusBadge,
  buttonStyles,
} from '@/components/ui';
import type { Campaign, CampaignSpecification } from '@/lib/api';
import { statusMeaning } from '@/lib/campaign-status';
import { useProjectScope } from '@/lib/project-context';

export default function ProjectPage() {
  const { project, campaigns, markets, specs, resolving } = useProjectScope();

  // The layout owns the error gate; a null project here means still loading.
  if (!project) return <SkeletonRows rows={3} />;

  const waiting = campaigns.filter((c) => statusMeaning(c.status).awaitsHuman);

  return (
    <div className="space-y-section">
      {waiting.length > 0 ? (
        <section aria-labelledby="project-waiting">
          <SectionHeader
            title={<span id="project-waiting">Waiting on you</span>}
            description="These cannot move until someone in the project makes a decision."
          />
          <ul className="mt-lg space-y-3">
            {waiting.map((campaign, i) => (
              <CampaignCard
                key={campaign.id}
                campaign={campaign}
                spec={specs.get(campaign.id) ?? null}
                index={i}
                emphasise
              />
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="project-campaigns">
        <SectionHeader
          title={<span id="project-campaigns">Campaigns</span>}
          description="Everything this project has produced or is producing."
          actions={
            <Link href="/app/campaigns" className={buttonStyles('secondary', 'md')}>
              New campaign
            </Link>
          }
        />
        <div className="mt-lg">
          {campaigns.length === 0 ? (
            <EmptyState
              title="No campaigns in this project"
              description="Start one from the campaigns screen and it will appear here."
              action={
                <Link href="/app/campaigns" className={buttonStyles('primary', 'lg')}>
                  Go to campaigns
                </Link>
              }
            />
          ) : (
            <ul className="space-y-3">
              {campaigns.map((campaign, i) => (
                <CampaignCard
                  key={campaign.id}
                  campaign={campaign}
                  spec={specs.get(campaign.id) ?? null}
                  index={i}
                />
              ))}
            </ul>
          )}
        </div>
      </section>

      {/* Markets this project runs in — derived from its own campaigns, so it
          is a restatement of real data rather than a second source for it. */}
      <section aria-labelledby="project-markets">
        <SectionHeader
          title={<span id="project-markets">Markets in this project</span>}
          description="Where this project’s campaigns have been written to belong."
        />
        <div className="mt-lg">
          {resolving && markets.length === 0 ? (
            <SkeletonRows rows={1} />
          ) : markets.length === 0 ? (
            <EmptyState
              title="No market named yet"
              description="A market appears once a campaign brief in this project names the place it runs in."
            />
          ) : (
            <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {markets.map((market, i) => (
                <Reveal as="li" key={market.region} index={i}>
                  <Card className="h-full">
                    <h3 className="text-h3">{market.region}</h3>
                    {market.languages.length > 0 ? (
                      <p className="mt-1.5 text-label uppercase text-muted">
                        {market.languages.join(' · ')}
                      </p>
                    ) : null}
                    <p className="mt-3 border-t border-line pt-3 text-small tabular-nums text-muted">
                      {market.campaignIds.length}{' '}
                      {market.campaignIds.length === 1 ? 'campaign' : 'campaigns'}
                    </p>
                  </Card>
                </Reveal>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}

/**
 * One campaign in a project.
 *
 * Deliberately without a thumbnail or a stage bar. Both exist per campaign —
 * `CampaignOverview` carries `stages` and `final_assets` — but reading them
 * means one request per row, and a project list of twelve campaigns would open
 * twelve. The command centre shows both, for the one campaign in view, at the
 * cost of the one request that is reasonable there.
 */
function CampaignCard({
  campaign,
  spec,
  index,
  emphasise,
}: {
  campaign: Campaign;
  spec: CampaignSpecification | null;
  index: number;
  emphasise?: boolean;
}) {
  const meaning = statusMeaning(campaign.status);
  return (
    <Reveal as="li" index={index}>
      <Card padding={false} className={emphasise ? 'border-l-2 border-l-accent' : undefined}>
        <Link
          href={`/app/campaigns/${campaign.id}/overview`}
          className="flex flex-col gap-3 p-5 transition-colors duration-fast hover:bg-line/20 sm:flex-row sm:items-center sm:gap-5"
        >
          <span className="min-w-0 flex-1">
            <span className="block text-h3">{campaign.title}</span>
            <PlaceStamp
              region={spec?.region}
              language={spec?.language}
              occasion={spec?.timing_occasion}
              detail="full"
              className="mt-2"
            />
            {spec?.objective ? (
              <span className="mt-2 block line-clamp-1 text-small text-muted">
                {spec.objective}
              </span>
            ) : null}
          </span>
          <span className="flex shrink-0 flex-wrap items-center gap-3">
            <StatusBadge tone={meaning.tone}>{meaning.label}</StatusBadge>
            {meaning.invitation ? (
              <span className="text-small text-accent">{meaning.invitation} →</span>
            ) : null}
          </span>
        </Link>
      </Card>
    </Reveal>
  );
}
