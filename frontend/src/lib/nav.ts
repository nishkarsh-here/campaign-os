/**
 * The information architecture, in one place.
 *
 * Every destination in the product is declared here: its route, its label, and
 * — for the campaign workspace — its position on the journey and what backs
 * it. Screens read this; they do not each hold their own copy of "where does
 * Generate live".
 *
 * Before UI-2A the campaign routes were linked from whichever page happened to
 * know about them, which is how the audit found stages that could be reached
 * but never returned from.
 */

import type { CampaignOverview, StageState } from '@/lib/api';

// ------------------------------------------------------------ product level

export interface Destination {
  href: string;
  label: string;
  /** Shown in the rail as a one-line explanation of what lives here. */
  hint: string;
}

/**
 * The product-level navigation.
 *
 * Three items, and the list is short for a reason: every entry here must lead
 * somewhere real.
 *
 * `Projects` is absent even though the vision document names it, because
 * `/app/projects` is not a route — only `/app/projects/:id` exists, and today
 * the project list *is* the Command Center. A nav item that 404s is worse than
 * one that is missing. It joins this list in UI-2B, when Command Center and a
 * dedicated Projects surface are separated.
 *
 * `Assets` and `Insights` are absent because no endpoint lists assets across
 * campaigns or records activity. See `docs/UI_UX_VISION.md` §12.
 */
export const PRODUCT_NAV: readonly Destination[] = [
  { href: '/app', label: 'Command Center', hint: 'Projects, and what needs you' },
  { href: '/app/campaigns', label: 'Campaigns', hint: 'Every campaign in this organization' },
  { href: '/app/brands', label: 'Brands', hint: 'Brand truth, claims and knowledge' },
] as const;

/**
 * Whether a nav item is the current one.
 *
 * Prefix matching, except for `/app` itself — `/app` prefixes every route in
 * the product, so a prefix test would light up Command Center everywhere.
 */
export function isCurrent(href: string, pathname: string | null): boolean {
  if (!pathname) return false;
  if (href === '/app') return pathname === '/app';
  return pathname === href || pathname.startsWith(`${href}/`);
}

// -------------------------------------------------------- campaign journey

/**
 * How a node on the Meridian knows its state.
 *
 * `stage` nodes read a real entry from `CampaignOverview.stages`. `optional`
 * nodes have working endpoints but no stage row — they enrich a campaign
 * rather than gate it, and showing them with a fabricated stage state would be
 * inventing backend data. The distinction is the whole reason this field
 * exists.
 */
export type NodeBacking = { kind: 'stage'; stageKey: string } | { kind: 'optional' };

export interface JourneyNode {
  /** Stable id, used for keys and for the current-node test. */
  id: string;
  /** Path segment appended to `/app/campaigns/:id`; empty string is the root. */
  segment: string;
  label: string;
  /** One sentence, in the user's words, about what happens here. */
  purpose: string;
  backing: NodeBacking;
}

/**
 * The campaign journey as the product actually runs it.
 *
 * Eight nodes. The backend has six stages (discovery, creative, generation,
 * evaluation, guardian, composition). Two destinations are `optional`: they
 * have real content and no stage row, so they are always reachable and gate
 * nothing.
 *
 * `Local Market` joined in UI-2C, when it got a route with real content behind
 * it. Until then it was deliberately absent — a node linking to a page that
 * does not exist is exactly the fake UI this redesign is under instructions not
 * to build.
 *
 * Labels are the user's words, never the schema's: "Brand check", not
 * "guardian"; "Review", not "evaluation".
 */
