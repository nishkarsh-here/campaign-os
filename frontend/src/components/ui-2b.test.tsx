// @vitest-environment jsdom

/**
 * UI-2B's surfaces.
 *
 * The contracts under test are mostly about honesty: that no pin, count or AI
 * claim appears without data behind it, that absence is stated rather than
 * filled, and that a control nobody can use is not offered.
 */

import { beforeAll, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AtlasHero } from './atlas-hero';
import { BrandCore, CampaignsUsingBrand } from './brand-core';
import { LocalMarketPanel, Progress, ProvenanceStrip, provenanceNotes } from './command-center';
import { NextActionCard } from './campaign-workspace';
import { capabilitiesFor } from '@/lib/capabilities';
import { JOURNEY, resolveJourney } from '@/lib/nav';
import type { BrandBrain, CampaignOverview, CampaignSpecification, CreativeContext } from '@/lib/api';
import type { MarketGroup } from '@/lib/market';

beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

const JAIPUR: MarketGroup = {
  region: 'Jaipur, Rajasthan',
  languages: ['Hindi + English'],
  audiences: ['University students, 18–24'],
  campaignIds: ['a', 'b'],
};
const KOCHI: MarketGroup = {
  region: 'Kochi, Kerala',
  languages: ['Malayalam + English'],
  audiences: ['Young families'],
  campaignIds: ['c'],
};

function overview(over: Partial<CampaignOverview> = {}): CampaignOverview {
  return {
    campaign_id: 'c-1',
    title: 'Pause the city',
    status: 'SPECIFICATION_CONFIRMED',
    brand_name: 'Mitti & Bean',
    stages: [],
    campaign_specification_version: null,
    creative_specification_version: null,
    creative_specification_approved: false,
    latest_batch_assets: 0,
    failed_generations: 0,
    recommended_asset_id: null,
    recommended_score: null,
    recommended_reason: '',
    selected_asset_id: null,
    ranked: [],
    guardian_verdict: null,
    guardian_checked: 0,
    revision_rounds: 0,
    composed_channels: [],
    available_channels: [],
    final_assets: [],
    latest_layout_version: null,
    next_stage: null,
    next_action: null,
    ...over,
  } as unknown as CampaignOverview;
}

function spec(over: Partial<CampaignSpecification> = {}): CampaignSpecification {
  return {
    region: 'Jaipur, Rajasthan',
    language: 'Hindi + English',
    timing_occasion: 'Hot season',
    audience: 'Students',
    audience_insight: null,
    required_elements: [],
    avoid_restrictions: [],
    field_assertions: {},
    ...over,
  } as CampaignSpecification;
}

// ---------------------------------------------------------------- Atlas hero
describe('Atlas hero', () => {
  it('states the product’s proposition as the page’s one h1', () => {
    render(<AtlasHero markets={[JAIPUR]} campaignCount={3} brandCount={1} canCreate />);
    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading.textContent).toContain('local everywhere');
  });

  it('plots only markets it was given', () => {
    render(<AtlasHero markets={[JAIPUR, KOCHI]} campaignCount={3} brandCount={1} canCreate />);
    expect(screen.getByText('Jaipur, Rajasthan')).toBeDefined();
    expect(screen.getByText('Kochi, Kerala')).toBeDefined();
  });

  it('draws no pins and says why when no market is known', () => {
    // A decorative pin on a product about locality would be the most
    // dishonest thing this interface could do.
    render(<AtlasHero markets={[]} campaignCount={0} brandCount={0} canCreate />);
    expect(screen.queryByText(/Rajasthan|Kerala/)).toBeNull();
    expect(screen.getByText(/Markets appear here once a campaign brief/)).toBeDefined();
  });

  it('counts in the singular when there is one of something', () => {
    // "1 Brands" reads as a bug to everyone who sees it. The label is present
    // twice by design — once for assistive technology, once visually — so this
    // asserts the term list rather than a unique node.
    const { container } = render(
      <AtlasHero markets={[JAIPUR]} campaignCount={1} brandCount={1} canCreate />,
    );
    const terms = [...container.querySelectorAll('dt')].map((t) => t.textContent);
    expect(terms).toEqual(['Campaign', 'Brand', 'Market']);
  });

  it('counts in the plural for none or many', () => {
    const { container } = render(
      <AtlasHero markets={[JAIPUR, KOCHI]} campaignCount={0} brandCount={3} canCreate />,
    );
    const terms = [...container.querySelectorAll('dt')].map((t) => t.textContent);
    expect(terms).toEqual(['Campaigns', 'Brands', 'Markets']);
  });

  it('offers no create action to someone who cannot create', () => {
    render(<AtlasHero markets={[JAIPUR]} campaignCount={2} brandCount={1} canCreate={false} />);
    expect(screen.queryByRole('link', { name: 'Create campaign' })).toBeNull();
    // Still a way in — read-only is not a dead end.
    expect(screen.getByRole('link', { name: 'Browse campaigns' })).toBeDefined();
  });

  it('keeps the plane decorative, out of the accessibility tree', () => {
    const { container } = render(
      <AtlasHero markets={[JAIPUR]} campaignCount={1} brandCount={1} canCreate />,
    );
    expect(container.querySelector('.atlas-plane')?.closest('[aria-hidden="true"]')).toBeTruthy();
  });
});

