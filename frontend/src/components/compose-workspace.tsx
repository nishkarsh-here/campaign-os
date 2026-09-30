'use client';

/**
 * The panels around the composition canvas: what is on it, what is selected,
 * and whether it can be rendered.
 *
 * The canvas cannot be the only way to understand a layout — it is a picture,
 * and a picture is unavailable to a screen reader and unusable at 375px. So the
 * layer list is a real list with real names, the inspector is real form
 * controls with real labels, and the layout check is real prose. Every one of
 * them is operable without ever touching the canvas.
 *
 * Vocabulary is the reader's: "Horizontal position", not `x`. The spec's own
 * field names are available behind a disclosure, for the person who needs to
 * compare what they see with what the API returned.
 */

import { useId, useState } from 'react';
import {
  Card,
  Field,
  Input,
  Select,
  StatusBadge,
  Textarea,
  cx,
} from '@/components/ui';
import type { ElementEdit, LayoutElementView, LayoutIssueView, LayoutSpecView } from '@/lib/api';
import type { Capabilities } from '@/lib/capabilities';
import {
  STANDING_MEANING,
  channelViews,
  editableFields,
  elementName,
  groupIssues,
  hasLock,
  isLocked,
  issuesFor,
  locksFor,
  percent,
  pixels,
  quantise,
  standing,
  type ChannelView,
  type LayoutCheck,
} from '@/lib/compose';

// -------------------------------------------------------------- the layers

/**
 * Everything on the canvas, topmost first.
 *
 * Ordered by `z` descending, which is how a person looking at the picture reads
 * it — the thing in front is the thing they clicked. A hidden element stays in
 * the list, because "where did my subhead go" is exactly the question this
 * panel exists to answer.
 */
