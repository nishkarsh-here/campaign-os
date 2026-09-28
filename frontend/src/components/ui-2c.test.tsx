// @vitest-environment jsdom

/**
 * UI-2C's surfaces.
 *
 * The contracts here are mostly about what the screen refuses to claim: that a
 * confirmed brief is shown rather than skipped, that "not applicable" is not
 * reported as "still needed", that only the field being asked is highlighted,
 * and that a reference's refusals are shown beside its takeaways.
 */

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CampaignSnapshot, fromInputs, fromSpecification } from './campaign-snapshot';
import { ReferenceCard } from './reference-moodboard';
import type {
  CampaignInputs,
  CampaignReference,
  CampaignSpecification,
  FieldAssertion,
} from '@/lib/api';

function assertion(over: Partial<FieldAssertion> = {}): FieldAssertion {
  return {
    field: 'x',
    availability: 'known',
    certainty: 'stated',
    source: null,
    edited_by_human: false,
    ...over,
  };
}

function inputs(over: Partial<CampaignInputs> = {}): CampaignInputs {
  return {
    campaign_objective: 'Defend share in Assam',
    target_audience: 'Family grocery buyers',
    product: null,
    key_message: null,
    region: 'Assam',
    channels: [],
    cta: null,
    desired_emotional_response: null,
    campaign_tone: [],
    key_offer: null,
    timing_occasion: null,
    required_elements: [],
    avoid_restrictions: [],
    assertions: {},
    ...over,
  } as CampaignInputs;
}

function specification(over: Partial<CampaignSpecification> = {}): CampaignSpecification {
  return {
    objective: 'Defend share in Assam',
    audience: 'Family grocery buyers',
    product: 'Ghoroa Masala',
    key_message: 'The taste your kitchen already knows.',
    cta: 'Ask for Ghoroa',
    key_offer: null,
    region: 'Assam',
    timing_occasion: 'Rongali Bihu',
    campaign_tone: ['warm'],
    tone: [],
    channels: ['instagram_post'],
    required_elements: [],
    avoid_restrictions: [],
    field_assertions: {},
    ...over,
  } as CampaignSpecification;
}

describe('Campaign snapshot', () => {
  it('shows the brief a confirmed campaign already has', () => {
    // The bug this pins: a confirmed campaign gets a 409 from
    // /discovery/start, so there is no DiscoveryTurn — and the screen used to
    // render a permanent skeleton, leaving the brief the whole pipeline is
    // built from invisible on its own page. Every seeded campaign is in this
    // state.
    render(<CampaignSnapshot brief={fromSpecification(specification())} complete confirmed />);
    expect(screen.getByText('Defend share in Assam')).toBeDefined();
    expect(screen.getByText('Ghoroa Masala')).toBeDefined();
    expect(screen.getByText('Confirmed')).toBeDefined();
  });

  it('counts what is still needed rather than a percentage', () => {
    // "Three things still needed" tells you what to do. "62% complete" does
    // not.
    render(<CampaignSnapshot brief={fromInputs(inputs())} complete={false} />);
    expect(screen.getByText(/still needed$/)).toBeDefined();
  });

  it('does not report an answered "not applicable" as missing', () => {
    // Someone said it does not apply. Asking again for ever is the failure.
    render(
      <CampaignSnapshot
        brief={fromInputs(
          inputs({ assertions: { key_offer: assertion({ availability: 'not_applicable' }) } }),
        )}
        complete={false}
      />,
    );
    expect(screen.getByText('Not applicable')).toBeDefined();
  });

  it('highlights only the field being asked, not every outstanding one', () => {
    // `missing` is every remaining open field; the question is one field.
    // Driving the accent from `missing` lights the whole column.
    render(
      <CampaignSnapshot
        brief={fromInputs(inputs())}
        missing={['product', 'cta', 'key_message']}
        asking="product"
        complete={false}
      />,
    );
    expect(screen.getByText('Being asked now')).toBeDefined();
    expect(screen.getAllByText('Still needed').length).toBeGreaterThan(0);
  });

  it('reads provenance under either field vocabulary', () => {
    // `field_assertions` genuinely mixes both: a real specification carries
    // `campaign_objective` *and* `audience`. A single-name lookup silently
    // finds nothing for half the rows.
    render(
      <CampaignSnapshot
        brief={fromSpecification(
          specification({
            field_assertions: {
              campaign_objective: assertion({ certainty: 'stated' }),
              audience: assertion({ certainty: 'inferred' }),
            },
          }),
        )}
        complete
      />,
    );
    expect(screen.getByText('Provided by you')).toBeDefined();
    expect(screen.getByText('AI inferred')).toBeDefined();
  });

  it('marks a field a human edited, because that survives recompilation', () => {
    render(
      <CampaignSnapshot
        brief={fromSpecification(
          specification({ field_assertions: { region: assertion({ edited_by_human: true }) } }),
        )}
        complete
      />,
    );
    expect(screen.getByText('Edited by you')).toBeDefined();
  });
});