export const JOURNEY: readonly JourneyNode[] = [
  {
    id: 'brief',
    segment: '',
    label: 'Brief',
    purpose: 'Describe the campaign; we turn it into a specification.',
    backing: { kind: 'stage', stageKey: 'discovery' },
  },
  {
    id: 'market',
    segment: '/market',
    label: 'Local market',
    purpose: 'Why this campaign belongs where it runs.',
    // Derived, not a stage: the backend has no "market" stage. Its content is
    // read from the campaign specification, so it is always available to look
    // at and never gates anything.
    backing: { kind: 'optional' },
  },
  {
    id: 'inspiration',
    segment: '/inspiration',
    label: 'Inspiration',
    purpose: 'Add references so the creative learns your taste.',
    backing: { kind: 'optional' },
  },
  {
    id: 'creative',
    segment: '/creative',
    label: 'Creative',
    purpose: 'Three directions, then the plan for the one you pick.',
    backing: { kind: 'stage', stageKey: 'creative' },
  },
  {
    id: 'generate',
    segment: '/generate',
    label: 'Generate',
    purpose: 'Produce the visuals from the approved plan.',
    backing: { kind: 'stage', stageKey: 'generation' },
  },
  {
    id: 'review',
    segment: '/evaluate',
    label: 'Review',
    purpose: 'Score each visual against the plan and the brand.',
    backing: { kind: 'stage', stageKey: 'evaluation' },
  },
  {
    id: 'brand-check',
    segment: '/refine',
    label: 'Brand check',
    purpose: 'Check the work against brand rules, and revise it.',
    backing: { kind: 'stage', stageKey: 'guardian' },
  },
  {
    id: 'compose',
    segment: '/compose',
    label: 'Compose & export',
    purpose: 'Lay out the final asset and export per channel.',
    backing: { kind: 'stage', stageKey: 'composition' },
  },
] as const;

export function journeyHref(campaignId: string, node: JourneyNode): string {
  return `/app/campaigns/${campaignId}${node.segment}`;
}

/**
 * Which node the current path is on.
 *
 * Longest segment wins, so `/compose` is not mistaken for the root node whose
 * segment is the empty string.
 */
export function currentNodeId(campaignId: string, pathname: string | null): string | null {
  if (!pathname) return null;
  const base = `/app/campaigns/${campaignId}`;
  if (!pathname.startsWith(base)) return null;
  const rest = pathname.slice(base.length);
  let best: JourneyNode | null = null;
  for (const node of JOURNEY) {
    if (rest === node.segment || (node.segment && rest.startsWith(`${node.segment}/`))) {
      if (!best || node.segment.length > best.segment.length) best = node;
    }
  }
  return best?.id ?? null;
}

// ------------------------------------------------------------- node state

/**
 * What a node looks like on the Meridian.
 *
 * `available` is the honest answer for an optional node and for anything whose
 * state the overview has not told us — it says "you can go here" without
 * claiming progress.
 */
export type NodeState = StageState | 'available';

export interface ResolvedNode extends JourneyNode {
  state: NodeState;
  /** The backend's own sentence about this stage, where it has one. */
  detail: string | null;
  href: string;
  /** False only when the backend says the stage is blocked. */
  reachable: boolean;
}

/**
 * Resolve the journey against a campaign overview.
 *
 * A null overview — still loading, or the request failed — yields `available`
 * everywhere rather than a guess. Navigation must work before the summary
 * arrives; a rail that cannot render until a second request lands is a rail
 * that flickers on every page change.
 *
 * Note that a BLOCKED node is still a link. The backend decides what a stage
 * will accept, and a person is allowed to look at a stage that is not ready —
 * they just should not be told it is ready. Refusing navigation here is how
 * the old one-way flow happened.
 */
export function resolveJourney(
  campaignId: string,
  overview: CampaignOverview | null,
): ResolvedNode[] {
  const byKey = new Map((overview?.stages ?? []).map((s) => [s.key, s]));
  return JOURNEY.map((node) => {
    const stage = node.backing.kind === 'stage' ? byKey.get(node.backing.stageKey) : undefined;
    return {
      ...node,
      state: stage?.state ?? 'available',
      detail: stage?.detail ?? null,
      href: journeyHref(campaignId, node),
      reachable: stage?.state !== 'BLOCKED',
    };
  });
}

/** Plain-language state names. The schema's words never reach a screen. */
export const NODE_STATE_LABEL: Record<NodeState, string> = {
  DONE: 'Done',
  RUNNING: 'Working',
  ATTENTION: 'Needs you',
  FAILED: 'Failed',
  PENDING: 'Not started',
  BLOCKED: 'Blocked',
  available: 'Available',
};
