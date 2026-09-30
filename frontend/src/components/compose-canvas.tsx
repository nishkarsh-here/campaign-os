'use client';

/**
 * The composition canvas — a preview of a `LayoutSpec`, not the deliverable.
 *
 * ## What this draws, and what it is not
 *
 * Every rectangle here is `element.box`, read as fractions of the canvas, and
 * every text size is `text_style.size` as a fraction of canvas *height*. So the
 * canvas is a faithful picture of the geometry the server will render from —
 * and deliberately not a picture of the output. Line breaking, font hinting and
 * the scrim's exact alpha are the Pillow renderer's, and the browser cannot
 * reproduce them. The screen says `Preview` for that reason, and the final
 * asset is what the server returns.
 *
 * Sizes use container-query units (`1cqh` = 1% of the canvas's own height), so
 * a headline set at `0.075` is 7.5% of the frame at every breakpoint with no
 * resize listener and no pixel state that could drift from the spec.
 *
 * ## Direct manipulation
 *
 * A drag updates a local draft box and nothing else. On release the draft goes
 * to `PATCH /composition`, which re-validates and may refuse the whole edit —
 * so the canvas is never the thing that decides a layout is acceptable. While
 * dragging, the outline colour reflects `standing()`, which is arithmetic about
 * two rectangles the layout already carries, not a rule invented here.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { cx } from '@/components/ui';
import type { BoxView, LayoutElementView, LayoutSpecView } from '@/lib/api';
import {
  bounds,
  clampToCanvas,
  elementName,
  quantise,
  safeRect,
  standing,
  type Standing,
} from '@/lib/compose';

/** How far an arrow key nudges a selected element, as a fraction. */
const NUDGE = 0.005;
const NUDGE_FAST = 0.05;

const OUTLINE: Record<Standing, string> = {
  safe: 'outline-success',
  'outside-safe': 'outline-warning',
  'off-canvas': 'outline-danger',
  'not-governed': 'outline-accent',
  hidden: 'outline-accent',
};

export interface ComposeCanvasProps {
  layout: LayoutSpecView;
  /** Signed URL for the generated plate, resolved from `source_asset_id`. */
  plateUrl: string | null;
  /** Signed URL for the brand's logo asset. */
  logoUrl: string | null;
  selectedId: string | null;
  onSelect: (elementId: string | null) => void;
  /** Commit a moved or resized box. The server re-validates and may refuse. */
  onCommit: (elementId: string, box: BoxView) => void;
  canEdit: boolean;
  /** Ids the layout check has something to say about. */
  flagged: Set<string>;
}

