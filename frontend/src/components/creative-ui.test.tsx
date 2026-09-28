// @vitest-environment jsdom

/**
 * The creative screens.
 *
 * Behaviour and governance contracts: that the three routes render as concepts,
 * that a control nobody can use is not offered, that compare mode is reachable
 * and reversible, and that the approval moment says what it commits.
 */

import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { CreativeDirections } from './creative-directions';
import { CreativePlan } from './creative-plan';
import { capabilitiesFor } from '@/lib/capabilities';
import type {
  CampaignSpecification,
  CreativeDirection,
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
    cta_direction: 'quiet',
    visual_metaphor: 'precision',
    composition: 'tight',
    subject: 'the panel',
    environment: 'a fabrication floor',
    lighting: 'hard light',
    palette: ['#1c1917'],
    style_families: ['editorial'],
    color_direction: 'restrained',
    brand_integration: 'colour, not a badge',
    product_integration: 'the subject',
    regional_considerations: ['Mumbai, Maharashtra'],
    negative_constraints: {} as CreativeDirection['negative_constraints'],
    reference_characteristics_used: ['raking light'],
    reference_characteristics_avoided: ['the exact poster layout'],
    distinctness_note: null,
    ...over,
  } as CreativeDirection;
}

function stage(over: Partial<CreativeStageView> = {}): CreativeStageView {
  return {
    campaign_id: 'c-1',
    gate: 'strategy_gate',
    direction_set: {
      campaign_id: 'c-1',
      version: 1,
      directions: [
        direction(),
        direction({ id: 'd-2', ordinal: 2, title: 'Lived In', subject: 'people' }),
        direction({ id: 'd-3', ordinal: 3, title: 'Against the Sky', subject: 'skyline' }),
      ],
      recommended_ordinal: 1,
      recommendation_reasons: ['It answers the objective most directly.'],
      diversity: { passed: true, collisions: [], weakest_pair_similarity: 0.2 },
      revision_of_version: null,
    },
    selected_direction_id: null,
    specification: null,
    diversity: { passed: true, collisions: [], weakest_pair_similarity: 0.2 },
    approved: false,
    gaps: [],
    channels: ['instagram_post'],
    ...over,
  } as CreativeStageView;
}

const campaignSpec = {
  region: 'Mumbai, Maharashtra',
  audience: 'Architects',
  objective: 'Get FS-9 specified at design stage',
} as CampaignSpecification;

function renderDirections(over: Partial<Parameters<typeof CreativeDirections>[0]> = {}) {
  const props = {
    view: stage(),
    campaignSpecification: campaignSpec,
    brandName: 'Northline Facades',
    capabilities: capabilitiesFor('admin'),
    busy: false,
    gateOpen: true,
    onChoose: vi.fn(),
    onRequestChanges: vi.fn(),
    ...over,
  };
  return { ...render(<CreativeDirections {...props} />), props };
}

