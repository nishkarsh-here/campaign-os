/**
 * ESLint, flat config.
 *
 * The audit found `npm run lint` present in `package.json`, `eslint` and
 * `eslint-config-next` both installed and pinned, and **no configuration file**
 * — so the script had never run. This is that file and nothing else: no new
 * dependency, no version change, and `@eslint/eslintrc` is already in the tree
 * as ESLint 9's own.
 *
 * `eslint-config-next` 15.5.4 is still eslintrc-shaped (`main: index.js`, no
 * flat export), so `FlatCompat` translates it. That is the approach Next.js
 * documents for ESLint 9 and it keeps the config the project already declared
 * rather than substituting a hand-picked rule set.
 *
 * **Scoped to what it can say something useful about.** The repository is thirteen
 * screens of existing, reviewed, type-checked code; `tsc --noEmit` under `strict`
 * plus `noUncheckedIndexedAccess` already covers the ground a type-aware lint
 * would, and vitest covers behaviour. So this adds the two things neither can
 * see — Next.js's own correctness rules and `jsx-a11y` — and deliberately does
 * not turn on a stylistic set that would produce hundreds of findings nobody
 * asked for. A lint run whose output people learn to scroll past is worse than
 * no lint run.
 */

import { dirname } from 'path';
import { fileURLToPath } from 'url';
import { FlatCompat } from '@eslint/eslintrc';

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

export default [
  {
    ignores: ['.next/**', 'node_modules/**', 'next-env.d.ts', 'src/lib/api-types.ts'],
  },
  ...compat.extends('next/core-web-vitals'),
  {
    rules: {
      // This config is a module that exports an array, which is the shape
      // ESLint requires of it. Same for `postcss.config.mjs`.
      'import/no-anonymous-default-export': 'off',
    },
  },
];

/*
 * `@next/next/no-img-element` is deliberately left **on**.
 *
 * Four components already carry an inline `eslint-disable` for it, written
 * against a config that never existed — each at a place that uses `<img>` on
 * purpose, because the bytes come from our own API behind a signed,
 * single-row, expiring link (ADR-017) and `next/image` would proxy them through
 * the Next server, which holds no credential for that link and serves no bytes.
 *
 * Turning the rule off globally would have silenced those four and, with them,
 * the reason they give. The authors said it at the site; the config defers.
 */

