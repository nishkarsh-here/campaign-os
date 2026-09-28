/**
 * The panel.
 *
 * `rounded-lg border border-line p-5` appears 32 times across the application,
 * character for character. That is not a pattern worth abstracting for its own
 * sake — it is a pattern that has already been copied 32 times and will be
 * copied again, and each copy is a place a future padding change has to find.
 *
 * `padding={false}` exists because five of those panels wrap a list or a table
 * that supplies its own spacing, and the alternative — a second component, or
 * a `className` that fights `p-5` — is worse.
 */

import { cx } from './cx';

export interface CardProps extends React.HTMLAttributes<HTMLElement> {
  /** `false` when the content owns its own padding, e.g. a divided list. */
  padding?: boolean;
  /** Lifts the panel off the page for genuinely layered content. */
  elevated?: boolean;
  as?: 'div' | 'section' | 'article' | 'li';
}

export function Card({
  padding = true,
  elevated = false,
  as: Tag = 'div',
  className,
  ...rest
}: CardProps) {
  return (
    <Tag
      className={cx(
        'rounded-lg border border-line',
        elevated ? 'bg-raised shadow-elevated' : 'bg-card',
        padding && 'p-5',
        className,
      )}
      {...rest}
    />
  );
}

/**
 * A heading with optional supporting text and trailing controls.
 *
 * The application's 40 `<h2>` elements were split 27/11 between
 * `text-sm font-semibold` and `text-sm font-medium` — two weights for one level,
 * which is how a hierarchy stops communicating rank. This settles it in one
 * place.
 *
 * `level` is a prop rather than a fixed tag because heading rank is a document
 * structure decision that belongs to the page, not to the component: a section
 * inside a section needs `h3`, and hard-coding `h2` is how pages end up with an
 * outline that skips levels.
 */
/** Rank to element and type step, so the two can never disagree. */
const HEADING = {
  1: { tag: 'h1', size: 'text-h1' },
  2: { tag: 'h2', size: 'text-h2' },
  3: { tag: 'h3', size: 'text-h3' },
} as const;

export function SectionHeader({
  title,
  description,
  actions,
  level = 2,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  level?: 1 | 2 | 3;
  className?: string;
}) {
  const { tag: Heading, size } = HEADING[level];
  return (
    <div className={cx('flex flex-wrap items-baseline justify-between gap-3', className)}>
      <div className="min-w-0">
        <Heading className={size}>{title}</Heading>
        {description ? <p className="mt-1 text-small text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}
