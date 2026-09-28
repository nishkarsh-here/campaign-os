/**
 * A fact, with how well it is known.
 *
 * The device that makes trust visible. Campaign OS is a governed system: a
 * proposed brand fact is not a confirmed one, an inferred market is not a
 * stated one, and a campaign gets approved on exactly that difference. So the
 * provenance travels with the value everywhere it is shown, rather than living
 * on a separate "confidence" screen nobody opens.
 *
 * Rendered as a description list because that is what it is — a term and its
 * definition. `<dl>` gives a screen reader the pairing for free, which a grid
 * of divs does not.
 */

import { CONFIDENCE_LABEL, CONFIDENCE_MEANING, type Confidence } from '@/lib/market';
import { cx } from './cx';

/** Colour *and* wording. A marker is never the only signal. */
const CONFIDENCE_TONE: Record<Confidence, string> = {
  stated: 'text-success',
  brand: 'text-info',
  inferred: 'text-warning',
  unrecorded: 'text-muted',
  unknown: 'text-muted',
};

export function FactList({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <dl className={cx('space-y-4', className)}>{children}</dl>;
}

export function Fact({
  label,
  value,
  confidence,
  /** Rendered under the value — a sentence of context, not another fact. */
  note,
}: {
  label: string;
  value: string | null;
  confidence?: Confidence;
  note?: React.ReactNode;
}) {
  const badge = confidence ? CONFIDENCE_LABEL[confidence] : null;
  return (
    <div>
      <dt className="flex flex-wrap items-center gap-2">
        <span className="text-label uppercase text-muted">{label}</span>
        {badge ? (
          <span
            title={confidence ? CONFIDENCE_MEANING[confidence] : undefined}
            className={cx('text-label uppercase', CONFIDENCE_TONE[confidence!])}
          >
            {badge}
          </span>
        ) : null}
      </dt>
      <dd className={cx('mt-1', value ? 'text-body text-ink' : 'text-body text-muted')}>
        {/* An em dash and the reason, never a plausible placeholder. A page
            that fills a gap with an invented value is a page that lies. */}
        {value ?? 'Not known yet'}
      </dd>
      {note ? <dd className="mt-1 text-caption text-muted">{note}</dd> : null}
    </div>
  );
}

/**
 * A counted thing.
 *
 * Every number the product shows must come from data it actually holds, so this
 * takes a `count` that is already `.length` of something real. `of` names what
 * was counted, which is how a reader can tell a derived number from a measured
 * one.
 */
export function Tally({
  count,
  of,
  tone = 'neutral',
}: {
  count: number;
  of: string;
  tone?: 'neutral' | 'accent';
}) {
  return (
    <div>
      <p
        className={cx(
          'text-h2 tabular-nums',
          tone === 'accent' ? 'text-accent' : 'text-ink',
          count === 0 && 'text-muted',
        )}
      >
        {count}
      </p>
      <p className="mt-0.5 text-label uppercase text-muted">{of}</p>
    </div>
  );
}
