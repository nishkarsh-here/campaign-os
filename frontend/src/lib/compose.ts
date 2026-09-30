/**
 * Reading the composition stage: the layout, its geometry, and what may move.
 *
 * ## What the editor actually edits
 *
 * A `LayoutSpec`, never an image. The rendered PNG is an *output* of the spec
 * (ADR-006, ADR-014), produced by a deterministic Pillow renderer on the
 * server. Every control changes a number in the spec and the server re-derives
 * the picture — which is what makes an edit reversible, a channel variant free,
 * and a render reproducible.
 *
 * Geometry is normalised: `x`, `y`, `width`, `height` are fractions of the
 * canvas, and text `size` is a fraction of canvas *height*. Nothing here
 * converts to pixels except for drawing, and nothing sends pixels back.
 *
 * ## Two things it is careful about
 *
 * **The server is the authority on whether a layout is valid.** `PATCH
 * /composition` runs `validate_layout` and *refuses the whole edit* when
 * anything blocking results — it does not save a broken layout with a warning.
 * So the canvas shows the last accepted state, and a refusal is reported in the
 * server's own words. The geometry this module computes while dragging is
 * arithmetic about rectangles the layout already carries, offered as a preview
 * of what the check will say, and labelled as exactly that.
 *
 * **What is locked is derived from data, and the refusal is the truth.** An
 * element's `type` and `role` are projected; the rules that make the call to
 * action, the legal line and the logo special are backend constants this module
 * mirrors, because the composition API publishes no per-element capability
 * descriptor. The mirror drives an affordance — a padlock, an explanation — and
 * never a claim: if it ever disagrees with the server, the server's rejection is
 * what the user sees.
 */

import type {
  BoxView,
  Channel,
  CompositionView,
  ElementEdit,
  FinalAssetView,
  LayoutElementView,
  LayoutIssueView,
  LayoutSpecView,
  SafeAreaView,
} from '@/lib/api';
import { CHANNEL_LABELS } from '@/lib/api';
import type { Tone } from '@/components/ui';

// ------------------------------------------------------------------ elements

/**
 * What an element is, for a person.
 *
 * Read from `role` first and `type` second, because that is the order the
 * renderer thinks in: a text element's role is what it *is*, and the type only
 * says how it is drawn. An unrecognised role falls through to the type rather
 * than being guessed at.
 */
export function elementName(element: LayoutElementView): string {
  switch (element.role) {
    case 'headline':
      return 'Headline';
    case 'subhead':
      return 'Subheadline';
    case 'cta':
      return 'Call to action';
    case 'legal':
      return 'Legal line';
    case 'eyebrow':
      return 'Eyebrow';
    default:
      break;
  }
  switch (element.type) {
    case 'logo':
      return 'Logo';
    case 'image':
      return 'Image';
    case 'shape':
      // The builder's one shape is the band drawn behind the copy so it stays
      // legible over any plate. Naming it "Shape" would tell a reader nothing.
      return 'Text backdrop';
    default:
      return 'Text';
  }
}

/**
 * The fields the server accepts for this element.
 *
 * Mirrors `_editable_fields` in `composition_stage.py`: position and visibility
 * for everything, the type controls only where there is a `text_style` to
 * change. Offering a size control on a logo would be a control that quietly
 * does nothing.
 */
export function editableFields(element: LayoutElementView): Set<keyof ElementEdit> {
  const common: (keyof ElementEdit)[] = ['visible', 'x', 'y', 'width', 'height'];
  if (element.type === 'text' && element.text_style) {
    return new Set<keyof ElementEdit>([
      ...common,
      'content',
      'size',
      'align',
      'color',
      'uppercase',
    ]);
  }
  return new Set(common);
}

export interface Lock {
  /** What cannot be done. */
  field: keyof ElementEdit;
  /** Why, in the user's words — and where to do it instead. */
  reason: string;
}

/**
 * What this element will not let a person change, and why.
 *
 * Mirrors three backend rules the composition API does not publish:
 * `PROTECTED_ROLES` (`cta`, `legal`), the call-to-action content guard, and the
 * logo visibility guard. Each is an affordance *plus an explanation* — never a
 * disabled control with no sentence, which leaves a person believing the tool
 * is broken rather than that the rule exists.
 */
export function locksFor(element: LayoutElementView): Lock[] {
  const locks: Lock[] = [];
  if (element.role === 'cta') {
    locks.push({
      field: 'content',
      reason:
        'The call to action is an approved campaign fact. Change the words through a revision, not in the layout.',
    });
  }
  if (element.role === 'legal') {
    locks.push({
      field: 'content',
      reason: 'The legal line comes from the Brand Brain and cannot be edited here.',
    });
  }
  if (element.type === 'logo') {
    locks.push({
      field: 'visible',
      reason:
        'A branded asset without the brand is not a deliverable, so the logo cannot be hidden.',
    });
  }
  return locks;
}

