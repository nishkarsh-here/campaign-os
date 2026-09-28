/**
 * The frontend test harness.
 *
 * Two kinds of test live here, and they want different environments:
 *
 *  - The authentication modules (`session.ts`, the request path in `api.ts`) are
 *    plain logic. They run in `node` with `fetch` and `localStorage` stubbed,
 *    which is what keeps them deterministic and offline — a test that reached a
 *    real Supabase project would fail on a train and pass in CI.
 *  - The UI primitives need a DOM to assert against. Those files opt into jsdom
 *    with a `@vitest-environment jsdom` docblock at the top rather than the
 *    whole suite paying for it, and rather than a config-level glob — vitest 3
 *    deprecated `environmentMatchGlobs`, and a per-file declaration is visible
 *    to whoever opens the file.
 *
 * Neither kind touches the network, a database, or a running Next server.
 */

import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  // `tsconfig.json` sets `jsx: "preserve"` because Next owns the JSX transform
  // in the application build. vitest has no Next pipeline, so it has to be told
  // which transform to use; without this, component tests fail on a bare
  // `React is not defined`.
  esbuild: { jsx: 'automatic', jsxImportSource: 'react' },
  resolve: {
    // Mirrors the `@/*` path alias in tsconfig, so tests import modules the
    // same way the application does.
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'node',
    // `.tsx` as well as `.ts`, now that components are under test.
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    setupFiles: ['./vitest.setup.ts'],
    globals: false,
  },
});