// ------------------------------------------------------------ next decision
describe('Next action (context rail)', () => {
  // UI-2C moved the next action from a command-centre hero into the persistent
  // context rail, so it is in the same place on every stage. The contracts are
  // unchanged and follow the behaviour to its new home.
  const nodes = resolveJourney('c-1', overview({ stages: [] }));

  it('states the one thing to do, in the backend’s own words', () => {
    render(
      <NextActionCard
        campaignId="c-1"
        overview={overview({ next_stage: 'generation', next_action: 'Generate creatives from the approved plan.' })}
        nodes={nodes}
        capabilities={capabilitiesFor('marketing')}
      />,
    );
    expect(screen.getByText('Generate creatives from the approved plan.')).toBeDefined();
    expect(screen.getByRole('link', { name: /Go to generate/i })).toBeDefined();
  });

  it('says so plainly when nothing is waiting', () => {
    render(
      <NextActionCard
        campaignId="c-1"
        overview={overview()}
        nodes={nodes}
        capabilities={capabilitiesFor('admin')}
      />,
    );
    expect(screen.getByText('This campaign is complete.')).toBeDefined();
  });

  it('does not offer an approval to someone who cannot approve', () => {
    // An Approve button a person is not meant to press teaches them the
    // interface lies.
    render(
      <NextActionCard
        campaignId="c-1"
        overview={overview({ next_stage: 'creative', next_action: 'Approve the creative direction.' })}
        nodes={nodes}
        capabilities={capabilitiesFor('designer')}
      />,
    );
    expect(screen.getByText('This needs someone with approval rights.')).toBeDefined();
    expect(screen.getByRole('link', { name: /View creative/i })).toBeDefined();
  });

  it('gives a viewer a way to look without a control they cannot use', () => {
    render(
      <NextActionCard
        campaignId="c-1"
        overview={overview({ next_stage: 'generation', next_action: 'Generate creatives.' })}
        nodes={nodes}
        capabilities={capabilitiesFor('viewer')}
      />,
    );
    expect(screen.getByText('Your role is read-only for this step.')).toBeDefined();
  });

  it('lets a designer get on with work that is not an approval', () => {
    render(
      <NextActionCard
        campaignId="c-1"
        overview={overview({ next_stage: 'generation', next_action: 'Generate creatives.' })}
        nodes={nodes}
        capabilities={capabilitiesFor('designer')}
      />,
    );
    expect(screen.getByRole('link', { name: /Go to generate/i })).toBeDefined();
  });
});

