/**
 * The creative mapping layer.
 *
 * These pin the rules that keep the screen honest: that a field the direction
 * does not carry is never substituted from a neighbour, that agreement is not
 * presented as a difference, and that channel inheritance is resolved the way
 * the backend resolves it.
 */

import { describe, expect, it } from 'vitest';
import {
  channelPlans,
  compareDirections,
  contextStrip,
  creativeState,
  differencesOnly,
  planSections,
  toDirectionView,
} from '@/lib/creative';
import type {
  CampaignSpecification,
  CreativeDirection,
  CreativeDirectionSet,
  CreativeSpecification,
  CreativeStageView,
} from '@/lib/api';

function direction(over: Partial<CreativeDirection> = {}): CreativeDirection {
  return {
    id: 'd-1',
    campaign_id: 'c-1',
    ordinal: 1,
    title: 'Built to Spec',
    big_idea: 'Engineering confidence.',
    strategic_rationale: 'It argues from engineering rather than from price.',
    emotional_angle: 'assured',
    audience_connection: 'Architects recognise the detail.',
    key_message: 'Built to outlast.',
    headline: 'Built to outlast the building it clads',
    subhead: null,
    cta: 'Request the specification pack',
    cta_direction: 'quiet, lower right',
    visual_metaphor: 'the product held in precise detail',
    composition: 'tight orthographic framing',
    subject: 'the facade panel',
    environment: 'a fabrication floor',
    lighting: 'hard directional studio light',
    palette: ['#1c1917', '#c54824'],
    style_families: ['editorial'],
    color_direction: 'restrained metal',
    brand_integration: 'present through colour, not a badge',
    product_integration: 'the subject, not a prop',
    regional_considerations: ['Mumbai, Maharashtra'],
    negative_constraints: {} as CreativeDirection['negative_constraints'],
    reference_characteristics_used: ['raking light'],
    reference_characteristics_avoided: ['the exact poster layout'],
    distinctness_note: null,
    ...over,
  } as CreativeDirection;
}

function set(over: Partial<CreativeDirectionSet> = {}): CreativeDirectionSet {
  return {
    campaign_id: 'c-1',
    version: 1,
    directions: [direction()],
    recommended_ordinal: 1,
    recommendation_reasons: ['It answers the objective most directly.'],
    diversity: { passed: true, collisions: [], weakest_pair_similarity: 0.2 },
    revision_of_version: null,
    ...over,
  } as CreativeDirectionSet;
}

describe('a direction card', () => {
  it('numbers the routes the way a person refers to them', () => {
    const view = toDirectionView(direction({ ordinal: 2 }), set(), null);
    expect(view.number).toBe('02');
  });

  it('shows the model’s own reasoning as the reason', () => {
    // `strategic_rationale` is written for a person to read, so it is not
    // relabelled "based on campaign context".
    const view = toDirectionView(direction(), set(), null);
    expect(view.rationale).toBe('It argues from engineering rather than from price.');
  });

  it('claims no rationale when none was given', () => {
    const view = toDirectionView(direction({ strategic_rationale: '  ' }), set(), null);
    expect(view.rationale).toBeNull();
  });

  it('omits a section the direction does not fill, rather than a placeholder', () => {
    const view = toDirectionView(direction({ environment: '', lighting: '' }), set(), null);
    const labels = view.sections.map((s) => s.label);
    expect(labels).not.toContain('Setting');
    expect(labels).not.toContain('Light');
    expect(labels).toContain('Subject');
  });

  it('never surfaces a field that belongs to the later plan', () => {
    // `visual_story`, `camera` and `mood` are CreativeSpecification fields.
    // Substituting a neighbouring field under those headings would be a lie
    // told in the user's own vocabulary.
    const view = toDirectionView(direction(), set(), null);
    const labels = view.sections.map((s) => s.label.toLowerCase());
    expect(labels).not.toContain('visual story');
    expect(labels).not.toContain('camera');
    expect(labels).not.toContain('mood');
  });

  it('keeps what the references gave and what they did not', () => {
    const view = toDirectionView(direction(), set(), null);
    expect(view.referenceUsed).toEqual(['raking light']);
    expect(view.referenceAvoided).toEqual(['the exact poster layout']);
  });

  it('marks the recommended route from the set, not from the direction', () => {
    // `recommended_ordinal` is a property of the set. A direction has no
    // opinion about whether it was recommended.
    expect(toDirectionView(direction({ ordinal: 1 }), set({ recommended_ordinal: 2 }), null).recommended).toBe(false);
    expect(toDirectionView(direction({ ordinal: 2 }), set({ recommended_ordinal: 2 }), null).recommended).toBe(true);
  });

  it('marks the chosen route from the server’s record', () => {
    expect(toDirectionView(direction(), set(), 'd-1').selected).toBe(true);
    expect(toDirectionView(direction(), set(), 'd-2').selected).toBe(false);
  });
});

