/**
 * Reading the composition stage.
 *
 * The geometry half is arithmetic and is tested as arithmetic. The rest exists
 * to stop this screen claiming things the API does not say: a channel size it
 * has never seen, a lock the server does not enforce, or a check the server
 * does not perform.
 */

import { describe, expect, it } from 'vitest';
import {
  EXPORT_FORMATS,
  aspectLabel,
  bounds,
  channelCopy,
  channelViews,
  clampToCanvas,
  editableFields,
  elementName,
  finalAssetFacts,
  groupIssues,
  hasLock,
  isLocked,
  issuesFor,
  layoutCheck,
  locksFor,
  percent,
  pixels,
  quantise,
  safeRect,
  standing,
} from './compose';
import type {
  CompositionView,
  FinalAssetView,
  LayoutElementView,
  LayoutSpecView,
  TextStyleView,
} from './api';

// ----------------------------------------------------------------- fixtures

function textStyle(over: Partial<TextStyleView> = {}): TextStyleView {
  return {
    font_family: null,
    font_weight: 'bold',
    size: 0.075,
    color: '#FFFFFF',
    align: 'left',
    line_height: 1.15,
    letter_spacing: 0,
    max_lines: 3,
    uppercase: false,
    scrim: false,
    scrim_opacity: 0.45,
    ...over,
  };
}

function element(over: Partial<LayoutElementView> = {}): LayoutElementView {
  return {
    id: 'e-headline',
    type: 'text',
    box: { x: 0.06, y: 0.62, width: 0.88, height: 0.22, anchor: 'top_left' },
    z: 20,
    visible: true,
    content: 'Built to outlast the building it clads',
    text_style: textStyle(),
    role: 'headline',
    storage_key: null,
    fit: 'cover',
    fill: null,
    opacity: 1,
    radius: 0,
    ...over,
  };
}

const CTA = element({
  id: 'e-cta',
  role: 'cta',
  content: 'Request the specification pack',
  box: { x: 0.06, y: 0.86, width: 0.6, height: 0.06, anchor: 'top_left' },
  text_style: textStyle({ size: 0.03 }),
});

const LOGO = element({
  id: 'e-logo',
  type: 'logo',
  role: 'logo',
  content: null,
  text_style: null,
  storage_key: 'org-1/brand-1/logo.png',
  box: { x: 0.72, y: 0.06, width: 0.22, height: 0.09, anchor: 'top_left' },
  z: 30,
});

const SCRIM = element({
  id: 'e-scrim',
  type: 'shape',
  role: null,
  content: null,
  text_style: null,
  fill: '#1F2933',
  opacity: 0.55,
  box: { x: 0, y: 0.58, width: 1, height: 0.42, anchor: 'top_left' },
  z: 10,
});

function layout(over: Partial<LayoutSpecView> = {}): LayoutSpecView {
  return {
    id: 'l-1',
    campaign_id: 'c-1',
    channel: 'instagram_post',
    version: 1,
    width: 1080,
    height: 1080,
    source_asset_id: 'a-1',
    specification_version: 3,
    plate_storage_key: 'org-1/campaign-1/generated/plate.png',
    background_color: '#1F2933',
    safe_area: { top: 0.06, right: 0.06, bottom: 0.06, left: 0.06 },
    elements: [SCRIM, element(), CTA, LOGO],
    ...over,
  };
}

function finalAsset(over: Partial<FinalAssetView> = {}): FinalAssetView {
  return {
    id: 'f-1',
    campaign_id: 'c-1',
    channel: 'instagram_post',
    kind: 'FINAL_BRANDED_ASSET',
    version: 1,
    width: 1080,
    height: 1080,
    mime_type: 'image/png',
    size_bytes: 41_200,
    url: '/v1/campaigns/c-1/final-assets/f-1/content?token=signed',
    download_url: '/v1/campaigns/c-1/final-assets/f-1/content?token=signed&download=true',
    source_asset_id: 'a-1',
    specification_version: 3,
    layout_version: 1,
    renderer_version: 'r1',
    created_at: '2026-01-02T10:00:00Z',
    ...over,
  };
}

function composition(over: Partial<CompositionView> = {}): CompositionView {
  return {
    campaign_id: 'c-1',
    channel: 'instagram_post',
    layout: layout(),
    report: { verdict: 'PASS', issues: [] },
    final_assets: [finalAsset()],
    composed_channels: ['instagram_post', 'instagram_story'],
    available_channels: ['linkedin', 'facebook'],
    can_compose: true,
    blocked_reason: null,
    ...over,
  };
}

// ------------------------------------------------------------------ naming

