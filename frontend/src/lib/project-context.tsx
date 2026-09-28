'use client';

/**
 * Project scope.
 *
 * The audit's finding was that a project is a *page* rather than a scope: you
 * opened it, saw a list, clicked into a campaign and the project was gone. This
 * makes it a scope the way UI-2A made the campaign one — resolved once in a
 * route layout and published here, so the header can state which project you
 * are in on every screen beneath it.
 *
 * What a project knows about itself is thin, and honestly so. `Project` returns
 * id, organization, name and description; it has no brand, no market and no
 * campaign count. Everything richer here is *derived* from the organization's
 * campaign list filtered by `project_id` — real data, computed in the browser,
 * never a number the API was asked for and did not give.
 */

import { createContext, useContext } from 'react';
import type { Brand, Campaign, CampaignSpecification, Project } from '@/lib/api';
import type { MarketGroup } from '@/lib/market';

export interface ProjectScope {
  projectId: string;
  organizationId: string | null;
  project: Project | null;
  /** The organization's campaigns filtered to this project. */
  campaigns: Campaign[];
  /** Brands those campaigns use — a project has no brand of its own. */
  brands: Brand[];
  /** Markets derived from those campaigns' specifications. */
  markets: MarketGroup[];
  specs: Map<string, CampaignSpecification | null>;
  /** Null while the derived data is still resolving. */
  resolving: boolean;
  refresh: () => void;
}

const Context = createContext<ProjectScope | null>(null);

export const ProjectScopeProvider = Context.Provider;

export function useProjectScope(): ProjectScope {
  const value = useContext(Context);
  if (!value) {
    throw new Error(
      'useProjectScope must be used inside the project layout ' +
        '(src/app/app/projects/[projectId]/layout.tsx).',
    );
  }
  return value;
}