describe('comparing routes', () => {
  const a = direction({ id: 'a', ordinal: 1, subject: 'panel', lighting: 'hard' });
  const b = direction({ id: 'b', ordinal: 2, subject: 'people', lighting: 'hard' });

  it('puts the cells in ordinal order whatever order they arrived in', () => {
    const rows = compareDirections([b, a]);
    const subject = rows.find((r) => r.label === 'Subject')!;
    expect(subject.values).toEqual(['panel', 'people']);
  });

  it('calls a difference a difference', () => {
    const rows = compareDirections([a, b]);
    expect(rows.find((r) => r.label === 'Subject')!.differs).toBe(true);
  });

  it('does not present agreement as a difference', () => {
    const rows = compareDirections([a, b]);
    expect(rows.find((r) => r.label === 'Light')!.differs).toBe(false);
    expect(differencesOnly(rows).map((r) => r.label)).not.toContain('Light');
  });

  it('drops an axis no route fills', () => {
    const rows = compareDirections([
      direction({ id: 'a', ordinal: 1, color_direction: '' }),
      direction({ id: 'b', ordinal: 2, color_direction: '' }),
    ]);
    expect(rows.map((r) => r.label)).not.toContain('Colour');
  });

  it('leaves a route’s empty cell empty rather than borrowing its neighbour', () => {
    const rows = compareDirections([a, direction({ id: 'b', ordinal: 2, subject: '' })]);
    expect(rows.find((r) => r.label === 'Subject')!.values).toEqual(['panel', null]);
  });
});

describe('where the creative stage stands', () => {
  const view = (o: Partial<CreativeStageView>) => o as CreativeStageView;

  it('says not started before anything is generated', () => {
    expect(creativeState(view({ direction_set: null })).state).toBe('not_started');
    expect(creativeState(null).state).toBe('not_started');
  });

  it('says choosing while Gate 1 is open', () => {
    expect(creativeState(view({ direction_set: set(), gate: 'strategy_gate' })).state).toBe(
      'choosing',
    );
  });

  it('says the plan needs review at Gate 2', () => {
    expect(
      creativeState(view({ direction_set: set(), gate: 'specification_gate' })).state,
    ).toBe('planning');
  });

  it('says approved only when the server recorded it', () => {
    const s = creativeState(view({ direction_set: set(), gate: null, approved: true }));
    expect(s.state).toBe('approved');
    expect(s.label).toBe('Creative plan approved');
    // Never the enum.
    expect(s.label).not.toContain('_');
  });
});

// ------------------------------------------------------------- channel copy