export function LayerList({
  layout,
  report,
  selectedId,
  onSelect,
}: {
  layout: LayoutSpecView;
  report: { issues: LayoutIssueView[] } | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const ordered = [...layout.elements].sort((a, b) => b.z - a.z);
  return (
    <div>
      <ul className="space-y-1">
        {ordered.map((element) => {
          const issues = issuesFor(report, element.id);
          const blocking = issues.some((i) => i.severity === 'blocking');
          const where = standing(element, layout.safe_area);
          return (
            <li key={element.id}>
              <button
                type="button"
                aria-pressed={element.id === selectedId}
                onClick={() => onSelect(element.id)}
                className={cx(
                  'flex w-full items-center gap-2 rounded-md border px-3 py-2 text-left transition-colors duration-fast',
                  element.id === selectedId
                    ? 'border-accent/60 bg-accent/5'
                    : 'border-transparent hover:border-line hover:bg-line/20',
                )}
              >
                <span className="min-w-0 flex-1 truncate text-small">
                  {elementName(element)}
                </span>
                {hasLock(element) ? (
                  <span className="text-caption text-muted" title="Has a protected property">
                    {/* A word as well as the mark, for a screen reader. */}
                    <span aria-hidden="true">🔒</span>
                    <span className="sr-only">Protected</span>
                  </span>
                ) : null}
                {!element.visible ? (
                  <span className="text-label uppercase text-muted">Hidden</span>
                ) : null}
                {issues.length ? (
                  <StatusBadge tone={blocking ? 'negative' : 'caution'}>
                    {blocking ? 'Blocking' : 'Note'}
                  </StatusBadge>
                ) : where === 'outside-safe' ? (
                  <StatusBadge tone="caution">Outside</StatusBadge>
                ) : null}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ------------------------------------------------------------ the inspector

interface InspectorProps {
  layout: LayoutSpecView;
  element: LayoutElementView;
  report: { issues: LayoutIssueView[] } | null;
  busy: boolean;
  capabilities: Capabilities;
  onEdit: (elementId: string, edit: ElementEdit) => void;
  /**
   * Bumped by the page after every edit resolves, accepted or refused.
   *
   * The uncontrolled fields key off it so a rejected value cannot stay on
   * screen pretending to be the layout's.
   */
  attempt: number;
}

/**
 * The selected element, and every property the server will actually accept.
 *
 * A control appears only when `editableFields` says the server takes it, so
 * there is no knob here that quietly does nothing. A *locked* property is shown
 * and disabled with the reason beside it, because hiding it would leave a person
 * hunting for a control that is deliberately absent.
 */
export function Inspector({
  layout,
  element,
  report,
  busy,
  capabilities,
  onEdit,
  attempt,
}: InspectorProps) {
  const fields = editableFields(element);
  const locks = locksFor(element);
  const issues = issuesFor(report, element.id);
  const where = standing(element, layout.safe_area);
  const canEdit = capabilities.can('edit_campaign');
  const id = useId();

  /**
   * A geometry control, committed on blur rather than on every keystroke.
   *
   * Each accepted edit writes a **new layout version** on the server, so
   * committing per keystroke would turn typing "12" into two versions — one of
   * them for the intermediate value 1 — and spam the history a person relies on
   * to see what actually changed.
   *
   * `key` carries the stored value *and* `attempt`, which the page increments
   * after every edit resolves. The stored value alone was not enough: a refused
   * edit leaves it unchanged, so the field never re-mounted and went on showing
   * a number the layout does not have — beside a pixel readout computed from
   * the number it does.
   */
  const number = (
    label: string,
    field: 'x' | 'y' | 'width' | 'height',
    value: number,
    extent: number,
  ) => (
    <Field key={field} label={label}>
      <div className="flex items-center gap-2">
        <Input
          key={`${element.id}-${field}-${value}-${attempt}`}
          type="number"
          // `x`/`y` are `ge=0` but `width`/`height` are `gt=0` on
          // `ElementEditRequest`, so a zero here is a 422 rather than a flat
          // element.
          min={field === 'width' || field === 'height' ? 0.1 : 0}
          max={100}
          step={0.5}
          disabled={!canEdit || busy}
          defaultValue={Math.round(value * 1000) / 10}
          onBlur={(event) => {
            const next = Number(event.target.value) / 100;
            if (!Number.isFinite(next) || quantise(next) === quantise(value)) return;
            onEdit(element.id, { [field]: quantise(next) });
          }}
        />
        <span className="shrink-0 text-caption text-muted">
          % · {pixels(value, extent)}px
        </span>
      </div>
    </Field>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-h3">{elementName(element)}</h3>
        <StatusBadge tone={STANDING_MEANING[where].tone}>
          {STANDING_MEANING[where].label}
        </StatusBadge>
      </div>

      {/* What the server said about this element, in its own words. */}
      {issues.length ? (
        <div role="alert" className="rounded-md border border-line p-3">
          {issues.map((issue) => (
            <div key={issue.detail} className="text-small">
              <p className={issue.severity === 'blocking' ? 'text-danger' : 'text-warning'}>
                {issue.detail}
              </p>
              {issue.suggested_fix ? (
                <p className="mt-0.5 text-caption text-muted">{issue.suggested_fix}</p>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}

      {/* Locks first: the answer to "why can I not change this?" should be
          above the controls, not discovered after trying. */}
      {locks.length ? (
        <div className="rounded-md border border-info/40 bg-info/5 p-3">
          <p className="text-label uppercase text-info">Protected element</p>
          <ul className="mt-1.5 space-y-1">
            {locks.map((lock) => (
              <li key={lock.field} className="text-caption text-muted">
                {lock.reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {fields.has('content') ? (
        <Field label="Text">
          <Textarea
            // Uncontrolled, so it needs a key: without one, selecting a
            // different text element left the previous element's words in the
            // box, and blurring would have written them onto the new one.
            key={`${element.id}-content-${attempt}`}
            rows={2}
            // The endpoint refuses content over 300 characters.
            maxLength={300}
            disabled={!canEdit || busy || isLocked(element, 'content')}
            defaultValue={element.content ?? ''}
            onBlur={(event) => {
              const next = event.target.value;
              if (next !== element.content) onEdit(element.id, { content: next });
            }}
          />
        </Field>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        {number('Horizontal position', 'x', element.box.x, layout.width)}
        {number('Vertical position', 'y', element.box.y, layout.height)}
        {number('Width', 'width', element.box.width, layout.width)}
        {number('Height', 'height', element.box.height, layout.height)}
      </div>

      {fields.has('size') && element.text_style ? (
        <Field label="Text size">
          <div className="flex items-center gap-2">
            <Input
              key={`${element.id}-size-${element.text_style.size}-${attempt}`}
              type="number"
              min={0.5}
              max={40}
              step={0.5}
              disabled={!canEdit || busy}
              defaultValue={Math.round(element.text_style.size * 1000) / 10}
              onBlur={(event) => {
                const next = Number(event.target.value) / 100;
                const current = element.text_style?.size ?? 0;
                if (!Number.isFinite(next) || quantise(next) === quantise(current)) return;
                onEdit(element.id, { size: quantise(next) });
              }}
            />
            <span className="shrink-0 text-caption text-muted">
              % of height · {pixels(element.text_style.size, layout.height)}px
            </span>
          </div>
        </Field>
      ) : null}

      {fields.has('align') && element.text_style ? (
        <Field label="Alignment">
          <Select
            disabled={!canEdit || busy}
            value={element.text_style.align}
            onChange={(event) => onEdit(element.id, { align: event.target.value })}
          >
            <option value="left">Left</option>
            <option value="center">Centre</option>
            <option value="right">Right</option>
          </Select>
        </Field>
      ) : null}

      {fields.has('color') && element.text_style ? (
        <Field label="Colour">
          <div className="flex items-center gap-2">
            <input
              id={`${id}-color`}
              aria-label="Colour"
              type="color"
              disabled={!canEdit || busy}
              // A colour picker fires continuously while it is dragged, and
              // every accepted edit is a new layout version. Committed when the
              // control is done with, like the number fields.
              defaultValue={element.text_style.color}
              key={`${element.id}-color-${element.text_style.color}-${attempt}`}
              onBlur={(event) => {
                if (event.target.value.toUpperCase() === element.text_style?.color.toUpperCase()) {
                  return;
                }
                onEdit(element.id, { color: event.target.value });
              }}
              className="h-9 w-12 shrink-0 rounded border border-line bg-transparent"
            />
            <span className="font-mono text-caption text-muted">{element.text_style.color}</span>
          </div>
        </Field>
      ) : null}

      <div className="flex flex-wrap items-center gap-4">
        {fields.has('uppercase') && element.text_style ? (
          <label className="flex items-center gap-2 text-small">
            <input
              type="checkbox"
              disabled={!canEdit || busy}
              checked={element.text_style.uppercase}
              onChange={(event) => onEdit(element.id, { uppercase: event.target.checked })}
            />
            Capitals
          </label>
        ) : null}

        <label className="flex items-center gap-2 text-small">
          <input
            type="checkbox"
            disabled={!canEdit || busy || isLocked(element, 'visible')}
            checked={element.visible}
            onChange={(event) => onEdit(element.id, { visible: event.target.checked })}
          />
          Visible
        </label>
      </div>

      {/* The spec as the API returned it, for the person comparing the two. */}
      <details className="group border-t border-line pt-3">
        <summary className="cursor-pointer list-none text-label uppercase text-muted transition-colors duration-fast hover:text-ink">
          <span className="group-open:hidden">Layout values →</span>
          <span className="hidden group-open:inline">Hide layout values ↑</span>
        </summary>
        <dl className="mt-3 space-y-1.5">
          {[
            ['id', element.id],
            ['type', element.type],
            ['role', element.role ?? '—'],
            ['anchor', element.box.anchor],
            ['z', String(element.z)],
            [
              'box',
              `x ${percent(element.box.x)}, y ${percent(element.box.y)}, w ${percent(element.box.width)}, h ${percent(element.box.height)}`,
            ],
          ].map(([key, value]) => (
            <div key={key} className="flex justify-between gap-3">
              <dt className="text-caption text-muted">{key}</dt>
              <dd className="truncate font-mono text-caption" title={value}>
                {value}
              </dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  );
}

// ------------------------------------------------------------- the check

/**
 * Whether this layout can be rendered, and what stands in the way.
 *
 * Every sentence is `validate_layout`'s. The panel adds grouping and an
 * affordance to select the element an issue is about; it composes no prose of
 * its own, and there is no check here the server does not perform.
 */
export function LayoutCheckPanel({
  check,
  report,
  layout,
  onSelect,
}: {
  check: LayoutCheck;
  report: { issues: LayoutIssueView[] } | null;
  layout: LayoutSpecView | null;
  onSelect: (id: string) => void;
}) {
  const groups = groupIssues(report, layout);
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StatusBadge tone={check.tone}>{check.label}</StatusBadge>
      </div>

      {check.unknown ? (
        <p className="mt-2 text-caption text-muted">
          No layout has been composed for this channel yet.
        </p>
      ) : groups.length === 0 ? (
        <p className="mt-2 text-caption text-muted">
          Every element is on the canvas and inside the safe area.
        </p>
      ) : (
        <ul className="mt-3 space-y-3">
          {groups.map((group) => (
            <li key={group.element?.id ?? 'canvas'}>
              {group.element ? (
                <button
                  type="button"
                  onClick={() => onSelect(group.element!.id)}
                  className="text-small font-medium underline decoration-dotted underline-offset-2 hover:text-accent"
                >
                  {group.subject}
                </button>
              ) : (
                <p className="text-small font-medium">{group.subject}</p>
              )}
              {group.issues.map((issue) => (
                <div key={issue.detail} className="mt-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge tone={issue.severity === 'blocking' ? 'negative' : 'caution'}>
                      {issue.severity === 'blocking' ? 'Blocking' : 'Worth a look'}
                    </StatusBadge>
                  </div>
                  <p className="mt-1 text-caption text-muted">{issue.detail}</p>
                  {issue.suggested_fix ? (
                    <p className="text-caption text-muted">{issue.suggested_fix}</p>
                  ) : null}
                </div>
              ))}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ----------------------------------------------------------- the channels

/**
 * The frames this campaign can be composed for.
 *
 * A size is shown only for a channel the app has really seen one for — from a
 * layout or a rendered asset. `CHANNEL_DIMENSIONS` is a backend constant no
 * endpoint publishes, so an uncomposed channel says "size known once composed"
 * rather than a number this screen guessed.
 */
export function ChannelPicker({
  channels,
  busy,
  canEdit,
  onSwitch,
  onCompose,
}: {
  channels: ChannelView[];
  busy: boolean;
  canEdit: boolean;
  onSwitch: (channel: ChannelView['channel']) => void;
  onCompose: (channel: ChannelView['channel']) => void;
}) {
  return (
    <div>
      <ul className="space-y-1.5">
        {channels.map((channel) => (
          <li key={channel.channel}>
            <button
              type="button"
              aria-pressed={channel.current}
              disabled={busy}
              onClick={() =>
                channel.composed ? onSwitch(channel.channel) : onCompose(channel.channel)
              }
              className={cx(
                'flex w-full flex-wrap items-center gap-x-2 gap-y-1 rounded-md border px-3 py-2 text-left transition-colors duration-fast disabled:opacity-50',
                channel.current
                  ? 'border-accent/60 bg-accent/5'
                  : 'border-line hover:border-accent/40',
              )}
            >
              <span className="min-w-0 flex-1 truncate text-small">{channel.label}</span>
              {/*
                Two independent facts, and they were conflated: whether the
                channel is composed (`composed_channels`) and whether this
                screen has ever seen its pixel size. A channel composed in
                another tab but not yet opened or rendered has no size here —
                labelling it "Compose to add" contradicted both the API and this
                row's own click handler, which switches to it.
              */}
              {channel.width && channel.height ? (
                <span className="text-caption text-muted">
                  {channel.ratio} · {channel.width} × {channel.height}
                </span>
              ) : channel.composed ? (
                <span className="text-caption text-muted">Composed · open it for its size</span>
              ) : (
                <span className="text-caption text-muted">
                  {canEdit ? 'Compose to add' : 'Not composed'}
                </span>
              )}
              {channel.renders ? (
                <span className="text-label uppercase text-muted">
                  {channel.renders} render{channel.renders === 1 ? '' : 's'}
                </span>
              ) : null}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * A panel that becomes a sheet below the desktop breakpoint.
 *
 * Three columns do not fit on a phone, and stacking them turns the canvas into
 * a strip above a wall of controls. So on small screens the layers and the
 * inspector collapse into disclosures the canvas sits above, and open as sheets
 * over it — the work stays the largest thing on screen at every width.
 */
export function CollapsiblePanel({
  title,
  children,
  defaultOpen = false,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Card padding={false} className="xl:border-0 xl:bg-transparent">
      {/* Below `xl` the title is the control that opens the panel; at `xl` it
          is a plain label. One title either way — rendering it here *and*
          inside the panel put "Layout check" on screen twice on a phone. */}
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left xl:hidden"
      >
        <span className="text-label uppercase text-muted">{title}</span>
        <span aria-hidden="true" className="text-muted">
          {open ? '−' : '+'}
        </span>
      </button>
      <p className="hidden text-label uppercase text-muted xl:block">{title}</p>
      <div className={cx('px-4 pb-4 xl:mt-3 xl:block xl:px-0 xl:pb-0', open ? 'block' : 'hidden')}>
        {children}
      </div>
    </Card>
  );
}
