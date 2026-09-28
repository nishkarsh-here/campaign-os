'use client';

/**
 * The Meridian — the campaign journey, drawn.
 *
 * The product's signature navigation and its answer to "where am I?". Not
 * tabs: a single line with nodes on it, in the order the product runs them, so
 * the whole path is visible at once — what is done, what is current, what is
 * next, what is blocked.
 *
 * It lives in the campaign route's `layout.tsx`, which means it does not
 * unmount when a person moves between stages. That is the difference between
 * persistent navigation and navigation that happens to appear on every page.
 *
 * Vertical from `lg` up; below that a horizontal scroller that keeps the
 * current node in view. That is a different arrangement, not a narrower one.
 *
 * Accessibility, since this replaces browser-back as the way around:
 *   - a real `<nav>` wrapping an ordered list, because the order is meaning;
 *   - `aria-current="step"` on the current node;
 *   - each link's accessible name carries its state — "Generate, blocked" —
 *     so the marker's fill is never the only place the state lives;
 *   - a blocked node is still a link. The backend decides what a stage will
 *     accept; a person is allowed to look at one that is not ready. Refusing
 *     navigation here is how the one-way flow the audit found came about.
 */

import { useEffect, useRef } from 'react';
import Link from 'next/link';
import { NODE_STATE_LABEL, type NodeState, type ResolvedNode } from '@/lib/nav';
import { cx } from './cx';

/**
 * How each state draws its node.
 *
 * Shape and fill differ as well as colour — a hollow dashed ring reads as
 * "not open to you" in greyscale, which a colour change alone does not.
 */
const MARKER: Record<NodeState, string> = {
  DONE: 'border-success bg-success',
  RUNNING: 'border-info bg-info/30 animate-pulse',
  ATTENTION: 'border-warning bg-warning/20',
  FAILED: 'border-danger bg-danger',
  PENDING: 'border-line bg-surface',
  BLOCKED: 'border-muted/50 border-dashed bg-surface',
  available: 'border-line bg-surface',
};

/** The rail's own text treatment per state, so the label agrees with the dot. */
const LABEL_TONE: Record<NodeState, string> = {
  DONE: 'text-ink',
  RUNNING: 'text-ink',
  ATTENTION: 'text-ink',
  FAILED: 'text-danger',
  PENDING: 'text-muted',
  BLOCKED: 'text-muted',
  available: 'text-muted',
};

export function Meridian({
  nodes,
  currentId,
  className,
}: {
  nodes: readonly ResolvedNode[];
  currentId: string | null;
  className?: string;
}) {
  const scroller = useRef<HTMLOListElement>(null);

  // On a phone the current node can start off-screen. Instant rather than
  // smooth: this is positioning, not a flourish, and a smooth scroll on mount
  // reads as the page moving under the reader.
  useEffect(() => {
    const el = scroller.current?.querySelector('[data-current="true"]');
    el?.scrollIntoView({ block: 'nearest', inline: 'center' });
  }, [currentId]);

  return (
    <nav aria-label="Campaign stages" className={className}>
      <ol
        ref={scroller}
        className={cx(
          'relative flex gap-1 overflow-x-auto pb-2',
          // The horizontal rule sits behind the markers on small screens…
          'before:absolute before:left-4 before:right-4 before:top-[15px] before:h-px before:bg-line before:content-[""]',
          // …and becomes a vertical one from `lg`, where the rail is a column.
          'lg:flex-col lg:gap-0 lg:overflow-visible lg:pb-0',
          'lg:before:left-[15px] lg:before:right-auto lg:before:top-4 lg:before:bottom-4 lg:before:h-auto lg:before:w-px',
        )}
      >
        {nodes.map((node, i) => {
          const current = node.id === currentId;
          return (
            <li key={node.id} className="relative shrink-0 lg:shrink">
              <Link
                href={node.href}
                data-current={current}
                aria-current={current ? 'step' : undefined}
                className={cx(
                  'group flex w-24 flex-col items-center gap-1.5 rounded-md px-1 py-1 text-center',
                  'transition-colors duration-fast ease-out hover:bg-line/30',
                  // From `lg` the node becomes a row: marker, then label and
                  // purpose beside it.
                  'lg:w-full lg:flex-row lg:items-start lg:gap-3 lg:px-2 lg:py-2.5 lg:text-left',
                  current && 'bg-line/40 lg:bg-line/30',
                )}
              >
                {/*
                 * The marker. `bg-surface` on the hollow states is what stops
                 * the rule behind it showing through the middle of the dot.
                 * `relative` lifts it above the `before:` line.
                 */}
                <span
                  aria-hidden="true"
                  className={cx(
                    'relative mt-0 flex h-[15px] w-[15px] shrink-0 items-center justify-center rounded-full border-2 lg:mt-0.5',
                    MARKER[node.state],
                    current && 'ring-2 ring-accent ring-offset-2 ring-offset-surface',
                  )}
                >
                  {/* A number, because the order is part of the information —
                      and it keeps the marker legible when printed. */}
                  <span className="sr-only">{i + 1}</span>
                </span>

                <span className="min-w-0 lg:flex-1">
                  <span
                    className={cx(
                      'block truncate text-caption font-medium lg:text-body',
                      LABEL_TONE[node.state],
                      current && 'text-ink',
                    )}
                  >
                    {node.label}
                  </span>
                  {/*
                   * State in words, for everyone — not a tooltip, and not
                   * carried by the marker's colour. Hidden visually on the
                   * narrow rail where there is no room, but never hidden from
                   * assistive technology: it is part of the link's name below.
                   */}
                  <span className="mt-0.5 hidden text-label uppercase text-muted lg:block">
                    {NODE_STATE_LABEL[node.state]}
                  </span>
                </span>

                {/* The accessible name. Appended so a screen reader hears
                    "Generate, blocked" while the eye reads the two as
                    separate lines. */}
                <span className="sr-only lg:hidden">, {NODE_STATE_LABEL[node.state]}</span>
              </Link>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