export function isLocked(element: LayoutElementView, field: keyof ElementEdit): boolean {
  return locksFor(element).some((lock) => lock.field === field);
}

/** True when anything about this element is protected — drives the padlock. */
export function hasLock(element: LayoutElementView): boolean {
  return locksFor(element).length > 0;
}

// ------------------------------------------------------------------ geometry

export interface Rect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/**
 * A box's edges as fractions.
 *
 * Read as top-left because that is the only anchor the layout builder emits.
 * `anchor` is carried through to the advanced view rather than reinterpreted —
 * guessing at a centre anchor would move every element on screen by half its
 * own size relative to where the renderer puts it.
 */
export function bounds(box: BoxView): Rect {
  return { left: box.x, top: box.y, right: box.x + box.width, bottom: box.y + box.height };
}

/** The safe area as a rectangle in the same fractional space as a box. */
export function safeRect(safe: SafeAreaView): Rect {
  return { left: safe.left, top: safe.top, right: 1 - safe.right, bottom: 1 - safe.bottom };
}

/**
 * Element types the safe area governs.
 *
 * Mirrors `_CONTENT_TYPES`: a scrim band is *meant* to run edge to edge and the
 * plate is *meant* to fill the frame, so flagging backdrop would put a warning
 * on every correct layout the builder produces — which teaches people to ignore
 * the panel, and is worse than not warning at all.
 */
const CONTENT_TYPES = new Set(['text', 'logo']);

export type Standing = 'safe' | 'outside-safe' | 'off-canvas' | 'not-governed' | 'hidden';

/**
 * Where a box sits relative to the canvas and the safe area.
 *
 * Arithmetic about two rectangles the layout already carries, not a rule
 * invented here — which is what makes it honest to show *while dragging*,
 * before the server has been asked. The server's own report stays the
 * authority and is presented as such.
 */
export function standing(
  element: LayoutElementView,
  safe: SafeAreaView,
  box?: BoxView,
): Standing {
  // `validate_layout` evaluates only visible elements, so a hidden one has no
  // standing to report. It matters: the builder's legal line is hidden *and*
  // sits below the safe area by construction, so judging it would put a caution
  // badge on every layout whose brand has a legal line — next to a panel saying
  // everything is inside the margins.
  if (!element.visible) return 'hidden';
  const b = bounds(box ?? element.box);
  if (b.right > 1.0001 || b.bottom > 1.0001 || b.left < -0.0001 || b.top < -0.0001) {
    return 'off-canvas';
  }
  if (!CONTENT_TYPES.has(element.type)) return 'not-governed';
  const s = safeRect(safe);
  const outside =
    b.left < s.left - 0.0001 ||
    b.top < s.top - 0.0001 ||
    b.right > s.right + 0.0001 ||
    b.bottom > s.bottom + 0.0001;
  return outside ? 'outside-safe' : 'safe';
}

export const STANDING_MEANING: Record<Standing, { label: string; tone: Tone }> = {
  safe: { label: 'Inside the safe area', tone: 'positive' },
  'outside-safe': { label: 'Outside the safe area', tone: 'caution' },
  'off-canvas': { label: 'Past the canvas edge', tone: 'negative' },
  'not-governed': { label: 'Backdrop — the margins do not apply', tone: 'neutral' },
  hidden: { label: 'Hidden — not checked', tone: 'neutral' },
};

/**
 * Keep a proposed box on the canvas.
 *
 * `Box` refuses a rectangle that leaves the artboard, so a drag that ran past
 * the edge would be rejected wholesale by the server. Clamping here keeps a
 * drag continuous instead of dropping the element back to where it started —
 * and the clamp is the *same* rule the model enforces, not a softer one.
 */
export function clampToCanvas(box: BoxView): BoxView {
  const width = Math.min(Math.max(box.width, 0.01), 1);
  const height = Math.min(Math.max(box.height, 0.01), 1);
  return {
    ...box,
    width,
    height,
    x: Math.min(Math.max(box.x, 0), 1 - width),
    y: Math.min(Math.max(box.y, 0), 1 - height),
  };
}

/**
 * Fractions rounded to what the renderer meaningfully distinguishes.
 *
 * A 1080px canvas cannot express more than about four decimal places, and
 * sending eleven makes a diff between two versions unreadable for no gain.
 */
export function quantise(value: number): number {
  return Math.round(value * 10_000) / 10_000;
}

/** A fraction as a percentage, for a reader. */
export function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/** A fraction of the canvas as real pixels, which is what a designer checks. */
export function pixels(fraction: number, extent: number): number {
  return Math.round(fraction * extent);
}

// ------------------------------------------------------------------- issues

