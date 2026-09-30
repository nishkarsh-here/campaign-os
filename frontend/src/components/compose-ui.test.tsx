// @vitest-environment jsdom

/**
 * The composition workspace.
 *
 * The canvas is a picture, and a picture is unavailable to a screen reader and
 * unusable at 375px — so most of what is asserted here is that the layout can
 * be read and changed *without* it: named layers, labelled controls, the
 * server's own sentences.
 *
 * The governance half is the rest: that a storage key never reaches an `img`,
 * that a size is never shown for a channel nobody has composed, and that a lock
 * is always accompanied by the reason for it.
 */

import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { ComposeCanvas } from './compose-canvas';
import {
  ChannelPicker,
  CollapsiblePanel,
  Inspector,
  LayerList,
  LayoutCheckPanel,
} from './compose-workspace';
import { FinalAssetPanel, RenderHistory, RenderPanel } from './final-asset';
import { capabilitiesFor } from '@/lib/capabilities';
import { channelViews, layoutCheck } from '@/lib/compose';
import type {
  CompositionView,
  FinalAssetView,
  LayoutElementView,
  LayoutIssueView,
  LayoutSpecView,
  TextStyleView,
} from '@/lib/api';

const admin = capabilitiesFor('admin');
const viewer = capabilitiesFor('viewer');
const noop = () => undefined;

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

const PLATE_KEY = 'org-1/campaign-1/generated/secret-plate.png';

const CTA = element({
  id: 'e-cta',
  role: 'cta',
  content: 'Request the specification pack',
  text_style: textStyle({ size: 0.03 }),
  box: { x: 0.06, y: 0.86, width: 0.6, height: 0.06, anchor: 'top_left' },
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
    plate_storage_key: PLATE_KEY,
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
    url: '/v1/campaigns/c-1/final-assets/f-1/content?token=signed-token',
    download_url: '/v1/campaigns/c-1/final-assets/f-1/content?token=signed-token&download=true',
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
    composed_channels: ['instagram_post'],
    available_channels: ['linkedin'],
    can_compose: true,
    blocked_reason: null,
    ...over,
  };
}

const PLATE_URL = 'http://api.test/v1/campaigns/c-1/assets/a-1/content?token=plate-signed';

function canvas(over: Record<string, unknown> = {}) {
  return render(
    <ComposeCanvas
      layout={layout()}
      plateUrl={PLATE_URL}
      logoUrl="http://api.test/v1/brands/b-1/assets/l-1/content?token=logo-signed"
      selectedId={null}
      onSelect={noop}
      onCommit={noop}
      canEdit
      flagged={new Set()}
      {...over}
    />,
  );
}

// ------------------------------------------------------------------ canvas

