/**
 * Status, said in a way that survives a greyscale projector.
 *
 * The tone scale itself is unchanged — five tones, and every badge carries a
 * word as well as a colour, because a colour-blind reader and a
 * washed-out lecture-hall projector are both real. What changed is where the
 * colours come from.
 *
 * They used to be Tailwind's `emerald-400`, `amber-400`, `red-400` and
 * `sky-400`, hard-coded across 99 class usages in thirteen files. Those are
 * dark-background shades: on this product's light theme (`--surface` is
 * near-white) the 400-weight green lands at roughly 1.8:1, well under the
 * 4.5:1 floor — a status word a light-mode reader genuinely cannot read. The
 * tokens resolve per theme, so the same `tone="positive"` is legible on both.
 */

import { cx } from './cx';

export type Tone = 'positive' | 'caution' | 'negative' | 'neutral' | 'active';

const TONE_CLASSES: Record<Tone, string> = {
  positive: 'border-success/40 bg-success/10 text-success',
  caution: 'border-warning/40 bg-warning/10 text-warning',
  negative: 'border-danger/40 bg-danger/10 text-danger',
  active: 'border-info/40 bg-info/10 text-info',
  neutral: 'border-line bg-line/30 text-muted',
};

export function StatusBadge({
  tone = 'neutral',
  children,
  title,
  className,
}: {
  tone?: Tone;
  children: React.ReactNode;
  /** A tooltip is a supplement, never the only place the meaning lives. */
  title?: string;
  className?: string;
}) {
  return (
    <span
      title={title}
      className={cx(
        'inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-label uppercase',
        TONE_CLASSES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/**
 * A neutral, squared-off counterpart for counts and plain labels — a version
 * number or "3 assets" is not a status and should not borrow status colour.
 */
export function Badge({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cx(
        'inline-flex shrink-0 items-center rounded-sm border border-line bg-line/30 px-1.5 py-0.5 text-label uppercase text-muted',
        className,
      )}
    >
      {children}
    </span>
  );
}
