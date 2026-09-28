'use client';

/**
 * What every screen in a campaign workspace needs to know.
 *
 * Before UI-2A each of the eight campaign screens called `useWorkspace()` for
 * itself, which meant a fresh `/me` request on every stage change, its own
 * loading gate, its own error gate and its own copy of the shell. Eight screens
 * deciding independently what "loading" looks like is how they came to disagree.
 *
 * The campaign route's `layout.tsx` resolves all of it once and publishes it
 * here. Because a client-component layout is not unmounted when the child route
 * changes, moving from Creative to Generate re-renders only the page — the
 * organization, the campaign summary and the Meridian persist across the
 * navigation rather than being rebuilt.
 */

import { createContext, useContext } from 'react';
import type { ApiError, CampaignOverview, CampaignSpecification, CreativeContext, Me } from '@/lib/api';

export interface CampaignWorkspace {
  campaignId: string;
  /** The organization the caller is acting in. Never a request parameter. */
  organizationId: string | null;
  me: Me | null;
  /**
   * The campaign summary that drives the Meridian.
   *
   * Null while in flight, or when the summary request failed. Screens must
   * treat null as "not known yet", never as "nothing has happened" — the
   * difference is a campaign that looks reset when one request timed out.
   */
  overview: CampaignOverview | null;
  /**
   * The approved campaign specification, where discovery has produced one.
   *
   * Fetched best-effort for the place stamp: a campaign still in discovery has
   * no specification, and that is a normal state rather than an error.
   * Convenience view of `creativeContext.specification`.
   */
  specification: CampaignSpecification | null;
  /**
   * The assembled creative context.
   *
   * Carried in full because the command centre's provenance strip must justify
   * every claim it makes: "based on Brand Brain" is only sayable when
   * `guardrails` actually holds something, and "learned from your references"
   * only when `reference_analyses` is non-empty. A strip that asserts either
   * without checking would be exactly the invented AI narration the vision
   * document forbids.
   */
  creativeContext: CreativeContext | null;
  /**
   * Why the summary could not be read, when it could not be.
   *
   * Published rather than swallowed. UI-2A caught this failure so that
   * navigation would still render, which was right — but it left a campaign
   * that cannot be loaded showing a loading skeleton for ever, because
   * `overview` stays null and a page has no way to tell "still arriving" from
   * "will never arrive". A page must be able to distinguish those.
   */
  overviewError: ApiError | null;
  /** Re-read the summary — after an action that advances a stage. */
  refresh: () => void;
}

const Context = createContext<CampaignWorkspace | null>(null);

export const CampaignWorkspaceProvider = Context.Provider;

/**
 * Read the campaign workspace.
 *
 * Throws rather than returning null when used outside the layout. A hook that
 * silently returns nothing produces a blank screen and a long afternoon; the
 * error names the actual mistake.
 */
export function useCampaignWorkspace(): CampaignWorkspace {
  const value = useContext(Context);
  if (!value) {
    throw new Error(
      'useCampaignWorkspace must be used inside the campaign layout ' +
        '(src/app/app/campaigns/[campaignId]/layout.tsx).',
    );
  }
  return value;
}
