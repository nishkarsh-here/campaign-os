/**
 * Motion primitives.
 *
 * Deliberately CSS, not a motion library. Everything in
 * `docs/UI_UX_VISION.md` §7 is a transition or a keyframe: content arriving,
 * a list staggering in, a line drawing forward. None of that needs a
 * layout-animation engine, and adding one before a surface needs it is how a
 * bundle grows without anyone deciding to grow it.
 *
 * Framer Motion gets adopted at the first surface that genuinely needs
 * orchestrated or shared-element animation — the Home hero sequence in UI-2B is
 * the expected trigger.
 *
 * Reduced motion needs no handling here: the global rule in `globals.css`
 * collapses every animation and transition in the product, and `.arrive`
 * carries an explicit end state for that case.
 */

import { cx } from './cx';

/** Delay between consecutive items in a staggered list. */
const STAGGER_MS = 30;
/**
 * Beyond this many items the stagger stops accumulating.
 *
 * At 30ms a list of forty would keep the last item hidden for 1.2 seconds,
 * which stops being a flourish and becomes a wait.
 */
const STAGGER_CAP = 8;

export interface RevealProps extends React.HTMLAttributes<HTMLElement> {
  /** Position in a list; drives the stagger delay. */
  index?: number;
  as?: 'div' | 'li' | 'section' | 'article';
}

/**
 * Content arriving.
 *
 * `index` staggers a list without each caller computing a delay. The element
 * renders in its final position in the DOM immediately — only opacity and a
 * 6px offset animate — so nothing here affects layout, and a screen reader
 * sees the finished content regardless of where the animation is.
 */
export function Reveal({ index = 0, as: Tag = 'div', className, style, ...rest }: RevealProps) {
  const delay = Math.min(index, STAGGER_CAP) * STAGGER_MS;
  return (
    <Tag
      className={cx('arrive', className)}
      style={{ animationDelay: delay ? `${delay}ms` : undefined, ...style }}
      {...rest}
    />
  );
}
