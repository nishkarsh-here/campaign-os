/**
 * The place stamp — where a campaign runs, set like a cartographic legend.
 *
 * Hyperlocalization is the product's reason to exist and it was previously a
 * form field three clicks deep. This renders it identically everywhere it
 * appears — workspace header, campaign card, beside a generated visual — so a
 * person learns to read it at a glance instead of re-parsing it per screen.
 *
 * ```
 * JAIPUR, RAJASTHAN · HINDI + ENGLISH · HOT SEASON, MARCH TO JUNE
 * ```
 *
 * Every part is optional and absent parts are simply not drawn, because these
 * are the real shapes of the data: `region` and `timing_occasion` are nullable
 * and `language` has a default. Nothing is substituted for a missing value —
 * an invented "India" would be a claim the specification never made.
 *
 * A note on what this is *not*. `region` is one free-text string
 * (`"Jaipur, Rajasthan"`), not structured city and state, and `language` is one
 * string (`"Hindi + English"`), not a list. This component displays them; it
 * must never parse them into structure the domain does not have. See
 * `docs/UI_UX_VISION.md` §5.
 */

import { displayLanguage } from '@/lib/market';
import { cx } from './cx';

export interface PlaceStampProps {
  region?: string | null;
  language?: string | null;
  /** Season or occasion — `specification.timing_occasion`. */
  occasion?: string | null;
  className?: string;
  /** `full` adds the occasion; `compact` is place and language only. */
  detail?: 'compact' | 'full';
}

export function PlaceStamp({
  region,
  language,
  occasion,
  className,
  detail = 'compact',
}: PlaceStampProps) {
  const parts = [region, displayLanguage(language), detail === 'full' ? occasion : null]
    .map((p) => p?.trim())
    .filter((p): p is string => Boolean(p));

  // Nothing known yet. Silence is the honest answer — a stamp reading
  // "Unknown · Unknown" is worse than no stamp.
  if (parts.length === 0) return null;

  return (
    <p
      className={cx('flex flex-wrap items-center gap-x-2 gap-y-1 text-label uppercase', className)}
    >
      {/* The label names what this row is, once, for a screen reader. Sighted
          readers get it from the consistent position and treatment. */}
      <span className="sr-only">Market:</span>
      {parts.map((part, i) => (
        <span key={part} className="flex items-center gap-2">
          {/* The separator is decorative and `aria-hidden`, but it is still
              ink on a page: at `text-muted/60` it measured 2.4:1, and "it is
              only a separator" is not a contrast exemption worth taking. */}
          {i > 0 ? (
            <span aria-hidden="true" className="text-muted">
              ·
            </span>
          ) : null}
          <span className={i === 0 ? 'text-ink' : 'text-muted'}>{part}</span>
        </span>
      ))}
    </p>
  );
}