describe('elementName', () => {
  it('names an element by its role before its type', () => {
    expect(elementName(element())).toBe('Headline');
    expect(elementName(CTA)).toBe('Call to action');
    expect(elementName(LOGO)).toBe('Logo');
  });

  it('names the builder’s scrim for what it does', () => {
    // "Shape" would tell a reader nothing about the band behind the copy.
    expect(elementName(SCRIM)).toBe('Text backdrop');
  });

  it('falls through to the type for a role it does not know', () => {
    expect(elementName(element({ role: 'something_new' }))).toBe('Text');
  });
});

// ------------------------------------------------------------ what may change

describe('editableFields', () => {
  it('offers the type controls only where there is text to style', () => {
    expect([...editableFields(element())].sort()).toEqual([
      'align',
      'color',
      'content',
      'height',
      'size',
      'uppercase',
      'visible',
      'width',
      'x',
      'y',
    ]);
  });

  it('offers a logo only position and visibility', () => {
    // A size control on a logo would be a control that quietly does nothing.
    expect([...editableFields(LOGO)].sort()).toEqual([
      'height',
      'visible',
      'width',
      'x',
      'y',
    ]);
    expect(editableFields(LOGO).has('size')).toBe(false);
  });

  it('treats a shape as position-only too', () => {
    expect(editableFields(SCRIM).has('content')).toBe(false);
  });
});

describe('locksFor', () => {
  it('locks the call to action’s words, and says where to change them', () => {
    const locks = locksFor(CTA);
    expect(locks).toHaveLength(1);
    expect(locks[0]!.field).toBe('content');
    expect(locks[0]!.reason).toMatch(/revision/i);
    expect(isLocked(CTA, 'content')).toBe(true);
    // Everything else about it still moves.
    expect(isLocked(CTA, 'x')).toBe(false);
  });

  it('refuses to edit the legal line here at all', () => {
    const legal = element({ id: 'e-legal', role: 'legal', content: 'Terms apply.' });
    expect(locksFor(legal)[0]!.reason).toMatch(/Brand Brain/);
  });

  it('will not let the logo be hidden, and explains why', () => {
    expect(isLocked(LOGO, 'visible')).toBe(true);
    expect(locksFor(LOGO)[0]!.reason).toMatch(/without the brand is not a deliverable/);
  });

  it('leaves an ordinary element unlocked', () => {
    expect(locksFor(element())).toEqual([]);
    expect(hasLock(element())).toBe(false);
    expect(hasLock(CTA)).toBe(true);
  });
});

// ---------------------------------------------------------------- geometry

describe('geometry', () => {
  it('reads a box as fractional edges', () => {
    expect(bounds({ x: 0.1, y: 0.2, width: 0.3, height: 0.4, anchor: 'top_left' })).toEqual({
      left: 0.1,
      top: 0.2,
      right: 0.4,
      bottom: 0.6000000000000001,
    });
  });

  it('turns the safe area into the same fractional space', () => {
    expect(safeRect({ top: 0.06, right: 0.06, bottom: 0.06, left: 0.06 })).toEqual({
      left: 0.06,
      top: 0.06,
      right: 0.94,
      bottom: 0.94,
    });
  });

  it('keeps a box on the canvas, which is what the model requires', () => {
    const clamped = clampToCanvas({
      x: 1.4,
      y: -0.3,
      width: 0.3,
      height: 0.2,
      anchor: 'top_left',
    });
    expect(clamped.x).toBeCloseTo(0.7);
    expect(clamped.y).toBe(0);
    expect(clamped.x + clamped.width).toBeLessThanOrEqual(1.0001);
  });

  it('rounds to what the renderer can express', () => {
    expect(quantise(0.123456789)).toBe(0.1235);
  });

  it('converts a fraction to the pixels a designer checks', () => {
    expect(pixels(0.06, 1080)).toBe(65);
    expect(percent(0.062)).toBe('6%');
  });
});