export function ComposeCanvas({
  layout,
  plateUrl,
  logoUrl,
  selectedId,
  onSelect,
  onCommit,
  canEdit,
  flagged,
}: ComposeCanvasProps) {
  const frame = useRef<HTMLDivElement | null>(null);
  /** Abandons an in-flight drag. Held so unmount can call it. */
  const teardown = useRef<(() => void) | null>(null);
  /** The box being dragged, in fractions. Null when nothing is in flight. */
  const [draft, setDraft] = useState<{ id: string; box: BoxView } | null>(null);
  const [plateFailed, setPlateFailed] = useState(false);

  const boxOf = useCallback(
    (element: LayoutElementView): BoxView =>
      draft && draft.id === element.id ? draft.box : element.box,
    [draft],
  );

  /** Pointer delta as a fraction of the rendered frame. */
  const fractionOf = useCallback((dxPx: number, dyPx: number) => {
    const rect = frame.current?.getBoundingClientRect();
    if (!rect || !rect.width || !rect.height) return { dx: 0, dy: 0 };
    return { dx: dxPx / rect.width, dy: dyPx / rect.height };
  }, []);

  const drag = useCallback(
    (element: LayoutElementView, mode: 'move' | 'resize') =>
      (event: React.PointerEvent) => {
        if (!canEdit) return;
        event.preventDefault();
        event.stopPropagation();
        onSelect(element.id);
        const origin = { x: event.clientX, y: event.clientY };
        const start = element.box;
        const target = event.currentTarget as HTMLElement;
        // Optional on both sides: pointer capture keeps a drag tracking when
        // the cursor leaves the element, and an environment without it should
        // still move the element rather than throw on the first press.
        target.setPointerCapture?.(event.pointerId);

        const move = (moveEvent: PointerEvent) => {
          const { dx, dy } = fractionOf(
            moveEvent.clientX - origin.x,
            moveEvent.clientY - origin.y,
          );
          const next =
            mode === 'move'
              ? { ...start, x: start.x + dx, y: start.y + dy }
              : { ...start, width: start.width + dx, height: start.height + dy };
          setDraft({ id: element.id, box: clampToCanvas(next) });
        };

        const detach = () => {
          target.releasePointerCapture?.(event.pointerId);
          window.removeEventListener('pointermove', move);
          window.removeEventListener('pointerup', up);
          window.removeEventListener('pointercancel', cancel);
          teardown.current = null;
        };

        function up() {
          detach();
          setDraft((current) => {
            if (current && current.id === element.id && changed(current.box, start)) {
              onCommit(element.id, current.box);
            }
            return null;
          });
        }

        /**
         * The pointer was taken away — a touch interrupted by a system gesture,
         * or the browser deciding the gesture is a scroll.
         *
         * Without this the listeners stayed on `window`, so the element kept
         * following every later stray move and never committed. The drag is
         * abandoned rather than saved: the user did not finish it.
         */
        function cancel() {
          detach();
          setDraft(null);
        }

        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
        window.addEventListener('pointercancel', cancel);
        // So an unmount mid-drag — switching channel, say — does not leave
        // listeners on `window` calling into a component that is gone.
        teardown.current = cancel;
      },
    [canEdit, fractionOf, onCommit, onSelect],
  );

  /** Arrow keys move the selection — the canvas cannot be mouse-only. */
  const onKeyDown = useCallback(
    (element: LayoutElementView) => (event: React.KeyboardEvent) => {
      const step = event.shiftKey ? NUDGE_FAST : NUDGE;
      const delta: Record<string, [number, number]> = {
        ArrowLeft: [-step, 0],
        ArrowRight: [step, 0],
        ArrowUp: [0, -step],
        ArrowDown: [0, step],
      };
      const move = delta[event.key];
      if (move && canEdit) {
        event.preventDefault();
        const next = clampToCanvas({
          ...element.box,
          x: element.box.x + move[0],
          y: element.box.y + move[1],
        });
        onCommit(element.id, next);
        return;
      }
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onSelect(element.id);
      }
    },
    [canEdit, onCommit, onSelect],
  );

  // Clicking the frame itself clears the selection, which is how a person
  // gets out of an inspector without hunting for a close button.
  const clearSelection = useCallback(() => onSelect(null), [onSelect]);

  useEffect(() => setPlateFailed(false), [plateUrl]);

  // A drag in flight when this unmounts would otherwise keep its `window`
  // listeners and call `setDraft` on a component that no longer exists.
  useEffect(() => () => teardown.current?.(), []);

  const safe = safeRect(layout.safe_area);
  const ordered = [...layout.elements].filter((e) => e.visible).sort((a, b) => a.z - b.z);

  return (
    <div
      ref={frame}
      className="compose-canvas relative w-full select-none overflow-hidden rounded-lg border border-line shadow-elevated"
      style={{
        aspectRatio: `${layout.width} / ${layout.height}`,
        background: layout.background_color,
      }}
      onPointerDown={clearSelection}
    >
      {/* ------------------------------------------------------ the plate */}
      {plateUrl && !plateFailed ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={plateUrl}
          alt=""
          aria-hidden="true"
          onError={() => setPlateFailed(true)}
          className="absolute inset-0 h-full w-full object-cover"
        />
      ) : null}
      {plateUrl && plateFailed ? (
        <p className="absolute left-1/2 top-4 -translate-x-1/2 rounded bg-surface/90 px-2 py-1 text-caption text-muted">
          The visual could not be loaded. The renderer uses the stored plate.
        </p>
      ) : null}

      {/* --------------------------------------------------- the elements */}
      {ordered.map((element) => {
        const box = boxOf(element);
        const b = bounds(box);
        const selected = element.id === selectedId;
        const where = standing(element, layout.safe_area, box);
        const style = element.text_style;

        return (
          <div
            key={element.id}
            role="button"
            tabIndex={0}
            aria-label={`${elementName(element)}${selected ? ', selected' : ''}`}
            aria-pressed={selected}
            onPointerDown={drag(element, 'move')}
            onKeyDown={onKeyDown(element)}
            onFocus={() => onSelect(element.id)}
            className={cx(
              'absolute cursor-move outline-offset-2',
              selected ? cx('outline outline-2', OUTLINE[where]) : 'outline-none',
              !selected && flagged.has(element.id) && 'outline-dashed outline-2 outline-warning/70',
              canEdit ? 'cursor-move' : 'cursor-default',
            )}
            style={{
              left: `${b.left * 100}%`,
              top: `${b.top * 100}%`,
              width: `${box.width * 100}%`,
              height: `${box.height * 100}%`,
              zIndex: element.z,
            }}
          >
            {element.type === 'shape' ? (
              <div
                className="h-full w-full"
                style={{
                  background: element.fill ?? 'transparent',
                  opacity: element.opacity,
                  borderRadius: `${element.radius * 100}%`,
                }}
              />
            ) : null}

            {element.type === 'logo' ? (
              logoUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={logoUrl}
                  alt=""
                  aria-hidden="true"
                  // Centred, and `contain`, because that is what the renderer
                  // does: `_draw_logo` thumbnails the mark into the box and
                  // centres it on both axes, deliberately ignoring `fit`.
                  // Right-aligning here drew the logo up to ~70px from where
                  // the file puts it — against the very safe-area guide a
                  // person drags to.
                  className="h-full w-full object-contain"
                />
              ) : (
                // The brand has a logo — the layout carries its key — but this
                // screen could not resolve a URL for it. Said plainly rather
                // than drawn as a placeholder mark.
                <div className="flex h-full w-full items-center justify-center rounded border border-dashed border-white/40">
                  <span className="text-[8px] uppercase tracking-wide text-white/70">Logo</span>
                </div>
              )
            ) : null}

            {element.type === 'text' && style ? (
              <p
                className="m-0 h-full w-full overflow-hidden"
                style={{
                  // `1cqh` is one percent of the canvas's own height, which is
                  // exactly what `size` means to the renderer.
                  fontSize: `calc(${style.size} * 100cqh)`,
                  lineHeight: style.line_height,
                  letterSpacing: `${style.letter_spacing}em`,
                  color: style.color,
                  textAlign: style.align as 'left' | 'center' | 'right',
                  fontWeight: style.font_weight === 'bold' ? 700 : 400,
                  textTransform: style.uppercase ? 'uppercase' : 'none',
                  background: style.scrim
                    ? `rgb(0 0 0 / ${style.scrim_opacity})`
                    : undefined,
                  display: '-webkit-box',
                  WebkitLineClamp: style.max_lines,
                  WebkitBoxOrient: 'vertical',
                }}
              >
                {element.content}
              </p>
            ) : null}

            {/* A resize grip, only where an edit could be accepted. */}
            {selected && canEdit ? (
              <span
                role="presentation"
                onPointerDown={drag(element, 'resize')}
                className="absolute -bottom-1.5 -right-1.5 h-3 w-3 cursor-nwse-resize rounded-sm border border-surface bg-accent"
              />
            ) : null}
          </div>
        );
      })}

      {/* ------------------------------------------------- the safe area */}
      {/* Drawn last so it reads over the work, and `pointer-events-none` so it
          never intercepts a drag. The margins are the layout's own. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute border border-dashed border-white/45"
        style={{
          // `safeRect` gives edge *positions* (right: 0.94); CSS `right` wants
          // the inset from that edge, which is what is left over.
          left: `${safe.left * 100}%`,
          top: `${safe.top * 100}%`,
          right: `${(1 - safe.right) * 100}%`,
          bottom: `${(1 - safe.bottom) * 100}%`,
          zIndex: 999,
        }}
      />
    </div>
  );
}

function changed(a: BoxView, b: BoxView): boolean {
  return (
    quantise(a.x) !== quantise(b.x) ||
    quantise(a.y) !== quantise(b.y) ||
    quantise(a.width) !== quantise(b.width) ||
    quantise(a.height) !== quantise(b.height)
  );
}