// -------------------------------------------------------------- local market
describe('Local market panel', () => {
  it('answers why the campaign belongs in its market', () => {
    render(<LocalMarketPanel specification={spec()} />);
    expect(screen.getByText('Jaipur, Rajasthan')).toBeDefined();
    expect(screen.getByText('Hindi + English')).toBeDefined();
    expect(screen.getByText('Hot season')).toBeDefined();
  });

  it('says the market is undecided rather than inventing one', () => {
    render(<LocalMarketPanel specification={null} />);
    expect(screen.getByText(/no market yet/i)).toBeDefined();
    expect(screen.queryByText(/Rajasthan/)).toBeNull();
  });

  it('shows what the creative must include and must avoid', () => {
    render(
      <LocalMarketPanel
        specification={spec({
          required_elements: ['finished dish as served'],
          avoid_restrictions: ['tea gardens'],
        })}
      />,
    );
    expect(screen.getByText('Must include')).toBeDefined();
    expect(screen.getByText('finished dish as served')).toBeDefined();
    expect(screen.getByText('Must avoid')).toBeDefined();
    expect(screen.getByText('tea gardens')).toBeDefined();
  });

  it('marks a field the person stated, and explains the marker', () => {
    render(
      <LocalMarketPanel
        specification={spec({
          field_assertions: {
            region: {
              field: 'region',
              availability: 'known',
              certainty: 'stated',
              source: null,
              edited_by_human: false,
            },
          },
        })}
      />,
    );
    expect(screen.getAllByText('Stated').length).toBeGreaterThan(0);
    expect(screen.getByText('Someone told us this outright.')).toBeDefined();
  });

  it('names a missing field rather than leaving a blank', () => {
    render(<LocalMarketPanel specification={spec({ audience_insight: null })} />);
    expect(screen.getAllByText('Not known yet').length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------- provenance
describe('Provenance', () => {
  function context(over: Partial<CreativeContext> = {}): CreativeContext {
    return {
      campaign_id: 'c-1',
      brand_id: 'b-1',
      specification: spec(),
      brand_name: 'Mitti & Bean',
      guardrails: {
        palette: [],
        tone_attributes: [],
        approved_claims: [],
        prohibited_claims: [],
        visual_dos: [],
        visual_donts: [],
        logo_rules: [],
        legal_line: null,
      },
      reference_style: {} as CreativeContext['reference_style'],
      reference_analyses: [],
      preferences: {} as CreativeContext['preferences'],
      style_profile: { weights: {} },
      gaps: [],
      ...over,
    } as CreativeContext;
  }

  it('claims nothing when nothing has run', () => {
    // The failure mode this guards: a strip that says reassuring things
    // unconditionally is decoration pretending to be an audit trail.
    expect(provenanceNotes(overview(), null)).toEqual([]);
  });

  it('says "based on the Brand Brain" only when guardrails exist', () => {
    const bare = provenanceNotes(overview(), context());
    expect(bare.some((n) => /Brand Brain/.test(n.text))).toBe(false);

    const guarded = provenanceNotes(
      overview(),
      context({
        guardrails: {
          ...context().guardrails,
          prohibited_claims: ['no medical claims'],
        },
      }),
    );
    expect(guarded.some((n) => /Brand Brain/.test(n.text))).toBe(true);
  });

  it('distinguishes what a model proposed from what a person approved', () => {
    const proposed = provenanceNotes(
      overview({ creative_specification_version: 2, creative_specification_approved: false }),
      null,
    );
    const note = proposed.find((n) => /Creative plan/.test(n.text))!;
    expect(note.by).toBe('ai');
    expect(note.text).toMatch(/awaiting approval/);

    const approved = provenanceNotes(
      overview({ creative_specification_version: 2, creative_specification_approved: true }),
      null,
    );
    expect(approved.find((n) => /Creative plan/.test(n.text))!.by).toBe('human');
  });

  it('mentions the market only when the specification names one', () => {
    expect(provenanceNotes(overview(), context({ specification: spec({ region: null }) })).some((n) =>
      /Written for/.test(n.text),
    )).toBe(false);
    expect(
      provenanceNotes(overview(), context()).some((n) => /Written for Jaipur/.test(n.text)),
    ).toBe(true);
  });

  it('counts references rather than asserting it learned something', () => {
    const notes = provenanceNotes(
      overview(),
      context({ reference_analyses: [{}, {}] as CreativeContext['reference_analyses'] }),
    );
    expect(notes.some((n) => n.text === 'Style learned from 2 references')).toBe(true);
  });

  it('labels each line with who acted, in words', () => {
    render(
      <ProvenanceStrip
        notes={provenanceNotes(overview({ campaign_specification_version: 1 }), null)}
      />,
    );
    expect(screen.getByText('Person')).toBeDefined();
  });

  it('explains the emptiness instead of rendering a bare panel', () => {
    render(<ProvenanceStrip notes={[]} />);
    expect(screen.getByText(/Nothing has run yet/)).toBeDefined();
  });
});

// ------------------------------------------------------------------ progress
describe('Progress', () => {
  it('lists every stage with the backend’s own sentence', () => {
    const nodes = resolveJourney(
      'c-1',
      overview({
        stages: [{ key: 'discovery', label: 'x', state: 'DONE', detail: 'Confirmed at v1.' }],
      } as Partial<CampaignOverview>),
    );
    render(<Progress nodes={nodes} />);
    expect(screen.getByText('Confirmed at v1.')).toBeDefined();
    expect(screen.getAllByRole('listitem')).toHaveLength(JOURNEY.length);
  });

  it('calls an optional destination optional, not "not started"', () => {
    // Inspiration has endpoints and no stage row. "Not started" would imply a
    // gate that does not exist.
    render(<Progress nodes={resolveJourney('c-1', overview())} />);
    expect(screen.getAllByText('Optional').length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------- brand core
describe('Brand core', () => {
  function brain(over: Partial<BrandBrain> = {}): BrandBrain {
    return {
      brand: {
        id: 'b-1',
        name: 'Mitti & Bean',
        industry: 'Speciality coffee',
        description: null,
        website: null,
        positioning: 'A Jaipur café',
        mission: null,
        values: ['craft'],
        audience_description: null,
        voice: { tone_attributes: ['warm'], person: null, writing_rules: [], avoid: [] },
        colors: [{ name: 'Terracotta', hex: '#c54824', role: 'primary' }],
        typography: { heading_font: null, body_font: null, fallback_stack: [], notes: null },
        approved_claims: ['Roasted in Jaipur'],
        prohibited_claims: [],
        visual_dos: [],
        visual_donts: [],
        logo_rules: [],
        legal_line: null,
      },
      documents: [],
      assets: [],
      proposed_facts: [],
      field_status: [
        { field: 'positioning', knowledge: 'known', proposal_count: 0 },
        { field: 'values', knowledge: 'inferred', proposal_count: 2 },
        { field: 'logo_rules', knowledge: 'unknown', proposal_count: 0 },
      ],
      chunk_count: 0,
      knowledge_ready: false,
      processing_errors: [],
      ...over,
    } as BrandBrain;
  }

  it('separates confirmed, inferred and unknown', () => {
    // Only a person accepting a fact makes it brand truth; the page's job is
    // to make that visible rather than show one undifferentiated list. Each
    // kind appears twice — in the tally and as a group heading over its own
    // fields — so these are `getAllByText`.
    render(<BrandCore brain={brain()} />);
    expect(screen.getAllByText('Confirmed').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Inferred').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Not known').length).toBeGreaterThan(0);
    // The field names themselves, grouped under their state.
    expect(screen.getByText('positioning')).toBeDefined();
    expect(screen.getByText('values (2)')).toBeDefined();
  });

  it('describes the split without relying on the bar', () => {
    render(<BrandCore brain={brain()} />);
    expect(
      screen.getByRole('img', { name: '1 confirmed, 1 inferred, 1 not known' }),
    ).toBeDefined();
  });

  it('flags facts a person still has to decide on', () => {
    render(
      <BrandCore
        brain={brain({
          proposed_facts: [
            {
              id: 'f1',
              field: 'mission',
              value: 'x',
              confidence: 0.8,
              status: 'proposed',
              provenance: { kind: 'document', document_id: null, document_title: null, page: null, quote: null },
              rationale: null,
            },
          ],
        })}
      />,
    );
    expect(screen.getByText(/waiting for someone to accept or reject/)).toBeDefined();
  });

  it('names an empty panel rather than hiding it', () => {
    // A panel that vanishes when empty reads as a feature that does not exist.
    // Naming the gap is how a person knows to go and fill it.
    render(
      <BrandCore
        brain={brain({
          brand: {
            ...brain().brand,
            voice: { tone_attributes: [], person: null, writing_rules: [], avoid: [] },
          },
        })}
      />,
    );
    expect(screen.getByText('No tone, rules or person recorded yet.')).toBeDefined();
    // And the panel is still there, with its heading.
    expect(screen.getByRole('heading', { name: 'Voice' })).toBeDefined();
  });

  it('names a colour as well as showing it', () => {
    render(<BrandCore brain={brain()} />);
    expect(screen.getByText('Terracotta')).toBeDefined();
    expect(screen.getByText('#c54824')).toBeDefined();
  });
});

// ------------------------------------------------------- brand → campaigns
describe('Campaigns using this brand', () => {
  it('links each campaign to its command centre', () => {
    // The audit found the brand page had no route to its campaigns at all.
    render(
      <CampaignsUsingBrand
        campaigns={[{ id: 'c-1', title: 'Pause the city', status: 'SPECIFICATION_CONFIRMED' }]}
        loading={false}
      />,
    );
    const link = screen.getByRole('link', { name: /Pause the city/ });
    expect(link.getAttribute('href')).toBe('/app/campaigns/c-1/overview');
  });

  it('offers a way to start one when there are none', () => {
    render(<CampaignsUsingBrand campaigns={[]} loading={false} />);
    expect(screen.getByText(/No campaign has been written from this brand yet/)).toBeDefined();
    expect(screen.getByRole('link', { name: 'Start a campaign' })).toBeDefined();
  });

  it('shows no count while it is still loading', () => {
    // A "0 campaigns" that turns into "3 campaigns" is a wrong answer shown
    // confidently.
    render(<CampaignsUsingBrand campaigns={[]} loading />);
    expect(screen.queryByText('0 campaigns')).toBeNull();
  });
});

// ------------------------------------------------- DH-1: running is not done
describe('Next action does not report a running campaign as complete', () => {
  // Audit finding DH-1. The card read a missing `next_stage` as "complete", and
  // the backend only nominated a stage that was PENDING, ATTENTION or FAILED —
  // so a campaign mid-generation announced itself finished, with a link to
  // final assets that did not exist. The backend now nominates the first
  // unfinished stage whatever its state, and this card has to distinguish the
  // four states rather than assume a person is being asked for something.
  const nodes = resolveJourney('c-1', overview({ stages: [] }));

  function atStage(key: string, state: string, detail: string) {
    return overview({
      stages: [{ key, label: key, state, detail } as never],
      next_stage: key,
      next_action: detail,
    });
  }

  it('reports work in flight as in progress, not as complete', () => {
    render(
      <NextActionCard
        campaignId="c-1"
        overview={atStage('generation', 'RUNNING', '2 job(s) still running.')}
        nodes={nodes}
        capabilities={capabilitiesFor('admin')}
      />,
    );
    expect(screen.getByText('In progress')).toBeDefined();
    expect(screen.getByText('2 job(s) still running.')).toBeDefined();
    expect(screen.queryByText('This campaign is complete.')).toBeNull();
  });

  it('does not call running work a decision the person owes', () => {
    render(
      <NextActionCard
        campaignId="c-1"
        overview={atStage('generation', 'RUNNING', '2 job(s) still running.')}
        nodes={nodes}
        capabilities={capabilitiesFor('admin')}
      />,
    );
    expect(screen.queryByText('Your next decision')).toBeNull();
  });

  it('offers no "see the final assets" link while none exist', () => {
    // The specific dead end: the complete branch linked to Compose.
    render(
      <NextActionCard
        campaignId="c-1"
        overview={atStage('generation', 'RUNNING', '2 job(s) still running.')}
        nodes={nodes}
        capabilities={capabilitiesFor('admin')}
      />,
    );
    expect(screen.queryByRole('link', { name: 'See the final assets' })).toBeNull();
  });

  it('says a blocked stage is waiting on an earlier one', () => {
    render(
      <NextActionCard
        campaignId="c-1"
        overview={atStage('evaluation', 'BLOCKED', 'Generate creatives first.')}
        nodes={nodes}
        capabilities={capabilitiesFor('admin')}
      />,
    );
    expect(screen.getByText('Waiting on an earlier stage')).toBeDefined();
    expect(screen.queryByText('This campaign is complete.')).toBeNull();
  });

  it('marks a failed stage as needing attention rather than as a decision', () => {
    render(
      <NextActionCard
        campaignId="c-1"
        overview={atStage('generation', 'FAILED', 'Two providers failed. Retry them.')}
        nodes={nodes}
        capabilities={capabilitiesFor('admin')}
      />,
    );
    expect(screen.getByText('Needs attention')).toBeDefined();
    expect(screen.getByText('Two providers failed. Retry them.')).toBeDefined();
  });

  it('still asks for a decision when a stage is genuinely waiting on a person', () => {
    render(
      <NextActionCard
        campaignId="c-1"
        overview={atStage('creative', 'ATTENTION', 'Approve the creative direction.')}
        nodes={nodes}
        capabilities={capabilitiesFor('marketing')}
      />,
    );
    expect(screen.getByText('Your next decision')).toBeDefined();
  });

  it('still says complete when every stage really is done', () => {
    render(
      <NextActionCard
        campaignId="c-1"
        overview={overview({
          stages: [{ key: 'composition', label: 'Final asset', state: 'DONE', detail: '' } as never],
        })}
        nodes={nodes}
        capabilities={capabilitiesFor('admin')}
      />,
    );
    expect(screen.getByText('This campaign is complete.')).toBeDefined();
  });
});