describe('standing', () => {
  const safe = { top: 0.06, right: 0.06, bottom: 0.06, left: 0.06 };

  it('reports an element inside the margins as safe', () => {
    expect(standing(element(), safe)).toBe('safe');
  });

  it('reports one outside the margins', () => {
    const high = element({ box: { ...element().box, y: 0.01 } });
    expect(standing(high, safe)).toBe('outside-safe');
  });

  it('reports one past the canvas edge, which is a different problem', () => {
    const off = element({ box: { ...element().box, x: 0.9, width: 0.5 } });
    expect(standing(off, safe)).toBe('off-canvas');
  });

  it('has nothing to say about a hidden element', () => {
    // `validate_layout` evaluates only visible elements, so a hidden one has no
    // standing — and the builder's legal line is hidden *and* below the safe
    // area by construction.
    const legal = element({
      role: 'legal',
      visible: false,
      box: { x: 0.06, y: 0.945, width: 0.88, height: 0.02, anchor: 'top_left' },
    });
    expect(standing(legal, safe)).toBe('hidden');
  });

  it('does not govern backdrop, because a scrim is meant to bleed', () => {
    // Flagging it would put a warning on every correct layout the builder
    // produces, which teaches people to ignore the panel.
    expect(standing(SCRIM, safe)).toBe('not-governed');
  });

  it('judges a proposed box rather than the stored one when asked', () => {
    const proposed = { ...element().box, y: 0.001 };
    expect(standing(element(), safe, proposed)).toBe('outside-safe');
    expect(standing(element(), safe)).toBe('safe');
  });
});

// ------------------------------------------------------------------ issues

describe('the layout check', () => {
  it('reports “not checked” differently from “it passed”', () => {
    const none = layoutCheck(null);
    expect(none.unknown).toBe(true);
    expect(none.label).toBe('Not checked');
    expect(none.blocked).toBe(false);
  });

  it('reads a pass with notes as a pass', () => {
    const check = layoutCheck({
      verdict: 'PASS',
      issues: [{ element_id: 'e-1', role: null, severity: 'warning', detail: 'x', suggested_fix: null }],
    });
    expect(check.blocked).toBe(false);
    expect(check.warnings).toBe(1);
    expect(check.label).toMatch(/with notes/);
  });

  it('blocks a render when the server says the layout needs adjustment', () => {
    const check = layoutCheck({
      verdict: 'NEEDS_ADJUSTMENT',
      issues: [
        { element_id: 'e-logo', role: 'logo', severity: 'blocking', detail: 'x', suggested_fix: null },
      ],
    });
    expect(check.blocked).toBe(true);
    expect(check.blocking).toBe(1);
  });

  it('groups issues by what they are about, blocking first', () => {
    const groups = groupIssues(
      {
        issues: [
          { element_id: 'e-headline', role: 'headline', severity: 'warning', detail: 'w', suggested_fix: null },
          { element_id: 'e-logo', role: 'logo', severity: 'blocking', detail: 'b', suggested_fix: 'move it' },
        ],
      },
      layout(),
    );
    expect(groups.map((g) => g.subject)).toEqual(['Logo', 'Headline']);
    expect(groups[0]!.issues[0]!.suggested_fix).toBe('move it');
  });

  it('names the canvas for an issue that belongs to no element', () => {
    const groups = groupIssues(
      { issues: [{ element_id: null, role: null, severity: 'blocking', detail: 'too small', suggested_fix: null }] },
      layout(),
    );
    expect(groups[0]!.subject).toBe('The canvas');
    expect(groups[0]!.element).toBeNull();
  });

  it('finds the issues about one element', () => {
    const report = {
      issues: [
        { element_id: 'e-logo', role: 'logo', severity: 'blocking' as const, detail: 'b', suggested_fix: null },
        { element_id: 'e-headline', role: 'headline', severity: 'warning' as const, detail: 'w', suggested_fix: null },
      ],
    };
    expect(issuesFor(report, 'e-logo')).toHaveLength(1);
    expect(issuesFor(report, 'nobody')).toHaveLength(0);
  });
});

// ---------------------------------------------------------------- channels

