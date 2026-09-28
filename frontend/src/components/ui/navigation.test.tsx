// @vitest-environment jsdom

/**
 * The Meridian and the place stamp.
 *
 * The Meridian replaces browser-back as the way around a campaign, so its
 * accessibility contract is load-bearing rather than cosmetic: the order has to
 * be real, the current step has to be announced, every state has to exist in
 * words, and a blocked stage still has to be reachable.
 */

import { beforeAll, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Meridian } from './meridian';
import { PlaceStamp } from './place-stamp';
import { JOURNEY, resolveJourney } from '@/lib/nav';
import type { CampaignOverview } from '@/lib/api';

beforeAll(() => {
  // jsdom has no layout, so it implements neither of these. The Meridian uses
  // scrollIntoView to keep the current node visible on a phone.
  Element.prototype.scrollIntoView = vi.fn();
});

function nodes(stages: { key: string; state: string }[] = []) {
  return resolveJourney('c-1', { stages } as unknown as CampaignOverview);
}

describe('Meridian', () => {
  it('is a landmark with a name, not an anonymous row of links', () => {
    render(<Meridian nodes={nodes()} currentId="brief" />);
    expect(screen.getByRole('navigation', { name: 'Campaign stages' })).toBeDefined();
  });

  it('presents the journey as an ordered list, because the order is meaning', () => {
    render(<Meridian nodes={nodes()} currentId="brief" />);
    // Against `JOURNEY.length`, not a literal: the journey gained a Local
    // Market node in UI-2C and will grow again. What must hold is that every
    // declared node is rendered, in order.
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(JOURNEY.length);
    expect(items[0]!.textContent).toContain('Brief');
    expect(items[items.length - 1]!.textContent).toContain('Compose & export');
  });

  it('announces which step you are on', () => {
    render(<Meridian nodes={nodes()} currentId="generate" />);
    const current = screen.getByRole('link', { name: /Generate/ });
    expect(current.getAttribute('aria-current')).toBe('step');
  });

  it('marks exactly one step current', () => {
    render(<Meridian nodes={nodes()} currentId="creative" />);
    const marked = screen
      .getAllByRole('link')
      .filter((a) => a.getAttribute('aria-current') === 'step');
    expect(marked).toHaveLength(1);
  });

  it('carries each stage’s state in words, not only in the marker', () => {
    // The dot's fill is a second signal. A greyscale projector and a screen
    // reader both need the first one.
    render(
      <Meridian
        nodes={nodes([
          { key: 'discovery', state: 'DONE' },
          { key: 'generation', state: 'BLOCKED' },
        ])}
        currentId="brief"
      />,
    );
    expect(screen.getByRole('link', { name: /Brief.*Done/s })).toBeDefined();
    expect(screen.getByRole('link', { name: /Generate.*Blocked/s })).toBeDefined();
  });

  it('keeps a blocked stage as a real link', () => {
    // Refusing navigation to a stage that is not ready is how the product
    // became one-way in the first place.
    render(<Meridian nodes={nodes([{ key: 'composition', state: 'BLOCKED' }])} currentId="brief" />);
    const compose = screen.getByRole('link', { name: /Compose & export/ });
    expect(compose.getAttribute('href')).toBe('/app/campaigns/c-1/compose');
  });

  it('renders before the campaign summary arrives', () => {
    // Navigation must work on first paint; the summary is a second request.
    render(<Meridian nodes={resolveJourney('c-1', null)} currentId="brief" />);
    expect(screen.getAllByRole('link')).toHaveLength(JOURNEY.length);
  });

  it('shows no internal stage names', () => {
    const { container } = render(<Meridian nodes={nodes()} currentId="brief" />);
    const text = container.textContent ?? '';
    for (const internal of ['guardian', 'evaluation', 'discovery', 'composition']) {
      expect(text.toLowerCase()).not.toContain(internal);
    }
  });
});

describe('PlaceStamp', () => {
  it('sets place, language and season as one legend', () => {
    render(
      <PlaceStamp
        region="Jaipur, Rajasthan"
        language="Hindi + English"
        occasion="Hot season, March to June"
        detail="full"
      />,
    );
    expect(screen.getByText('Jaipur, Rajasthan')).toBeDefined();
    expect(screen.getByText('Hindi + English')).toBeDefined();
    expect(screen.getByText('Hot season, March to June')).toBeDefined();
  });

  it('leaves the season out of the compact form', () => {
    const { container } = render(
      <PlaceStamp region="Kochi, Kerala" language="Malayalam + English" occasion="Monsoon" />,
    );
    expect(container.textContent).toContain('Kochi, Kerala');
    expect(container.textContent).not.toContain('Monsoon');
  });

  it('draws nothing at all when the market is not known yet', () => {
    // `region` and `timing_occasion` are nullable and a campaign in discovery
    // has no specification. A stamp reading "Unknown · Unknown" is worse than
    // no stamp, and an invented "India" would be a claim nobody made.
    const { container } = render(<PlaceStamp region={null} language={null} occasion={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('omits only the parts that are missing', () => {
    const { container } = render(<PlaceStamp region="Assam" language={null} />);
    expect(container.textContent).toContain('Assam');
    expect(screen.queryByText('·')).toBeNull();
  });

  it('names the row for a screen reader', () => {
    render(<PlaceStamp region="Guwahati, Assam" language="Assamese" />);
    expect(screen.getByText('Market:')).toBeDefined();
  });
});
