'use client';

/**
 * PRODUCT HOME.
 *
 * Answers three questions in order: what is this, what is waiting on me, and
 * what exists. That order matters — the screen this replaced opened with a
 * project list, which answers the third question and none of the others.
 *
 * ## Every number here is counted, not estimated
 *
 * Campaign, brand, project and market counts are the lengths of lists this page
 * actually fetched. "Waiting on you" is derived from each campaign's real
 * `status`. Markets come from real campaign specifications. Where data does not
 * exist — there is no activity log and no cross-campaign asset index — the
 * section says so instead of showing a plausible number. See
 * `docs/UI_UX_VISION.md` §12.
 */

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AppShell } from '@/components/app-shell';
import { AtlasHero } from '@/components/atlas-hero';
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  PlaceStamp,
  Reveal,
  SectionHeader,
  SkeletonRows,
  StatusBadge,
  buttonStyles,
} from '@/components/ui';
import {
  ApiError,
  api,
  type Brand,
  type Campaign,
  type CampaignSpecification,
  type Project,
} from '@/lib/api';
import { capabilitiesFor } from '@/lib/capabilities';
import { statusMeaning } from '@/lib/campaign-status';
import { groupByMarket, type MarketGroup } from '@/lib/market';
import { mapWithConcurrency } from '@/lib/concurrency';
import { useWorkspace } from '@/lib/use-workspace';

/** Enough to fill the screen without turning home into an archive. */
const RECENT_LIMIT = 5;
/** Simultaneous specification requests. See `mapWithConcurrency`. */
const SPEC_CONCURRENCY = 6;

interface Loaded {
  campaigns: Campaign[];
  brands: Brand[];
  projects: Project[];
}

export default function ProductHome() {
  const workspace = useWorkspace();
  const { organizationId } = workspace;

  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  /** Markets resolve after the lists, so they get their own state. */
  const [markets, setMarkets] = useState<MarketGroup[] | null>(null);
  const [specs, setSpecs] = useState<Map<string, CampaignSpecification | null>>(new Map());

  const load = useCallback(() => {
    if (!organizationId) return undefined;
    const controller = new AbortController();
    setData(null);
    setError(null);
    setMarkets(null);
    setSpecs(new Map());

    Promise.all([
      api.listCampaigns(organizationId, controller.signal),
      api.listBrands(organizationId, controller.signal),
      api.listProjects(organizationId, controller.signal),
    ])
      .then(async ([campaignPage, brandPage, projectPage]) => {
        if (controller.signal.aborted) return;
        setData({
          campaigns: campaignPage.items,
          brands: brandPage.items,
          projects: projectPage.items,
        });

        // Markets live on campaign specifications and there is no aggregate
        // endpoint for them, so this is a bounded fan-out. Every campaign is
        // resolved rather than the first few: a partial sweep would make the
        // per-market counts wrong, and a wrong count is worse than a slow one.
        const resolved = await mapWithConcurrency(
          campaignPage.items,
          SPEC_CONCURRENCY,
          async (campaign) => {
            const view = await api.getCreativeContext(
              campaign.id,
              organizationId,
              controller.signal,
            );
            return { campaignId: campaign.id, specification: view.context.specification };
          },
        );
        if (controller.signal.aborted) return;
        const entries = resolved.filter((r): r is NonNullable<typeof r> => r !== null);
        setSpecs(new Map(entries.map((e) => [e.campaignId, e.specification])));
        setMarkets(groupByMarket(entries));
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
      });

    return () => controller.abort();
  }, [organizationId]);

  useEffect(load, [load]);

  if (workspace.loading) {
    return (
      <div className="mx-auto max-w-page px-gutter py-10 sm:px-gutter-lg">
        <SkeletonRows rows={4} />
      </div>
    );
  }
  if (workspace.error) {
    return (
      <div className="mx-auto max-w-page px-gutter py-10 sm:px-gutter-lg">
        <ErrorState
          title="Cannot load your workspace"
          message={workspace.error.message}
          code={workspace.error.code}
          requestId={workspace.error.requestId}
          onRetry={workspace.error.isRetryable ? workspace.reload : undefined}
        />
      </div>
    );
  }

  const membership = workspace.me?.organizations.find(
    (m) => m.organization.id === organizationId,
  );
  const capabilities = capabilitiesFor(membership?.role ?? (workspace.me ? 'viewer' : null));
  const canEdit = capabilities.can('edit_campaign');

  const campaigns = data?.campaigns ?? [];
  const waiting = campaigns.filter((c) => statusMeaning(c.status).awaitsHuman);
  const recent = [...campaigns]
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, RECENT_LIMIT);

  return (
    <AppShell
      me={workspace.me}
      activeOrganizationId={organizationId}
      onOrganizationChange={workspace.setOrganizationId}
      bleed={
        <AtlasHero
          markets={markets ?? []}
          campaignCount={campaigns.length}
          brandCount={data?.brands.length ?? 0}
          canCreate={canEdit}
        />
      }
    >
      {error ? (
        <ErrorState
          title="Could not load your workspace"
          message={error.message}
          code={error.code}
          requestId={error.requestId}
          onRetry={error.isRetryable ? load : undefined}
        />
      ) : data === null ? (
        <SkeletonRows rows={4} />
      ) : (
        <div className="space-y-section">
          <WaitingOnYou campaigns={waiting} specs={specs} />
          <Markets markets={markets} />
          <RecentWork campaigns={recent} specs={specs} total={campaigns.length} />
          <Brands brands={data.brands} campaigns={campaigns} canEdit={canEdit} />
          <Projects
            projects={data.projects}
            campaigns={campaigns}
            canManage={capabilities.can('manage_workspace')}
            onCreated={load}
            organizationId={organizationId}
          />
        </div>
      )}
    </AppShell>
  );
}