function spec(over: Partial<CreativeSpecification> = {}): CreativeSpecification {
  return {
    id: 's-1',
    campaign_id: 'c-1',
    direction_id: 'd-1',
    version: 1,
    concept: 'Engineering confidence.',
    visual_story: 'The product, held in precise detail.',
    emotional_angle: 'assured',
    headline: 'Built to outlast the building it clads',
    headline_guidance: 'Plain, declarative.',
    subhead: null,
    cta: 'Request the specification pack',
    cta_guidance: 'Quiet.',
    body_copy: null,
    visual_metaphor: 'precision',
    composition: 'tight',
    focal_point: 'the joint',
    subject: 'the panel',
    environment: 'fabrication floor',
    lighting: 'hard',
    camera: null,
    palette: [],
    color_direction: 'restrained',
    style_families: [],
    mood: [],
    typography_guidance: {} as CreativeSpecification['typography_guidance'],
    product_integration: 'subject',
    people_guidance: 'none',
    brand_integration: 'colour only',
    regional_cues: [],
    negative_constraints: {} as CreativeSpecification['negative_constraints'],
    human_edited_fields: [],
    channel_copy: {},
    locked_fields: [],
    ...over,
  } as CreativeSpecification;
}

describe('what each channel says', () => {
  it('inherits the default where a channel writes nothing', () => {
    // An override is a sparse diff: absent means inherit, not "no headline".
    const [plan] = channelPlans(spec(), ['instagram_post']);
    expect(plan!.inheritsEverything).toBe(true);
    expect(plan!.lines[0]).toMatchObject({
      label: 'Headline',
      value: 'Built to outlast the building it clads',
      origin: 'default',
    });
  });

  it('uses the channel’s own words where it has them', () => {
    const [plan] = channelPlans(
      spec({ channel_copy: { linkedin: { headline: 'Specified, not substituted' } } }),
      ['linkedin'],
    );
    expect(plan!.lines[0]).toMatchObject({
      value: 'Specified, not substituted',
      origin: 'channel',
    });
    expect(plan!.inheritsEverything).toBe(false);
  });

  it('treats an explicit null as inherit, not as blank', () => {
    const [plan] = channelPlans(spec({ channel_copy: { linkedin: { headline: null } } }), [
      'linkedin',
    ]);
    expect(plan!.lines[0]!.origin).toBe('default');
  });

  it('marks the call to action locked only when the plan says it is', () => {
    // Read from the specification's own `locked_fields`, never a constant
    // copied out of the backend.
    const open = channelPlans(spec(), ['linkedin'])[0]!;
    expect(open.lines[2]!.origin).toBe('default');

    const locked = channelPlans(spec({ locked_fields: ['cta'] }), ['linkedin'])[0]!;
    expect(locked.lines[2]!.origin).toBe('locked');
  });

  it('only builds plans for channels the brief declares', () => {
    expect(channelPlans(spec(), []).length).toBe(0);
    expect(channelPlans(spec(), ['linkedin', 'instagram_story']).length).toBe(2);
  });
});

describe('the plan, grouped', () => {
  it('omits an empty field rather than printing a blank row', () => {
    const groups = planSections(spec({ subhead: null, body_copy: null }));
    expect(groups.words.map((s) => s.label)).not.toContain('Subhead');
    expect(groups.words.map((s) => s.label)).toContain('Headline');
  });

  it('marks a field a human edited', () => {
    const groups = planSections(spec({ human_edited_fields: ['headline'] }));
    expect(groups.words.find((s) => s.label === 'Headline')!.edited).toBe(true);
  });

  it('marks a locked field from the plan’s own list', () => {
    const groups = planSections(spec({ locked_fields: ['cta'] }));
    expect(groups.words.find((s) => s.label === 'Call to action')!.locked).toBe(true);
  });

  it('drops an empty list field', () => {
    const groups = planSections(spec({ mood: [], style_families: ['editorial'] }));
    const labels = groups.visual.map((s) => s.label);
    expect(labels).not.toContain('Mood');
    expect(labels).toContain('Style');
  });
});

describe('the context strip', () => {
  it('shows only the facts that exist', () => {
    const rows = contextStrip(
      {
        region: 'Mumbai',
        audience: 'Architects',
        objective: null,
      } as unknown as CampaignSpecification,
      'Northline Facades',
    );
    expect(rows.map((r) => r.label)).toEqual(['Brand', 'Market', 'Audience']);
  });

  it('is empty rather than full of dashes when nothing is known', () => {
    expect(contextStrip(null, null)).toEqual([]);
  });
});
