/**
 * Join class names, dropping anything falsy.
 *
 * Small enough to own rather than depend on: the primitives need conditional
 * classes and `clsx` would be a dependency for eleven lines.
 */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}