// ------------------------------------------------------------ waiting on you

/**
 * The first thing on the screen after the hero, because it is the only section
 * that is about the reader rather than about the workspace.
 *
 * "Waiting" is `status`-derived and therefore honest but coarse — it sees the
 * discovery phase only. `campaign-status.ts` explains why, and the command
 * centre is where a campaign's true stage is shown.
 */
function WaitingOnYou({
  campaigns,
  specs,
}: {
  campaigns: Campaign[];
  specs: Map<string, CampaignSpecification | null>;
}) {
  if (campaigns.length === 0) return null;
  return (
    <section aria-labelledby="waiting-title">
      <SectionHeader
        title={<span id="waiting-title">Waiting on you</span>}
        description="Campaigns that cannot move until someone makes a decision."
      />
      <ul className="mt-lg space-y-3">
        {campaigns.map((campaign, i) => {
          const meaning = statusMeaning(campaign.status);
          const spec = specs.get(campaign.id);
          return (
            <Reveal as="li" key={campaign.id} index={i}>
              <Card padding={false}>
                <Link
                  href={`/app/campaigns/${campaign.id}/overview`}
                  className="flex flex-col gap-3 p-5 transition-colors duration-fast hover:bg-line/20 sm:flex-row sm:items-center sm:gap-5"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block text-h3">{campaign.title}</span>
                    <PlaceStamp
                      region={spec?.region}
                      language={spec?.language}
                      className="mt-1.5"
                    />
                  </span>
                  <StatusBadge tone={meaning.tone}>{meaning.label}</StatusBadge>
                  {meaning.invitation ? (
                    <span className="shrink-0 text-small text-accent">
                      {meaning.invitation} →
                    </span>
                  ) : null}
                </Link>
              </Card>
            </Reveal>
          );
        })}
      </ul>
    </section>
  );
}

// ------------------------------------------------------------------- markets

