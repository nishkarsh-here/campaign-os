/**
 * Loading, empty and error states.
 *
 * Centralised because `UI_SPEC.md §Design principles` requires all four states
 * on every async surface, and a screen missing one is unfinished. Making them
 * components makes forgetting one visible in review.
 */

import { buttonStyles } from './button';
import { cx } from './cx';

/**
 * A pulsing placeholder for content that is on its way.
 *
 * `aria-busy` with a label, so a screen reader is told the region is loading
 * rather than told nothing. The pulse itself is suppressed under
 * `prefers-reduced-motion` by the global rule in globals.css.
 */
export function SkeletonRows({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div className={cx('space-y-3', className)} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-16 animate-pulse rounded-lg border border-line bg-line/30" />
      ))}
    </div>
  );
}

/** A single pulsing block, for a heading or a value rather than a row. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <span
      aria-busy="true"
      className={cx('block animate-pulse rounded-sm bg-line/50', className ?? 'h-4 w-24')}
    />
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-dashed border-line p-6 text-center sm:p-10">
      <h3 className="text-h3">{title}</h3>
      <p className="mx-auto mt-1 max-w-md text-body text-muted">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  title = 'Something went wrong',
  message,
  requestId,
  onRetry,
  code,
}: {
  title?: string;
  message: string;
  requestId?: string;
  onRetry?: () => void;
  /**
   * The API's error code, where the caller has one.
   *
   * Only `FORBIDDEN` changes anything: a permission failure is not a fault to
   * retry, and offering "Try again" on one teaches people that the button is
   * decorative. It gets its own title and a way out instead.
   */
  code?: string;
}) {
  const forbidden = code === 'FORBIDDEN';
  return (
    // `role="alert"` so the failure is announced, not just drawn. The left
    // border is a second, non-colour-dependent cue that this block is a
    // problem rather than content.
    <div role="alert" className="rounded-lg border border-line border-l-2 border-l-danger bg-card p-5">
      <h3 className="text-h3">{forbidden ? 'You do not have access to this' : title}</h3>
      {/* The backend's message is already written for a person and carries no
          internals — `AppError.detail` is log-side only and never serialised. */}
      <p className="mt-1 text-body text-muted">{message}</p>
      {forbidden ? (
        <p className="mt-2 text-body text-muted">
          You are signed in, but this workspace or action is not available to your account. Ask an
          administrator if you think that is wrong.
        </p>
      ) : null}
      {requestId ? (
        // Surfaced so a user can quote it and we can find the exact request.
        <p className="mt-2 font-mono text-caption text-muted">request {requestId}</p>
      ) : null}
      {forbidden ? (
        // A way out, rather than a dead end the browser's back button has to
        // rescue. Never a route that would simply fail the same way.
        <a href="/app" className={buttonStyles('secondary', 'md', 'mt-4')}>
          Back to your workspace
        </a>
      ) : onRetry ? (
        <button type="button" onClick={onRetry} className={buttonStyles('secondary', 'md', 'mt-4')}>
          Try again
        </button>
      ) : null}
    </div>
  );
}