export interface IssueGroup {
  element: LayoutElementView | null;
  /** The element's name, or the canvas when the issue belongs to no element. */
  subject: string;
  issues: LayoutIssueView[];
}

/**
 * The layout check, grouped by what it is about.
 *
 * Blocking first: those are the ones that stop a render. Every sentence is the
 * server's own — `detail` and `suggested_fix` are already written for a user,
 * and nothing is composed here.
 */
export function groupIssues(
  report: { issues: LayoutIssueView[] } | null,
  layout: LayoutSpecView | null,
): IssueGroup[] {
  const issues = report?.issues ?? [];
  if (!issues.length) return [];
  const rank = (issue: LayoutIssueView) => (issue.severity === 'blocking' ? 0 : 1);
  const ordered = [...issues].sort((a, b) => rank(a) - rank(b));
  const groups = new Map<string, IssueGroup>();
  for (const issue of ordered) {
    const key = issue.element_id ?? '__canvas__';
    const element = layout?.elements.find((e) => e.id === issue.element_id) ?? null;
    const existing = groups.get(key);
    if (existing) {
      existing.issues.push(issue);
      continue;
    }
    groups.set(key, {
      element,
      subject: element ? elementName(element) : 'The canvas',
      issues: [issue],
    });
  }
  return [...groups.values()];
}

/** Issues the check raised about one element, for its row and its inspector. */
export function issuesFor(
  report: { issues: LayoutIssueView[] } | null,
  elementId: string,
): LayoutIssueView[] {
  return (report?.issues ?? []).filter((issue) => issue.element_id === elementId);
}

export interface LayoutCheck {
  label: string;
  tone: Tone;
  /** True when a render would be refused. */
  blocked: boolean;
  blocking: number;
  warnings: number;
  /** True when no check has been run — different from "it passed". */
  unknown: boolean;
}

/**
 * Whether this layout can be rendered.
 *
 * The verdict is computed by the server from the layout's own geometry, so
 * there is nothing to second-guess — but "no report" and "PASS" are different
 * states and the screen says which.
 */
export function layoutCheck(report: CompositionView['report']): LayoutCheck {
  if (!report) {
    return {
      label: 'Not checked',
      tone: 'neutral',
      blocked: false,
      blocking: 0,
      warnings: 0,
      unknown: true,
    };
  }
  const blocking = report.issues.filter((i) => i.severity === 'blocking').length;
  const warnings = report.issues.filter((i) => i.severity === 'warning').length;
  if (report.verdict === 'PASS') {
    return {
      label: warnings ? 'Ready to render, with notes' : 'Ready to render',
      tone: warnings ? 'caution' : 'positive',
      blocked: false,
      blocking,
      warnings,
      unknown: false,
    };
  }
  return {
    label: 'Needs adjustment before it can render',
    tone: 'negative',
    blocked: true,
    blocking,
    warnings,
    unknown: false,
  };
}

// ------------------------------------------------------------------ channels

export interface ChannelView {
  channel: Channel;
  label: string;
  /** Real pixels, where the app has actually seen them. Null otherwise. */
  width: number | null;
  height: number | null;
  /** "4:5", from real dimensions — never assumed from the channel's name. */
  ratio: string | null;
  composed: boolean;
  /** How many deliverables this channel has rendered. */
  renders: number;
  current: boolean;
}

function gcd(a: number, b: number): number {
  return b === 0 ? a : gcd(b, a % b);
}

/** An aspect ratio from real pixels — "1080 × 1350" becomes "4:5". */
export function aspectLabel(width: number, height: number): string | null {
  if (!width || !height) return null;
  const divisor = gcd(width, height) || 1;
  return `${width / divisor}:${height / divisor}`;
}

/**
 * Every channel this campaign may compose, with what is really known of it.
 *
 * **`available_channels` is `COMPOSABLE_CHANNELS` minus the composed ones**, so
 * it is what you could still *add* — not the whole set. Reading it alone would
 * hide every channel the campaign has already composed, which is most of the
 * ones a person wants to switch to. The union of the two lists is the composable
 * set, derived rather than restated.
 *
 * Dimensions come from a layout or a rendered asset the app has actually seen.
 * A channel with neither reports none: `CHANNEL_DIMENSIONS` lives in the
 * backend domain and no endpoint publishes it, so a size shown for an
 * uncomposed channel would be a number this app invented. Composing the channel
 * is what makes its real size known, and the picker says so.
 */