function Markets({ markets }: { markets: MarketGroup[] | null }) {
  return (
    <section aria-labelledby="markets-title">
      <SectionHeader
        title={<span id="markets-title">Local markets</span>}
        description="Every place a campaign in this organization has been written for."
      />
      <div className="mt-lg">
        {markets === null ? (
          // Its own loading state: the lists arrive first and the markets are
          // resolved per campaign afterwards.
          <SkeletonRows rows={2} />
        ) : markets.length === 0 ? (
          <EmptyState
            title="No markets yet"
            description="A market appears here once a campaign brief names the place it runs in — the region, the language and the season it belongs to."
          />
        ) : (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {markets.map((market, i) => (
              <Reveal as="li" key={market.region} index={i}>
                {/* A market is not a link: there is no market route to go to
                    until UI-2C builds one. A card that looks clickable and is
                    not is worse than a card that does not. */}
                <Card className="h-full">
                  <p className="text-label uppercase text-accent">Market</p>
                  <h3 className="mt-2 text-h3">{market.region}</h3>
                  <dl className="mt-4 space-y-2.5 border-t border-line pt-4">
                    {market.languages.length > 0 ? (
                      <div>
                        <dt className="text-label uppercase text-muted">Language</dt>
                        <dd className="text-small text-ink">{market.languages.join(' · ')}</dd>
                      </div>
                    ) : null}
                    {market.audiences.length > 0 ? (
                      <div>
                        <dt className="text-label uppercase text-muted">Audience</dt>
                        <dd className="line-clamp-2 text-small text-ink">
                          {market.audiences[0]}
                        </dd>
                      </div>
                    ) : null}
                    <div>
                      <dt className="text-label uppercase text-muted">Campaigns</dt>
                      {/* A counted number: the length of the campaign ids
                          grouped into this market. */}
                      <dd className="text-small tabular-nums text-ink">
                        {market.campaignIds.length}
                      </dd>
                    </div>
                  </dl>
                </Card>
              </Reveal>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

// --------------------------------------------------------------- recent work

/**
 * Recent campaigns, newest first.
 *
 * Named "Recent work" rather than "Recent activity" on purpose. There is no
 * activity or audit-event endpoint, so the product cannot say "Priya approved
 * the creative plan two hours ago". It can say which campaigns were created
 * most recently, from `created_at`, and that is what this shows.
 */
function RecentWork({
  campaigns,
  specs,
  total,
}: {
  campaigns: Campaign[];
  specs: Map<string, CampaignSpecification | null>;
  total: number;
}) {
  return (
    <section aria-labelledby="recent-title">
      <SectionHeader
        title={<span id="recent-title">Recent work</span>}
        description="The most recently created campaigns."
        actions={
          total > campaigns.length ? (
            <Link href="/app/campaigns" className="text-small text-muted hover:text-ink">
              All {total} campaigns →
            </Link>
          ) : null
        }
      />
      <div className="mt-lg">
        {campaigns.length === 0 ? (
          <EmptyState
            title="No campaigns yet"
            description="A campaign starts with a brief: what you are marketing, where, and to whom."
            action={
              <Link href="/app/campaigns" className={buttonStyles('primary', 'lg')}>
                Create campaign
              </Link>
            }
          />
        ) : (
          <Card padding={false}>
            <ul className="divide-y divide-line">
              {campaigns.map((campaign) => {
                const meaning = statusMeaning(campaign.status);
                const spec = specs.get(campaign.id);
                return (
                  <li key={campaign.id}>
                    <Link
                      href={`/app/campaigns/${campaign.id}/overview`}
                      className="flex flex-col gap-2 px-5 py-4 transition-colors duration-fast hover:bg-line/20 sm:flex-row sm:items-center sm:gap-4"
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-body font-medium">
                          {campaign.title}
                        </span>
                        <PlaceStamp
                          region={spec?.region}
                          language={spec?.language}
                          className="mt-1"
                        />
                      </span>
                      <StatusBadge tone={meaning.tone}>{meaning.label}</StatusBadge>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </Card>
        )}
      </div>
    </section>
  );
}

// -------------------------------------------------------------------- brands

function Brands({
  brands,
  campaigns,
  canEdit,
}: {
  brands: Brand[];
  campaigns: Campaign[];
  canEdit: boolean;
}) {
  return (
    <section aria-labelledby="brands-title">
      <SectionHeader
        title={<span id="brands-title">Brands</span>}
        description="The intelligence every campaign is written from."
        actions={
          <Link href="/app/brands" className="text-small text-muted hover:text-ink">
            All brands →
          </Link>
        }
      />
      <div className="mt-lg">
        {brands.length === 0 ? (
          <EmptyState
            title="No brands yet"
            description="A brand holds its identity, its documents and the knowledge campaigns retrieve from."
            action={
              canEdit ? (
                <Link href="/app/brands" className={buttonStyles('secondary', 'lg')}>
                  Add a brand
                </Link>
              ) : undefined
            }
          />
        ) : (
          <ul className="grid gap-4 sm:grid-cols-2">
            {brands.map((brand, i) => {
              // Counted from the campaign list already in hand — no extra
              // request, and no estimate.
              const used = campaigns.filter((c) => c.brand_id === brand.id).length;
              return (
                <Reveal as="li" key={brand.id} index={i}>
                  <Card padding={false} className="h-full">
                    <Link
                      href={`/app/brands/${brand.id}`}
                      className="flex h-full flex-col p-5 transition-colors duration-fast hover:bg-line/20"
                    >
                      <span className="flex items-start justify-between gap-3">
                        <span className="text-h3">{brand.name}</span>
                        {/* Swatches only when the brand has a palette. A
                            placeholder colour would be an invented brand
                            asset. */}
                        {brand.colors.length > 0 ? (
                          <span className="flex shrink-0 gap-1" aria-hidden="true">
                            {brand.colors.slice(0, 4).map((c) => (
                              <span
                                key={c.hex}
                                title={`${c.name} ${c.hex}`}
                                className="h-4 w-4 rounded-sm border border-line"
                                style={{ background: c.hex }}
                              />
                            ))}
                          </span>
                        ) : null}
                      </span>
                      {brand.positioning ? (
                        <span className="mt-2 line-clamp-2 text-small text-muted">
                          {brand.positioning}
                        </span>
                      ) : null}
                      <span className="mt-4 flex flex-wrap gap-x-5 gap-y-1 border-t border-line pt-3 text-label uppercase text-muted">
                        {brand.industry ? <span>{brand.industry}</span> : null}
                        <span>
                          {used} {used === 1 ? 'campaign' : 'campaigns'}
                        </span>
                      </span>
                    </Link>
                  </Card>
                </Reveal>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ projects

function Projects({
  projects,
  campaigns,
  canManage,
  onCreated,
  organizationId,
}: {
  projects: Project[];
  campaigns: Campaign[];
  canManage: boolean;
  onCreated: () => void;
  organizationId: string | null;
}) {
  const [name, setName] = useState('');
  const [creating, setCreating] = useState(false);
  const [failure, setFailure] = useState<ApiError | null>(null);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim() || !organizationId) return;
    setCreating(true);
    setFailure(null);
    try {
      await api.createProject(organizationId, { name: name.trim() });
      setName('');
      onCreated();
    } catch (err) {
      setFailure(err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0));
    } finally {
      setCreating(false);
    }
  }

  return (
    <section aria-labelledby="projects-title">
      <SectionHeader
        title={<span id="projects-title">Projects</span>}
        description="A project holds a brand and the campaigns you run for it."
      />

      <div className="mt-lg space-y-4">
        {failure ? <ErrorState message={failure.message} code={failure.code} /> : null}

        {projects.length === 0 ? (
          <EmptyState
            title="No projects yet"
            description="Projects group the campaigns you run for one brand or one push."
          />
        ) : (
          <ul className="grid gap-4 sm:grid-cols-2">
            {projects.map((project, i) => {
              const inProject = campaigns.filter((c) => c.project_id === project.id);
              return (
                <Reveal as="li" key={project.id} index={i}>
                  <Card padding={false} className="h-full">
                    <Link
                      href={`/app/projects/${project.id}`}
                      className="flex h-full flex-col p-5 transition-colors duration-fast hover:bg-line/20"
                    >
                      <span className="text-h3">{project.name}</span>
                      {project.description ? (
                        <span className="mt-2 line-clamp-2 text-small text-muted">
                          {project.description}
                        </span>
                      ) : null}
                      <span className="mt-4 border-t border-line pt-3 text-label uppercase text-muted">
                        {inProject.length}{' '}
                        {inProject.length === 1 ? 'campaign' : 'campaigns'}
                      </span>
                    </Link>
                  </Card>
                </Reveal>
              );
            })}
          </ul>
        )}

        {/* Creating a project is an admin affordance. A viewer or an editor
            sees the projects and not the form — presentation only; the
            endpoint does not yet check. */}
        {canManage ? (
          <Card>
            <form onSubmit={create} className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <Field label="New project" className="flex-1">
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Monsoon launch"
                />
              </Field>
              <Button type="submit" variant="primary" size="lg" disabled={creating || !name.trim()}>
                {creating ? 'Creating…' : 'Create project'}
              </Button>
            </form>
          </Card>
        ) : null}
      </div>
    </section>
  );
}
