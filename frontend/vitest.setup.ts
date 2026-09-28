/**
 * Test setup.
 *
 * Only one thing is global: unmounting React trees between tests. Left mounted,
 * a previous test's DOM stays in `document.body` and the next `getByRole` query
 * finds two matching elements — a failure that reads as a component bug and is
 * not one.
 *
 * Guarded because this file also loads for the node-environment auth tests,
 * where there is no DOM to clean and `@testing-library/react` must not be
 * pulled in.
 */

import { afterEach } from 'vitest';

afterEach(async () => {
  if (typeof document === 'undefined') return;
  const { cleanup } = await import('@testing-library/react');
  cleanup();
});