export function channelViews(view: CompositionView | null): ChannelView[] {
  if (!view) return [];
  const composed = new Set(view.composed_channels);
  // Order by the product's own channel vocabulary, so the picker does not
  // reshuffle when the database returns the composed ones in another order.
  const order = Object.keys(CHANNEL_LABELS) as Channel[];
  const all = [...new Set([...view.composed_channels, ...view.available_channels])].sort(
    (a, b) => order.indexOf(a) - order.indexOf(b),
  );
  const sizes = new Map<Channel, { width: number; height: number }>();
  if (view.layout) {
    sizes.set(view.layout.channel, { width: view.layout.width, height: view.layout.height });
  }
  for (const asset of view.final_assets) {
    if (!sizes.has(asset.channel)) {
      sizes.set(asset.channel, { width: asset.width, height: asset.height });
    }
  }
  const renders = new Map<Channel, number>();
  for (const asset of view.final_assets) {
    renders.set(asset.channel, (renders.get(asset.channel) ?? 0) + 1);
  }

  return all.map((channel) => {
    const size = sizes.get(channel) ?? null;
    return {
      channel,
      label: CHANNEL_LABELS[channel] ?? channel,
      width: size?.width ?? null,
      height: size?.height ?? null,
      ratio: size ? aspectLabel(size.width, size.height) : null,
      composed: composed.has(channel),
      renders: renders.get(channel) ?? 0,
      current: channel === view.channel,
    };
  });
}

// -------------------------------------------------------------- channel copy

export type CopyOrigin = 'tailored' | 'inherited' | 'locked';

export interface ChannelCopyLine {
  role: string;
  label: string;
  text: string;
  origin: CopyOrigin;
}

/**
 * Where this channel's words came from, in M11's own vocabulary.
 *
 * An override is a sparse diff: absent means inherit. The layout carries the
 * *resolved* text, so the comparison that says "tailored" is against the
 * specification's default — and the call to action is reported as locked
 * whatever its source, because that is the rule a person needs to know.
 */
export function channelCopy(
  layout: LayoutSpecView | null,
  defaults: { headline?: string | null; subhead?: string | null; cta?: string | null },
): ChannelCopyLine[] {
  if (!layout) return [];
  const lines: ChannelCopyLine[] = [];
  for (const role of ['headline', 'subhead', 'cta'] as const) {
    const element = layout.elements.find((e) => e.role === role);
    if (!element?.content) continue;
    const fallback = defaults[role]?.trim() ?? null;
    const origin: CopyOrigin =
      role === 'cta'
        ? 'locked'
        : fallback && element.content.trim() !== fallback
          ? 'tailored'
          : 'inherited';
    lines.push({ role, label: elementName(element), text: element.content, origin });
  }
  return lines;
}

export const ORIGIN_MEANING: Record<CopyOrigin, { label: string; tone: Tone }> = {
  tailored: { label: 'Tailored', tone: 'active' },
  inherited: { label: 'Inherits', tone: 'neutral' },
  locked: { label: 'Locked', tone: 'caution' },
};

// -------------------------------------------------------------- final assets

export interface FinalAssetFacts {
  rows: { label: string; value: string }[];
  /** Set when the layout has moved on since this file was rendered. */
  supersededBy: number | null;
}

/**
 * A rendered deliverable's provenance, from the fields it actually carries.
 *
 * Every one of these is stamped on the asset at render time, which is what
 * makes a file in a folder traceable at all. Nothing is read from the campaign's
 * current state: an asset that has gone to a client keeps saying what it said.
 */
export function finalAssetFacts(
  asset: FinalAssetView,
  layout: LayoutSpecView | null,
): FinalAssetFacts {
  const rows: { label: string; value: string }[] = [
    { label: 'Channel', value: CHANNEL_LABELS[asset.channel] ?? asset.channel },
    { label: 'Size', value: `${asset.width} × ${asset.height}` },
  ];
  const ratio = aspectLabel(asset.width, asset.height);
  if (ratio) rows.push({ label: 'Aspect ratio', value: ratio });
  rows.push(
    { label: 'Format', value: asset.mime_type },
    { label: 'Deliverable version', value: `v${asset.version}` },
    { label: 'Built from layout', value: `v${asset.layout_version}` },
    { label: 'Creative plan', value: `v${asset.specification_version}` },
    { label: 'Renderer', value: asset.renderer_version },
  );
  if (asset.size_bytes) {
    rows.push({ label: 'File size', value: `${Math.round(asset.size_bytes / 1024)} KB` });
  }
  return {
    rows,
    supersededBy: layout && layout.version > asset.layout_version ? layout.version : null,
  };
}

/**
 * The formats `POST /composition/render` actually accepts.
 *
 * Two, because the renderer writes two. PDF and print production are not built
 * and the API refuses the print channels outright, so no third option is
 * offered here.
 */
export const EXPORT_FORMATS: { format: 'PNG' | 'JPEG'; label: string; detail: string }[] = [
  { format: 'PNG', label: 'PNG', detail: 'Lossless. The default for screen delivery.' },
  { format: 'JPEG', label: 'JPEG', detail: 'Smaller file, no transparency.' },
];
