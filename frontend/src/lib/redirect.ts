/**
 * Where to send someone after they sign in.
 *
 * Lives here rather than beside the sign-in page because Next's App Router
 * permits only a fixed set of exports from a `page.tsx`, and because a rule
 * this security-relevant deserves to be importable and testable on its own.
 */

/** Where a sign-in lands when nothing better is known. */
export const DEFAULT_DESTINATION = '/app';

/**
 * Only same-origin application paths are honoured.
 *
 * `next` arrives from the query string, which anyone can write. Redirecting to
 * whatever it says would turn the sign-in page into an open redirect — a
 * phishing primitive that borrows this domain's credibility to land someone
 * somewhere else. An allowlist of "starts with `/app`, and is not
 * protocol-relative" is the whole rule, and it fails closed.
 */
export function safeDestination(next: string | null | undefined): string {
  if (!next) return DEFAULT_DESTINATION;
  // `//evil.example` is a protocol-relative URL: it starts with a slash and
  // still leaves the origin.
  if (next.startsWith('//')) return DEFAULT_DESTINATION;
  if (!next.startsWith('/app')) return DEFAULT_DESTINATION;
  return next;
}