// ------------------------------------------------------------------ moodboard

function reference(over: Partial<CampaignReference> = {}): CampaignReference {
  return {
    id: 'r-1',
    filename: 'poster.jpg',
    mime_type: 'image/jpeg',
    bytes: 100,
    note: 'Warm evening market',
    url: '/media/r-1',
    status: 'COMPLETED',
    accepted: false,
    error: null,
    analysis: {
      reference_id: 'r-1',
      style_families: ['editorial'],
      composition: 'centred subject',
      lighting: 'warm low sun',
      imagery_style: [],
      color: {
        dominant_palette: ['#c54824'],
        brightness: 0.5,
        saturation: 0.5,
        contrast: 0.5,
        temperature: 'warm',
      },
      typography: {
        scale: null,
        weight: null,
        classification: null,
        case: null,
        text_density: null,
      },
      layout: { image_text_balance: null, subject_placement: 'lower third', hierarchy: null },
      visual_density: 'sparse',
      mood: ['calm'],
      subject_treatment: null,
      style_takeaways: ['Warm low light on the product'],
      not_transferable: ['The specific poster layout'],
      confidence: 0.8,
      summary: 'A warm, sparse market scene.',
    },
    ...over,
  } as CampaignReference;
}

describe('Reference card', () => {
  it('shows what it learned beside what it refuses to reuse', () => {
    // ADR-011 made checkable: "learn the style, never copy the design" is a
    // promise until the refusal is on screen next to the takeaway.
    render(<ReferenceCard reference={reference()} index={0} canEdit busy={false} />);
    expect(screen.getByText('Warm low light on the product')).toBeDefined();
    expect(screen.getByText('Deliberately not reused')).toBeDefined();
    expect(screen.getByText('The specific poster layout')).toBeDefined();
  });

  it('draws only the characteristics the analysis actually returned', () => {
    // Texture and Depth have no field in ReferenceAnalysis. A chip reading
    // "Soft texture" that no model produced is a fabricated observation about
    // someone else's artwork.
    const { container } = render(
      <ReferenceCard reference={reference()} index={0} canEdit busy={false} />,
    );
    const text = container.textContent ?? '';
    expect(text).toContain('Composition');
    expect(text).toContain('Lighting');
    expect(text).not.toContain('Texture');
    expect(text).not.toContain('Depth');
  });

  it('names a palette colour as well as showing it', () => {
    render(<ReferenceCard reference={reference()} index={0} canEdit busy={false} />);
    expect(screen.getByText('#c54824')).toBeDefined();
  });

  it('offers no undo for an accepted reference, because the API has none', () => {
    const onAccept = vi.fn();
    render(
      <ReferenceCard
        reference={reference({ accepted: true })}
        index={0}
        canEdit
        busy={false}
        onAccept={onAccept}
      />,
    );
    expect(screen.getByText('In the mix')).toBeDefined();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('tells a viewer why they cannot add a reference', () => {
    render(
      <ReferenceCard
        reference={reference()}
        index={0}
        canEdit={false}
        busy={false}
        onAccept={() => {}}
      />,
    );
    expect(screen.getByText(/read-only for references/)).toBeDefined();
  });

  it('reports a reference that could not be read', () => {
    render(
      <ReferenceCard
        reference={reference({ status: 'FAILED', analysis: null, error: 'Unsupported file.' })}
        index={0}
        canEdit
        busy={false}
      />,
    );
    expect(screen.getByRole('alert').textContent).toContain('Unsupported file.');
  });

  it('describes the reference image for someone who cannot see it', () => {
    render(<ReferenceCard reference={reference()} index={0} canEdit busy={false} />);
    expect(screen.getByAltText('Reference: Warm evening market')).toBeDefined();
  });
});