describe('ComposeCanvas', () => {
  it('draws the real elements the layout carries', () => {
    canvas();
    expect(screen.getByText('Built to outlast the building it clads')).toBeTruthy();
    expect(screen.getByText('Request the specification pack')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Logo' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Text backdrop' })).toBeTruthy();
  });

  it('fetches the plate through a signed URL, never its storage key', () => {
    // No route takes a storage key from a request (M10), so a key in an `img`
    // would be both broken and a contract violation.
    const { container } = canvas();
    const sources = [...container.querySelectorAll('img')].map((i) => i.getAttribute('src') ?? '');
    expect(sources.some((s) => s.includes('token=plate-signed'))).toBe(true);
    for (const src of sources) expect(src).not.toContain(PLATE_KEY);
    expect(container.innerHTML).not.toContain(PLATE_KEY);
  });

  it('places every element by its normalised box', () => {
    canvas();
    const headline = screen.getByRole('button', { name: 'Headline' });
    expect(headline.style.left).toBe('6%');
    expect(headline.style.top).toBe('62%');
    expect(headline.style.width).toBe('88%');
    expect(headline.style.height).toBe('22%');
  });

  it('sizes text as a fraction of canvas height, the way the renderer does', () => {
    canvas();
    const text = screen.getByText('Built to outlast the building it clads');
    // jsdom normalises the calc; 7.5cqh is 7.5% of the canvas's own height.
    expect(text.style.fontSize).toBe('calc(7.5cqh)');
  });

  it('keeps the canvas at the layout’s own aspect ratio', () => {
    const { container } = canvas();
    const frame = container.querySelector('.compose-canvas') as HTMLElement;
    expect(frame.style.aspectRatio).toBe('1080 / 1080');
    expect(frame.style.background).toContain('rgb(31, 41, 51)');
  });

  it('draws the safe area from the layout’s own margins', () => {
    const { container } = canvas();
    const overlay = container.querySelector('.border-dashed') as HTMLElement;
    // `right` is an inset from the right edge, so a 6% margin is `right: 6%`.
    expect(overlay.style.left).toBe('6%');
    expect(parseFloat(overlay.style.right)).toBeCloseTo(6);
    expect(parseFloat(overlay.style.bottom)).toBeCloseTo(6);
    // It must never swallow a drag.
    expect(overlay.className).toContain('pointer-events-none');
  });

  it('hides an element the layout says is not visible', () => {
    canvas({ layout: layout({ elements: [element({ visible: false })] }) });
    expect(screen.queryByText('Built to outlast the building it clads')).toBeNull();
  });

  it('says so when the plate cannot be loaded, without hiding the layout', () => {
    canvas();
    fireEvent.error(screen.getByRole('button', { name: 'Text backdrop' }).ownerDocument.querySelector('img')!);
    expect(screen.getByText(/could not be loaded/i)).toBeTruthy();
    expect(screen.getByText('Built to outlast the building it clads')).toBeTruthy();
  });

  it('names the logo rather than drawing a placeholder mark when it has no URL', () => {
    canvas({ logoUrl: null });
    const logo = screen.getByRole('button', { name: 'Logo' });
    expect(within(logo).getByText('Logo')).toBeTruthy();
    expect(logo.querySelector('img')).toBeNull();
  });

  it('is operable from the keyboard, which a canvas otherwise is not', () => {
    const onCommit = vi.fn();
    canvas({ onCommit });
    const headline = screen.getByRole('button', { name: 'Headline' });
    expect(headline.tabIndex).toBe(0);
    fireEvent.keyDown(headline, { key: 'ArrowRight' });
    expect(onCommit).toHaveBeenCalledWith('e-headline', expect.objectContaining({ x: 0.065 }));
  });

  it('moves further with shift, and never off the canvas', () => {
    const onCommit = vi.fn();
    canvas({ onCommit, layout: layout({ elements: [element({ box: { x: 0.9, y: 0.5, width: 0.09, height: 0.1, anchor: 'top_left' } })] }) });
    fireEvent.keyDown(screen.getByRole('button', { name: 'Headline' }), {
      key: 'ArrowRight',
      shiftKey: true,
    });
    const box = onCommit.mock.calls[0]![1] as { x: number; width: number };
    expect(box.x + box.width).toBeLessThanOrEqual(1.0001);
  });

  it('announces which element is selected', () => {
    canvas({ selectedId: 'e-cta' });
    const cta = screen.getByRole('button', { name: 'Call to action, selected' });
    expect(cta.getAttribute('aria-pressed')).toBe('true');
  });

  it('abandons a drag the browser cancels, instead of following stray moves', () => {
    // A touch interrupted by a system gesture fires `pointercancel`. Without
    // handling it the listeners stayed on `window` and the element kept
    // tracking every later move, never committing.
    const onCommit = vi.fn();
    const { container } = canvas({ onCommit });
    const headline = screen.getByRole('button', { name: 'Headline' });
    const frame = container.querySelector('.compose-canvas') as HTMLElement;
    vi.spyOn(frame, 'getBoundingClientRect').mockReturnValue({
      width: 1000, height: 1000, x: 0, y: 0, top: 0, left: 0, right: 1000, bottom: 1000,
      toJSON: () => ({}),
    } as DOMRect);

    fireEvent.pointerDown(headline, { clientX: 100, clientY: 100, pointerId: 1 });
    fireEvent(window, new Event('pointercancel'));
    // A stray move after the cancel must do nothing at all.
    fireEvent(window, Object.assign(new Event('pointermove'), { clientX: 900, clientY: 100 }));
    expect(screen.getByRole('button', { name: 'Headline' }).style.left).toBe('6%');
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('lets go of the window when it unmounts mid-drag', () => {
    const onCommit = vi.fn();
    const { container, unmount } = canvas({ onCommit });
    const headline = screen.getByRole('button', { name: 'Headline' });
    const frame = container.querySelector('.compose-canvas') as HTMLElement;
    vi.spyOn(frame, 'getBoundingClientRect').mockReturnValue({
      width: 1000, height: 1000, x: 0, y: 0, top: 0, left: 0, right: 1000, bottom: 1000,
      toJSON: () => ({}),
    } as DOMRect);

    fireEvent.pointerDown(headline, { clientX: 100, clientY: 100, pointerId: 1 });
    unmount();
    // Switching channel unmounts the canvas. A listener left behind here would
    // call into a component that no longer exists.
    expect(() => {
      fireEvent(window, Object.assign(new Event('pointermove'), { clientX: 400, clientY: 100 }));
      fireEvent(window, new Event('pointerup'));
    }).not.toThrow();
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('does not offer a resize grip to someone who cannot edit', () => {
    const { container } = canvas({ selectedId: 'e-headline', canEdit: false });
    expect(container.querySelector('.cursor-nwse-resize')).toBeNull();
  });
});

// ------------------------------------------------------------------ layers

describe('LayerList', () => {
  const list = (over: Record<string, unknown> = {}) =>
    render(
      <LayerList
        layout={layout()}
        report={{ issues: [] }}
        selectedId={null}
        onSelect={noop}
        {...over}
      />,
    );

  it('lists everything on the canvas, topmost first', () => {
    list();
    const names = screen.getAllByRole('button').map((b) => b.textContent);
    expect(names[0]).toContain('Logo');
    expect(names[names.length - 1]).toContain('Text backdrop');
  });

  it('marks what is protected, in words as well as a mark', () => {
    list();
    // A padlock glyph alone is invisible to a screen reader.
    expect(screen.getAllByText('Protected')).toHaveLength(2);
  });

  it('selects an element', () => {
    const onSelect = vi.fn();
    list({ onSelect });
    fireEvent.click(screen.getByRole('button', { name: /Headline/ }));
    expect(onSelect).toHaveBeenCalledWith('e-headline');
  });

  it('flags a layer the check has something to say about', () => {
    list({
      report: {
        issues: [
          { element_id: 'e-logo', role: 'logo', severity: 'blocking', detail: 'x', suggested_fix: null },
        ] as LayoutIssueView[],
      },
    });
    expect(screen.getByText('Blocking')).toBeTruthy();
  });

  it('keeps a hidden element in the list and says it is hidden', () => {
    list({ layout: layout({ elements: [element({ visible: false })] }) });
    expect(screen.getByText('Hidden')).toBeTruthy();
  });

  it('does not judge a hidden element against the safe area', () => {
    // `validate_layout` only evaluates visible elements. The builder's legal
    // line is hidden *and* sits below the safe area by construction, so judging
    // it put a caution badge on every layout whose brand has a legal line —
    // beside a panel saying everything was inside the margins.
    const legal = element({
      id: 'e-legal',
      role: 'legal',
      visible: false,
      content: 'Terms apply.',
      box: { x: 0.06, y: 0.945, width: 0.88, height: 0.02, anchor: 'top_left' },
    });
    list({ layout: layout({ elements: [legal] }) });
    expect(screen.queryByText('Outside')).toBeNull();
    expect(screen.getByText('Hidden')).toBeTruthy();
  });
});

// --------------------------------------------------------------- inspector

describe('Inspector', () => {
  const inspect = (over: Record<string, unknown> = {}) =>
    render(
      <Inspector
        layout={layout()}
        element={element()}
        report={{ issues: [] }}
        busy={false}
        capabilities={admin}
        onEdit={noop}
        attempt={0}
        {...over}
      />,
    );

  it('labels every control the way a person would say it', () => {
    inspect();
    for (const label of ['Horizontal position', 'Vertical position', 'Width', 'Height', 'Text size', 'Alignment', 'Colour']) {
      expect(screen.getByLabelText(label), label).toBeTruthy();
    }
    // Not the field names the API uses.
    expect(screen.queryByLabelText('x')).toBeNull();
    expect(screen.queryByLabelText('y')).toBeNull();
  });

  it('shows a fractional position as a percentage and real pixels', () => {
    inspect();
    expect((screen.getByLabelText('Horizontal position') as HTMLInputElement).value).toBe('6');
    expect(screen.getByText(/65px/)).toBeTruthy();
  });

  it('sends a normalised fraction back, not a percentage', () => {
    const onEdit = vi.fn();
    inspect({ onEdit });
    const field = screen.getByLabelText('Horizontal position');
    fireEvent.change(field, { target: { value: '12' } });
    fireEvent.blur(field);
    expect(onEdit).toHaveBeenCalledWith('e-headline', { x: 0.12 });
  });

  it('commits when the field is done with, not on every keystroke', () => {
    // Each accepted edit writes a new layout version, so committing per
    // keystroke would turn typing "12" into two versions — one of them for the
    // intermediate value 1.
    const onEdit = vi.fn();
    inspect({ onEdit });
    const field = screen.getByLabelText('Horizontal position');
    fireEvent.change(field, { target: { value: '1' } });
    fireEvent.change(field, { target: { value: '12' } });
    expect(onEdit).not.toHaveBeenCalled();
    fireEvent.blur(field);
    expect(onEdit).toHaveBeenCalledTimes(1);
  });

  it('sends nothing when the value did not actually change', () => {
    const onEdit = vi.fn();
    inspect({ onEdit });
    fireEvent.blur(screen.getByLabelText('Horizontal position'));
    expect(onEdit).not.toHaveBeenCalled();
  });

  it('offers no type controls on an element that has no text style', () => {
    inspect({ element: LOGO });
    expect(screen.queryByLabelText('Text size')).toBeNull();
    expect(screen.queryByLabelText('Alignment')).toBeNull();
    expect(screen.getByLabelText('Width')).toBeTruthy();
  });

  it('explains a locked call to action instead of only disabling it', () => {
    inspect({ element: CTA });
    expect(screen.getByText('Protected element')).toBeTruthy();
    expect(screen.getByText(/approved campaign fact/)).toBeTruthy();
    expect((screen.getByLabelText('Text') as HTMLTextAreaElement).disabled).toBe(true);
    // And the things that are *not* locked still work.
    expect((screen.getByLabelText('Horizontal position') as HTMLInputElement).disabled).toBe(false);
  });

  it('explains why the logo cannot be hidden', () => {
    inspect({ element: LOGO });
    expect(screen.getByText(/cannot be hidden/)).toBeTruthy();
    const visible = screen.getByLabelText('Visible') as HTMLInputElement;
    expect(visible.disabled).toBe(true);
  });

  it('refuses to edit the legal line here, and says where it comes from', () => {
    inspect({ element: element({ id: 'e-legal', role: 'legal', content: 'Terms apply.' }) });
    expect(screen.getByText(/Brand Brain/)).toBeTruthy();
  });

  it('shows the server’s own words about this element', () => {
    inspect({
      report: {
        issues: [
          {
            element_id: 'e-headline',
            role: 'headline',
            severity: 'blocking',
            detail: 'Headline extends past the canvas edge.',
            suggested_fix: 'Move it inward or make it smaller.',
          },
        ] as LayoutIssueView[],
      },
    });
    const alert = screen.getByRole('alert');
    expect(within(alert).getByText('Headline extends past the canvas edge.')).toBeTruthy();
    expect(within(alert).getByText('Move it inward or make it smaller.')).toBeTruthy();
  });

  it('clears a value the server refused, instead of leaving it on screen', () => {
    // A refusal leaves the stored value unchanged, so keying only off that
    // value kept the rejected number in the field — next to a pixel readout
    // computed from the number the layout actually has.
    const { rerender } = inspect();
    const field = screen.getByLabelText('Horizontal position') as HTMLInputElement;
    fireEvent.change(field, { target: { value: '95' } });
    fireEvent.blur(field);
    // The server refused: the layout is unchanged, only the attempt advances.
    rerender(
      <Inspector
        layout={layout()}
        element={element()}
        report={{ issues: [] }}
        busy={false}
        capabilities={admin}
        onEdit={noop}
        attempt={1}
      />,
    );
    expect((screen.getByLabelText('Horizontal position') as HTMLInputElement).value).toBe('6');
  });

  it('does not offer a zero width, which the endpoint refuses', () => {
    // `ElementEditRequest` has width/height as gt=0, and x/y as ge=0.
    inspect();
    expect(screen.getByLabelText('Width').getAttribute('min')).toBe('0.1');
    expect(screen.getByLabelText('Height').getAttribute('min')).toBe('0.1');
    expect(screen.getByLabelText('Horizontal position').getAttribute('min')).toBe('0');
  });

  it('caps the text at what the endpoint accepts', () => {
    inspect();
    expect(screen.getByLabelText('Text').getAttribute('maxlength')).toBe('300');
  });

  it('is read-only for someone who cannot edit the campaign', () => {
    inspect({ capabilities: viewer });
    expect((screen.getByLabelText('Horizontal position') as HTMLInputElement).disabled).toBe(true);
  });

  it('shows the newly selected element’s words, not the previous one’s', () => {
    // The content box is uncontrolled, so without a key it kept the old text
    // and a blur would have written it onto the new element.
    const { rerender } = inspect();
    expect((screen.getByLabelText('Text') as HTMLTextAreaElement).value).toBe(
      'Built to outlast the building it clads',
    );
    rerender(
      <Inspector
        layout={layout()}
        element={CTA}
        report={{ issues: [] }}
        busy={false}
        capabilities={admin}
        onEdit={noop}
        attempt={0}
      />,
    );
    expect((screen.getByLabelText('Text') as HTMLTextAreaElement).value).toBe(
      'Request the specification pack',
    );
  });

  it('keeps the raw layout values behind a disclosure', () => {
    const { container } = inspect();
    const details = container.querySelector('details') as HTMLDetailsElement;
    expect(details.hasAttribute('open')).toBe(false);
    expect(within(details).getByText('anchor')).toBeTruthy();
  });
});

// ------------------------------------------------------------- the check

describe('LayoutCheckPanel', () => {
  const panel = (over: Record<string, unknown> = {}) => {
    const report = (over.report as CompositionView['report']) ?? { verdict: 'PASS', issues: [] };
    return render(
      <LayoutCheckPanel
        check={layoutCheck(report)}
        report={report}
        layout={layout()}
        onSelect={noop}
        {...over}
      />,
    );
  };

  it('says a clean layout is ready to render', () => {
    panel();
    expect(screen.getByText('Ready to render')).toBeTruthy();
    expect(screen.getByText(/inside the safe area/)).toBeTruthy();
  });

  it('distinguishes a blocking issue from a note', () => {
    panel({
      report: {
        verdict: 'NEEDS_ADJUSTMENT',
        issues: [
          { element_id: 'e-logo', role: 'logo', severity: 'blocking', detail: 'Logo sits outside the safe area.', suggested_fix: 'Move it inside the margins for this channel.' },
          { element_id: 'e-headline', role: 'headline', severity: 'warning', detail: 'Headline sits outside the safe area.', suggested_fix: null },
        ],
      },
    });
    expect(screen.getByText('Blocking')).toBeTruthy();
    expect(screen.getByText('Worth a look')).toBeTruthy();
    expect(screen.getByText('Logo sits outside the safe area.')).toBeTruthy();
    expect(screen.getByText('Move it inside the margins for this channel.')).toBeTruthy();
    expect(screen.getByText('Needs adjustment before it can render')).toBeTruthy();
  });

  it('lets an issue select the element it is about', () => {
    const onSelect = vi.fn();
    panel({
      report: {
        verdict: 'NEEDS_ADJUSTMENT',
        issues: [{ element_id: 'e-logo', role: 'logo', severity: 'blocking', detail: 'x', suggested_fix: null }],
      },
      onSelect,
    });
    fireEvent.click(screen.getByRole('button', { name: 'Logo' }));
    expect(onSelect).toHaveBeenCalledWith('e-logo');
  });

  it('says a layout has not been checked rather than implying it passed', () => {
    panel({ report: null, check: layoutCheck(null), layout: null });
    expect(screen.getByText('Not checked')).toBeTruthy();
  });
});

// ----------------------------------------------------------- the channels

describe('ChannelPicker', () => {
  const picker = (over: Record<string, unknown> = {}) =>
    render(
      <ChannelPicker
        channels={channelViews(composition())}
        busy={false}
        canEdit
        onSwitch={noop}
        onCompose={noop}
        {...over}
      />,
    );

  it('shows a real size only for a channel it has seen one for', () => {
    picker();
    expect(screen.getByText('1:1 · 1080 × 1080')).toBeTruthy();
    // LinkedIn has no layout and no render, so no size is claimed for it.
    expect(screen.getByText('Compose to add')).toBeTruthy();
    expect(screen.queryByText(/1200 × 627/)).toBeNull();
  });

  it('switches to a composed channel and composes an uncomposed one', () => {
    const onSwitch = vi.fn();
    const onCompose = vi.fn();
    picker({ onSwitch, onCompose });
    fireEvent.click(screen.getByRole('button', { name: /Instagram post/ }));
    expect(onSwitch).toHaveBeenCalledWith('instagram_post');
    fireEvent.click(screen.getByRole('button', { name: /LinkedIn/ }));
    expect(onCompose).toHaveBeenCalledWith('linkedin');
  });

  it('announces the open channel with pressed semantics, not colour', () => {
    picker();
    expect(
      screen.getByRole('button', { name: /Instagram post/ }).getAttribute('aria-pressed'),
    ).toBe('true');
    expect(screen.getByRole('button', { name: /LinkedIn/ }).getAttribute('aria-pressed')).toBe(
      'false',
    );
  });

  it('does not call a composed channel uncomposed just because it has no size', () => {
    // `channelViews` learns a size from the open layout and from rendered
    // assets only, so a channel composed elsewhere has none — which is not the
    // same as being uncomposed, and the row's own click handler switches to it.
    const view = composition({
      composed_channels: ['instagram_post', 'instagram_story'],
      available_channels: ['linkedin'],
      final_assets: [],
    });
    picker({ channels: channelViews(view) });
    const story = screen.getByRole('button', { name: /Instagram story/ });
    expect(within(story).getByText(/Composed/)).toBeTruthy();
    expect(within(story).queryByText('Compose to add')).toBeNull();
    // And the uncomposed one still invites composing.
    expect(
      within(screen.getByRole('button', { name: /LinkedIn/ })).getByText('Compose to add'),
    ).toBeTruthy();
  });

  it('does not invite someone without edit rights to compose', () => {
    picker({ canEdit: false });
    expect(screen.getByText('Not composed')).toBeTruthy();
  });
});

// --------------------------------------------------------- render + export

describe('RenderPanel', () => {
  const panel = (over: Record<string, unknown> = {}) =>
    render(
      <RenderPanel
        check={layoutCheck({ verdict: 'PASS', issues: [] })}
        rendering={false}
        busy={false}
        capabilities={admin}
        hasLayout
        onRender={noop}
        error={null}
        {...over}
      />,
    );

  it('offers only the formats the renderer writes', () => {
    panel();
    const group = screen.getByRole('group', { name: 'File format' });
    expect(within(group).getAllByRole('button').map((b) => b.textContent)).toEqual(['PNG', 'JPEG']);
  });

  it('renders in the chosen format', () => {
    const onRender = vi.fn();
    panel({ onRender });
    fireEvent.click(screen.getByRole('button', { name: 'JPEG' }));
    fireEvent.click(screen.getByRole('button', { name: 'Render the JPEG' }));
    expect(onRender).toHaveBeenCalledWith('JPEG');
  });

  it('says it is working rather than going quiet', () => {
    panel({ rendering: true });
    expect(screen.getByText('Creating final asset…')).toBeTruthy();
  });

  it('will not offer a render the server would refuse, and says why', () => {
    panel({
      check: layoutCheck({
        verdict: 'NEEDS_ADJUSTMENT',
        issues: [{ element_id: 'e-logo', role: 'logo', severity: 'blocking', detail: 'x', suggested_fix: null }],
      }),
    });
    const button = screen.getByRole('button', { name: 'Fix the layout before rendering' });
    expect(button.hasAttribute('disabled')).toBe(true);
    expect(screen.getByText(/1 blocking issue/)).toBeTruthy();
  });

  it('says earlier renders are kept', () => {
    panel();
    expect(screen.getByText(/Earlier renders stay exactly as they were/)).toBeTruthy();
  });

  it('shows the server’s reason when a render failed', () => {
    panel({ error: 'The logo asset could not be read.' });
    expect(screen.getByRole('alert').textContent).toBe('The logo asset could not be read.');
  });

  it('offers nothing to someone who cannot edit the campaign', () => {
    panel({ capabilities: viewer });
    expect(screen.getByText(/needs edit rights/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^Render/ })).toBeNull();
  });
});

describe('FinalAssetPanel', () => {
  const panel = (over: Record<string, unknown> = {}) =>
    render(
      <FinalAssetPanel
        asset={finalAsset()}
        layout={layout()}
        campaign="FS-9 Facade Launch"
        brand="Northline Facades"
        market="Mumbai, Maharashtra"
        guardian={{ label: 'Within the brand’s rules', tone: 'positive' }}
        latest
        {...over}
      />,
    );

  it('shows the rendered file through a signed URL', () => {
    panel();
    const img = screen.getByRole('img');
    expect(img.getAttribute('src')).toContain('token=signed-token');
    expect(img.getAttribute('alt')).toMatch(/final instagram post asset/i);
  });

  it('places the deliverable with the provenance stamped on it', () => {
    panel();
    expect(screen.getByText('Northline Facades')).toBeTruthy();
    expect(screen.getByText('Mumbai, Maharashtra')).toBeTruthy();
    expect(screen.getByText('1080 × 1080')).toBeTruthy();
    expect(screen.getByText('image/png')).toBeTruthy();
    expect(screen.getByText('r1')).toBeTruthy();
    expect(screen.getByText('Within the brand’s rules')).toBeTruthy();
  });

  it('downloads through the server-built attachment link', () => {
    panel();
    // `url + '?download=true'` would fold the flag into the signature.
    const link = screen.getByRole('link', { name: /Download the PNG/ });
    expect(link.getAttribute('href')).toContain('download=true');
    expect(link.getAttribute('href')).toContain('token=signed-token');
  });

  it('says when the layout has moved on since the file was made', () => {
    panel({ layout: layout({ version: 4 }) });
    expect(screen.getByText(/layout has changed since this was rendered/)).toBeTruthy();
  });

  it('keeps the campaign’s brand verdict out of the file’s own ledger', () => {
    // Every ledger row is stamped on the file at render time; the brand check
    // is the campaign's current verdict on the selected creative. Inside the
    // same list it read as something this file carries.
    panel();
    const scoped = screen.getByText(/Brand check · the campaign’s selected creative/);
    expect(scoped).toBeTruthy();
    expect(scoped.closest('dl')).toBeNull();
    expect(screen.getByText(/not on this file/)).toBeTruthy();
  });

  it('claims no brand check when none was run', () => {
    panel({ guardian: null });
    expect(screen.queryByText('Brand check')).toBeNull();
  });
});

describe('RenderHistory', () => {
  it('keeps every render, because old files went to clients', () => {
    render(
      <RenderHistory
        assets={[finalAsset({ id: 'f-2', version: 2 }), finalAsset()]}
        selectedId="f-2"
        onSelect={noop}
      />,
    );
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual([
      'instagram post · v2',
      'instagram post · v1',
    ]);
  });

  it('says nothing when there is only one', () => {
    const { container } = render(
      <RenderHistory assets={[finalAsset()]} selectedId="f-1" onSelect={noop} />,
    );
    expect(container.textContent).toBe('');
  });
});

// ------------------------------------------------------------- responsive

describe('CollapsiblePanel', () => {
  it('is a disclosure below the desktop breakpoint, and announces its state', () => {
    render(
      <CollapsiblePanel title="Layers">
        <p>the layers</p>
      </CollapsiblePanel>,
    );
    const toggle = screen.getByRole('button', { name: /Layers/ });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
  });

  it('gives the panel exactly one title', () => {
    // The toggle carries it below `xl` and a plain label carries it at `xl`;
    // rendering it inside the panel as well put it on screen twice on a phone.
    render(
      <CollapsiblePanel title="Layout check">
        <p>body</p>
      </CollapsiblePanel>,
    );
    expect(screen.getAllByText('Layout check')).toHaveLength(2);
  });
});