describe('channelViews', () => {
  it('shows every composable channel, not just the ones left to add', () => {
    // `available_channels` is the composable set *minus* the composed ones, so
    // reading it alone hides everything the campaign already works on.
    const channels = channelViews(composition());
    expect(channels.map((c) => c.channel).sort()).toEqual([
      'facebook',
      'instagram_post',
      'instagram_story',
      'linkedin',
    ]);
  });

  it('marks what is composed and which one is open', () => {
    const channels = channelViews(composition());
    expect(channels.find((c) => c.channel === 'instagram_post')!.composed).toBe(true);
    expect(channels.find((c) => c.channel === 'instagram_post')!.current).toBe(true);
    expect(channels.find((c) => c.channel === 'linkedin')!.composed).toBe(false);
  });

  it('gives a size only for a channel it has really seen one for', () => {
    const channels = channelViews(composition());
    const post = channels.find((c) => c.channel === 'instagram_post')!;
    expect(post.width).toBe(1080);
    expect(post.ratio).toBe('1:1');
    // `CHANNEL_DIMENSIONS` is a backend constant no endpoint publishes, so a
    // size here would be a number this app invented.
    const linkedin = channels.find((c) => c.channel === 'linkedin')!;
    expect(linkedin.width).toBeNull();
    expect(linkedin.ratio).toBeNull();
  });

  it('learns a size from a rendered asset when there is no layout', () => {
    const channels = channelViews(
      composition({
        layout: null,
        final_assets: [finalAsset({ channel: 'instagram_story', width: 1080, height: 1920 })],
        composed_channels: ['instagram_story'],
        available_channels: [],
      }),
    );
    const story = channels.find((c) => c.channel === 'instagram_story')!;
    expect(story.height).toBe(1920);
    expect(story.ratio).toBe('9:16');
  });

  it('counts the renders a channel has', () => {
    const channels = channelViews(
      composition({ final_assets: [finalAsset(), finalAsset({ id: 'f-2', version: 2 })] }),
    );
    expect(channels.find((c) => c.channel === 'instagram_post')!.renders).toBe(2);
  });

  it('marks a channel composed even when no size is known for it yet', () => {
    // `composed` and "we have seen its pixel size" are independent facts, and
    // conflating them labelled a composed channel as uncomposed.
    const channels = channelViews(
      composition({
        composed_channels: ['instagram_post', 'instagram_story'],
        available_channels: ['linkedin'],
        final_assets: [],
      }),
    );
    const story = channels.find((c) => c.channel === 'instagram_story')!;
    expect(story.composed).toBe(true);
    expect(story.width).toBeNull();
  });

  it('is empty when there is nothing to read', () => {
    expect(channelViews(null)).toEqual([]);
  });
});

describe('aspectLabel', () => {
  it('reduces real pixels to a ratio', () => {
    expect(aspectLabel(1080, 1350)).toBe('4:5');
    expect(aspectLabel(1080, 1920)).toBe('9:16');
    expect(aspectLabel(1080, 1080)).toBe('1:1');
    expect(aspectLabel(1200, 627)).toBe('400:209');
  });

  it('returns nothing rather than dividing by zero', () => {
    expect(aspectLabel(0, 100)).toBeNull();
  });
});

// ------------------------------------------------------------ channel copy

describe('channelCopy', () => {
  it('reports words that differ from the default as tailored', () => {
    const lines = channelCopy(layout(), { headline: 'A different default', cta: 'Request the specification pack' });
    expect(lines.find((l) => l.role === 'headline')!.origin).toBe('tailored');
  });

  it('reports words that match the default as inherited', () => {
    const lines = channelCopy(layout(), {
      headline: 'Built to outlast the building it clads',
      cta: 'Request the specification pack',
    });
    expect(lines.find((l) => l.role === 'headline')!.origin).toBe('inherited');
  });

  it('always reports the call to action as locked', () => {
    // Whatever its source, the rule a person needs to know is that it cannot
    // be rewritten here.
    const lines = channelCopy(layout(), { cta: 'Request the specification pack' });
    expect(lines.find((l) => l.role === 'cta')!.origin).toBe('locked');
  });

  it('is empty when there is no layout', () => {
    expect(channelCopy(null, {})).toEqual([]);
  });
});

// ------------------------------------------------------------ final assets

describe('finalAssetFacts', () => {
  it('reads the provenance stamped on the file', () => {
    const facts = finalAssetFacts(finalAsset(), layout());
    const value = (label: string) => facts.rows.find((r) => r.label === label)?.value;
    expect(value('Channel')).toBe('Instagram post');
    expect(value('Size')).toBe('1080 × 1080');
    expect(value('Aspect ratio')).toBe('1:1');
    expect(value('Creative plan')).toBe('v3');
    expect(value('Built from layout')).toBe('v1');
    expect(value('Renderer')).toBe('r1');
    expect(value('File size')).toBe('40 KB');
  });

  it('says when the layout has moved on since the file was rendered', () => {
    const facts = finalAssetFacts(finalAsset({ layout_version: 1 }), layout({ version: 3 }));
    expect(facts.supersededBy).toBe(3);
  });

  it('says nothing of the sort when the file is current', () => {
    expect(finalAssetFacts(finalAsset({ layout_version: 1 }), layout({ version: 1 })).supersededBy)
      .toBeNull();
  });

  it('omits a file size the API did not give', () => {
    const facts = finalAssetFacts(finalAsset({ size_bytes: null }), layout());
    expect(facts.rows.find((r) => r.label === 'File size')).toBeUndefined();
  });
});

describe('export formats', () => {
  it('offers only what the render endpoint accepts', () => {
    // PDF and print production are not built, and the API refuses the print
    // channels outright.
    expect(EXPORT_FORMATS.map((f) => f.format)).toEqual(['PNG', 'JPEG']);
  });
});
