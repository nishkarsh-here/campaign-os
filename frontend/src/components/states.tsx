/**
 * Loading, empty and error states.
 *
 * Centralised because `UI_SPEC.md §Design principles` requires all four states
 * on every async surface, and a screen missing one is unfinished. Making them
 * components makes forgetting one visible in review.
 */

/**
 * The one tone scale in the product.
 *
 * Every screen was inventing its own emerald/amber/red classes, which is how
 * "passed" ends up looking different on two pages. Colour is never the only
 * signal — each badge carries a word as well, because a colour-blind reader
 * and a greyscale projector are both real.
 */
export type Tone = 'positive' | 'caution' | 'negative' | 'neutral' | 'active';

const TONE_CLASSES: Record<Tone, string> = {
  positive: 'border-emerald-500/50 text-emerald-400',
  caution: 'border-amber-500/50 text-amber-400',
  negative: 'border-red-500/50 text-red-400',
  active: 'border-sky-500/50 text-sky-400',
  neutral: 'border-line text-muted',
};

export function StatusBadge({
  tone = 'neutral',
  children,
  title,
}: {
  tone?: Tone;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}

export function SkeletonRows({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-16 animate-pulse rounded-lg border border-line bg-line/30" />
      ))}
    </div>
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
    <div className="rounded-lg border border-dashed border-line p-10 text-center">
      <h3 className="text-base font-medium">{title}</h3>
      <p className="mx-auto mt-1 max-w-md text-sm text-muted">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  title = 'Something went wrong',
  message,
  requestId,
  onRetry,
}: {
  title?: string;
  message: string;
  requestId?: string;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className="rounded-lg border border-line bg-line/20 p-6">
      <h3 className="text-base font-medium">{title}</h3>
      <p className="mt-1 text-sm text-muted">{message}</p>
      {requestId ? (
        // Surfaced so a user can quote it and we can find the exact request.
        <p className="mt-2 font-mono text-xs text-muted">request {requestId}</p>
      ) : null}
      {onRetry ? (
        <button
          onClick={onRetry}
          className="mt-4 rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40"
        >
          Try again
        </button>
      ) : null}
    </div>
  );
}
