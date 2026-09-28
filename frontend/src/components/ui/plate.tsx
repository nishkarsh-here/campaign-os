'use client';

/**
 * A generated visual, in its own shape, with an honest failure.
 *
 * Three screens show the same thing — generate, evaluate and the brand review
 * — and each needs the same three properties, so it is one component rather
 * than three copies:
 *
 * 1. **Its own aspect ratio**, from the asset's real pixel dimensions, so a 4:5
 *    portrait is framed 4:5 and a story 9:16. Never one thumbnail box for
 *    everything.
 * 2. **Alt text that says what the picture is** and where it came from, because
 *    "image" tells a screen-reader user nothing they could act on.
 * 3. **A stated failure when the bytes do not arrive.** Left alone, a broken
 *    `<img>` renders as its own alt text in a box, which reads like a caption
 *    on a picture that is simply dark. It matters most on the brand review: a
 *    verdict beside an image nobody can see is a judgement about something the
 *    reader cannot check, and it has to say so.
 *
 * This is not the place to solve *why* bytes may not arrive. The API serves
 * them from an organization-scoped route that an `<img src>` cannot send a
 * header to; that is recorded as a backend gap, not worked around here.
 */

import { useState } from 'react';
import { cx } from './cx';

export interface PlateProps {
  src: string;
  alt: string;
  /** A CSS `aspect-ratio`, or null when the asset reported no usable size. */
  ratio: string | null;
  /** Rendered when there is no asset at all — a different thing from a failure. */
  className?: string;
}

export function Plate({ src, alt, ratio, className }: PlateProps) {
  const [failed, setFailed] = useState(false);

  return (
    <figure className={cx('m-0', className)}>
      <div
        className="relative flex items-center justify-center overflow-hidden bg-line/30"
        style={{ aspectRatio: ratio ?? '4 / 5' }}
      >
        {failed ? (
          // Said plainly, and not styled as a caption: nothing is being
          // described here, because there is nothing on screen to describe.
          <div className="px-4 text-center">
            <p className="text-label uppercase text-muted">Visual could not be loaded</p>
            <p className="mt-1.5 text-caption text-muted">
              The image exists but its bytes did not arrive.
            </p>
          </div>
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={src}
            alt={alt}
            onError={() => setFailed(true)}
            className="plate-image h-full w-full object-cover"
          />
        )}
      </div>
    </figure>
  );
}

/** No asset at all. Not a failure — there is simply nothing to show yet. */
export function PlateAbsent({ label }: { label: string }) {
  return (
    <div className="flex h-full min-h-[12rem] items-center justify-center bg-line/20">
      <p className="text-label uppercase text-muted">{label}</p>
    </div>
  );
}
