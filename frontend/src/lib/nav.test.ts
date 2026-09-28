/**
 * The information architecture's contracts.
 *
 * These pin the rules that are easy to break and hard to notice: that current
 * matching does not light up every page at once, that the longest route segment
 * wins, that a stage's state comes from the backend and is never invented, and
 * that navigation still works when the summary request has not landed.
 */

import { describe, expect, it } from 'vitest';
import {
  JOURNEY,
  NODE_STATE_LABEL,
  PRODUCT_NAV,
  currentNodeId,
  isCurrent,
  journeyHref,
  resolveJourney,
} from '@/lib/nav';
import type { CampaignOverview, StageStateView } from '@/lib/api';

const CAMPAIGN = 'c-1';

function overview(stages: Partial<StageStateView>[]): CampaignOverview {
  return {
    stages: stages.map((s) => ({
      key: s.key ?? 'discovery',
      label: s.label ?? 'Stage',
      state: s.state ?? 'PENDING',
      detail: s.detail ?? '',
    })),
  } as CampaignOverview;
}

describe('product navigation', () => {
  it('leads only to routes that exist', () => {
    // The regression this guards: `/app/projects` was listed for a route that
    // was never built, so the primary navigation contained a 404.
    const ROUTES = new Set(['/app', '/app/campaigns', '/app/brands']);
    for (const item of PRODUCT_NAV) expect(ROUTES.has(item.href)).toBe(true);
  });

  it('does not mark the workspace current on every page', () => {
    // `/app` prefixes every route in the product, so a prefix test would light
    // up Command Center everywhere.
    expect(isCurrent('/app', '/app')).toBe(true);
    expect(isCurrent('/app', '/app/brands')).toBe(false);
    expect(isCurrent('/app', '/app/campaigns/c-1/creative')).toBe(false);
  });

  it('marks a section current for its own subtree', () => {
    expect(isCurrent('/app/brands', '/app/brands')).toBe(true);
    expect(isCurrent('/app/brands', '/app/brands/b-1')).toBe(true);
    expect(isCurrent('/app/brands', '/app/campaigns')).toBe(false);
  });

  it('claims nothing when there is no path yet', () => {
    expect(isCurrent('/app', null)).toBe(false);
  });
});

describe('the campaign journey', () => {
  it('uses the user’s words, never the schema’s', () => {
    // "guardian" and "evaluation" are implementation names. A label that leaks
    // one is the failure this asserts against.
    const labels = JOURNEY.map((n) => n.label.toLowerCase());
    for (const internal of ['guardian', 'evaluation', 'discovery', 'composition']) {
      expect(labels).not.toContain(internal);
    }
  });

  it('gives every node a unique id and route', () => {
    expect(new Set(JOURNEY.map((n) => n.id)).size).toBe(JOURNEY.length);
    expect(new Set(JOURNEY.map((n) => n.segment)).size).toBe(JOURNEY.length);
  });

  it('names a real backend stage wherever it claims one', () => {
    // The six stages `app/services/overview.py` emits. A node claiming a
    // seventh would render a state no service computes.
    const STAGES = new Set([
      'discovery',
      'creative',
      'generation',
      'evaluation',
      'guardian',
      'composition',
    ]);
    for (const node of JOURNEY) {
      if (node.backing.kind === 'stage') expect(STAGES.has(node.backing.stageKey)).toBe(true);
    }
  });

  it('marks Inspiration optional rather than inventing a stage for it', () => {
    // Inspiration has real endpoints and no entry in `CampaignOverview.stages`.
    const node = JOURNEY.find((n) => n.id === 'inspiration');
    expect(node?.backing.kind).toBe('optional');
  });

  it('builds routes under the campaign', () => {
    expect(journeyHref(CAMPAIGN, JOURNEY[0]!)).toBe('/app/campaigns/c-1');
    const compose = JOURNEY.find((n) => n.id === 'compose')!;
    expect(journeyHref(CAMPAIGN, compose)).toBe('/app/campaigns/c-1/compose');
  });
});

describe('locating the current node', () => {
  it('prefers the longest matching segment over the root', () => {
    // The root node's segment is the empty string, which every path starts
    // with. Without longest-match, every stage would report as the brief.
    expect(currentNodeId(CAMPAIGN, '/app/campaigns/c-1/compose')).toBe('compose');
    expect(currentNodeId(CAMPAIGN, '/app/campaigns/c-1/creative')).toBe('creative');
    expect(currentNodeId(CAMPAIGN, '/app/campaigns/c-1')).toBe('brief');
  });

  it('maps the user-facing label back to its real route', () => {
    // "Review" lives at /evaluate and "Brand check" at /refine — the rename is
    // presentational and must not move the route.
    expect(currentNodeId(CAMPAIGN, '/app/campaigns/c-1/evaluate')).toBe('review');
    expect(currentNodeId(CAMPAIGN, '/app/campaigns/c-1/refine')).toBe('brand-check');
  });

  it('reports nothing for another campaign or another section', () => {
    expect(currentNodeId(CAMPAIGN, '/app/campaigns/c-2/creative')).toBeNull();
    expect(currentNodeId(CAMPAIGN, '/app/brands')).toBeNull();
    expect(currentNodeId(CAMPAIGN, null)).toBeNull();
  });
});

describe('resolving the journey', () => {
  it('takes each stage state from the backend', () => {
    const nodes = resolveJourney(
      CAMPAIGN,
      overview([
        { key: 'discovery', state: 'DONE', detail: 'Confirmed at v1.' },
        { key: 'generation', state: 'BLOCKED' },
      ]),
    );
    const byId = new Map(nodes.map((n) => [n.id, n]));
    expect(byId.get('brief')?.state).toBe('DONE');
    expect(byId.get('brief')?.detail).toBe('Confirmed at v1.');
    expect(byId.get('generate')?.state).toBe('BLOCKED');
  });

  it('says "available" rather than guessing when the summary has not arrived', () => {
    // Navigation must render on first paint. A rail that waits for a second
    // request is a rail that flickers on every page change — and a rail that
    // defaulted to PENDING would claim a campaign had not started.
    const nodes = resolveJourney(CAMPAIGN, null);
    expect(nodes).toHaveLength(JOURNEY.length);
    for (const node of nodes) expect(node.state).toBe('available');
  });

  it('leaves an optional node alone even when a stage shares its name', () => {
    const nodes = resolveJourney(CAMPAIGN, overview([{ key: 'inspiration', state: 'DONE' }]));
    expect(nodes.find((n) => n.id === 'inspiration')?.state).toBe('available');
  });

  it('keeps a blocked stage navigable', () => {
    // A person may look at a stage that is not ready. The backend decides what
    // it will accept; refusing navigation here is how one-way flow happens.
    const nodes = resolveJourney(CAMPAIGN, overview([{ key: 'composition', state: 'BLOCKED' }]));
    const compose = nodes.find((n) => n.id === 'compose')!;
    expect(compose.reachable).toBe(false);
    expect(compose.href).toBe('/app/campaigns/c-1/compose');
  });

  it('has a plain-language label for every state it can render', () => {
    const nodes = resolveJourney(CAMPAIGN, overview([{ key: 'discovery', state: 'ATTENTION' }]));
    for (const node of nodes) expect(NODE_STATE_LABEL[node.state]).toBeTruthy();
    expect(NODE_STATE_LABEL.ATTENTION).toBe('Needs you');
  });
});