describe('Creative directions', () => {
  it('presents three routes as concepts, each with a name', () => {
    renderDirections();
    expect(screen.getByRole('heading', { name: /Built to Spec/ })).toBeDefined();
    expect(screen.getByRole('heading', { name: /Lived In/ })).toBeDefined();
    expect(screen.getByRole('heading', { name: /Against the Sky/ })).toBeDefined();
  });

  it('states the campaign context from real values only', () => {
    renderDirections();
    // Appears in the context strip and again in "carried forward".
    expect(screen.getAllByText('Northline Facades').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Mumbai, Maharashtra').length).toBeGreaterThan(0);
    expect(screen.queryByText('—')).toBeNull();
  });

  it('shows the model’s own reason for a route', () => {
    renderDirections();
    expect(screen.getAllByText(/argues from engineering/).length).toBeGreaterThan(0);
  });

  it('does not show fields that belong to the later plan', () => {
    // visual_story / camera / mood are CreativeSpecification fields.
    const { container } = renderDirections();
    const text = (container.textContent ?? '').toLowerCase();
    expect(text).not.toContain('visual story');
    expect(text).not.toContain('camera');
  });

  it('labels the palette as a stated palette, not as artwork', () => {
    renderDirections();
    expect(screen.getAllByText('Palette this route names').length).toBe(3);
    expect(screen.getAllByRole('img', { name: /^Palette:/ }).length).toBe(3);
  });

  it('marks the recommended route without hiding the choice', () => {
    renderDirections();
    expect(screen.getByText('Put forward')).toBeDefined();
    expect(screen.getByText(/you do not have to agree/)).toBeDefined();
  });

  it('lets an approver choose a route', () => {
    const { props } = renderDirections();
    fireEvent.click(screen.getByRole('button', { name: 'Choose direction 02' }));
    expect(props.onChoose).toHaveBeenCalledWith('d-2');
  });

  it('offers no choice to someone without approval rights', () => {
    renderDirections({ capabilities: capabilitiesFor('designer') });
    expect(screen.queryByRole('button', { name: /Choose direction/ })).toBeNull();
    expect(screen.getAllByText(/needs approval rights/).length).toBeGreaterThan(0);
  });

  it('keeps the routes readable after the gate closes, without a dead control', () => {
    // The set still holds all three; a person should be able to read back what
    // was chosen and what it was chosen over.
    renderDirections({
      gateOpen: false,
      view: stage({ gate: null, selected_direction_id: 'd-2' }),
    });
    expect(screen.getByRole('heading', { name: /Lived In/ })).toBeDefined();
    expect(screen.queryByRole('button', { name: /Choose direction/ })).toBeNull();
    expect(screen.getByText(/Chosen — the plan is built from this/i)).toBeDefined();
    // The two routes that were not chosen.
    expect(screen.getAllByText('Not chosen')).toHaveLength(2);
  });

  it('enters and leaves compare mode', () => {
    renderDirections();
    const toggle = screen.getByRole('button', { name: 'Compare all three' });
    expect(toggle.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(toggle);

    expect(screen.getByRole('heading', { name: /Different because/ })).toBeDefined();
    const back = screen.getByRole('button', { name: 'Back to the routes' });
    expect(back.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(back);
    expect(screen.getByRole('button', { name: 'Compare all three' })).toBeDefined();
  });

  it('separates what differs from what the routes share', () => {
    renderDirections();
    fireEvent.click(screen.getByRole('button', { name: 'Compare all three' }));
    expect(screen.getByRole('heading', { name: /Different because/ })).toBeDefined();
    // Light is identical across all three fixtures, so it is shared, not a
    // difference.
    const shared = screen.getByRole('heading', { name: 'What they all share' }).closest('section')!;
    // One cell per route, all saying the same thing — which is what makes it
    // shared rather than a difference.
    expect(within(shared).getAllByText('hard light')).toHaveLength(3);
  });

  it('says what the choice commits, before it is made', () => {
    renderDirections();
    expect(screen.getByText(/choosing the concept that guides the rest/i)).toBeDefined();
    expect(screen.getByText('Carried forward whichever you choose')).toBeDefined();
  });

  it('captures a reason when changes are requested', () => {
    const { props } = renderDirections();
    fireEvent.click(screen.getByRole('button', { name: /None of these work/ }));
    fireEvent.change(screen.getByLabelText('What needs to change?'), {
      target: { value: 'Too corporate.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Ask for another set' }));
    expect(props.onRequestChanges).toHaveBeenCalledWith('Too corporate.');
  });

  it('will not send an empty change request', () => {
    renderDirections();
    fireEvent.click(screen.getByRole('button', { name: /None of these work/ }));
    const send = screen.getByRole('button', { name: 'Ask for another set' });
    expect((send as HTMLButtonElement).disabled).toBe(true);
  });

  it('says so when the routes are too alike', () => {
    renderDirections({
      view: stage({
        diversity: { passed: false, collisions: [[1, 2, 0.9]], weakest_pair_similarity: 0.9 },
      }),
    });
    expect(screen.getByText('These routes overlap')).toBeDefined();
  });

  it('explains an empty set rather than showing a blank panel', () => {
    renderDirections({ view: stage({ direction_set: null }) });
    expect(screen.getByText('No creative routes yet')).toBeDefined();
  });
});

// ----------------------------------------------------------------- the plan

function spec(over: Partial<CreativeSpecification> = {}): CreativeSpecification {
  return {
    id: 's-1',
    campaign_id: 'c-1',
    direction_id: 'd-1',
    version: 2,
    concept: 'Engineering confidence.',
    visual_story: 'The product, held in precise detail.',
    emotional_angle: 'assured',
    headline: 'Built to outlast the building it clads',
    headline_guidance: 'Plain.',
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

function renderPlan(over: Partial<Parameters<typeof CreativePlan>[0]> = {}) {
  const props = {
    specification: spec(),
    declaredChannels: ['instagram_post', 'linkedin'] as const,
    approved: false,
    gateOpen: true,
    capabilities: capabilitiesFor('admin'),
    busy: false,
    onApprove: vi.fn(),
    onRequestChanges: vi.fn(),
    ...over,
  };
  return { ...render(<CreativePlan {...props} />), props };
}

describe('Creative plan', () => {
  it('is called the Creative plan, never the schema’s name', () => {
    const { container } = renderPlan();
    expect(screen.getByRole('heading', { name: 'Creative plan' })).toBeDefined();
    expect(container.textContent).not.toContain('Creative Specification');
  });

  it('translates the approval state instead of showing the enum', () => {
    renderPlan({ approved: true });
    expect(screen.getByText('Creative plan approved')).toBeDefined();
  });

  it('shows the plan grouped the way a brief is read', () => {
    renderPlan();
    expect(screen.getByRole('heading', { name: 'The idea' })).toBeDefined();
    expect(screen.getByRole('heading', { name: 'The words' })).toBeDefined();
    expect(screen.getByRole('heading', { name: 'The picture' })).toBeDefined();
  });

  it('shows each channel’s words and where they came from', () => {
    renderPlan();
    expect(screen.getByRole('heading', { name: 'Instagram post' })).toBeDefined();
    expect(screen.getAllByText('Uses campaign default').length).toBeGreaterThan(0);
  });

  it('marks a channel that was written for specifically', () => {
    renderPlan({
      specification: spec({ channel_copy: { linkedin: { headline: 'Specified, not substituted' } } }),
    });
    expect(screen.getByText('Specified, not substituted')).toBeDefined();
    expect(screen.getByText('Written for this channel')).toBeDefined();
    expect(screen.getByText('Tailored')).toBeDefined();
  });

  it('says a channel inherits rather than implying it has no words', () => {
    renderPlan();
    expect(screen.getAllByText('Inherits').length).toBe(2);
  });

  it('explains what approving commits', () => {
    renderPlan();
    expect(screen.getByText(/Approving locks the plan and opens generation/)).toBeDefined();
  });

  it('lets an approver approve', () => {
    const { props } = renderPlan();
    fireEvent.click(screen.getByRole('button', { name: 'Approve the creative plan' }));
    expect(props.onApprove).toHaveBeenCalledOnce();
  });

  it('offers a designer changes but not approval', () => {
    renderPlan({ capabilities: capabilitiesFor('designer') });
    expect(screen.queryByRole('button', { name: 'Approve the creative plan' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Request changes' })).toBeDefined();
  });

  it('gives a viewer neither', () => {
    renderPlan({ capabilities: capabilitiesFor('viewer') });
    expect(screen.queryByRole('button', { name: 'Approve the creative plan' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Request changes' })).toBeNull();
  });

  it('does not offer a decision when the gate is shut', () => {
    renderPlan({ gateOpen: false });
    expect(screen.getByText('Not open for a decision')).toBeDefined();
    expect(screen.queryByRole('button', { name: 'Approve the creative plan' })).toBeNull();
  });

  it('marks a field a person edited and one that is locked', () => {
    renderPlan({ specification: spec({ human_edited_fields: ['headline'], locked_fields: ['cta'] }) });
    expect(screen.getByText('Edited by a person')).toBeDefined();
    expect(screen.getByText('Locked')).toBeDefined();
  });
});
