/**
 * The original home of the state primitives, kept as the public path.
 *
 * Thirteen pages and four components import `EmptyState`, `ErrorState`,
 * `SkeletonRows`, `StatusBadge` and `Tone` from here. The implementations moved
 * into `components/ui/` when the design system was introduced in UI-1; this
 * re-export means that move cost no churn and no risk across seventeen call
 * sites. New code should import from `@/components/ui`.
 */

export { EmptyState, ErrorState, Skeleton, SkeletonRows } from '@/components/ui/states';
export { StatusBadge, type Tone } from '@/components/ui/badge';
