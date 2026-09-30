/**
 * `API_BASE_URL` is read at **build time** and inlined into the bundle.
 *
 * That is the whole reason this file validates it. `next build` substitutes the
 * value into the client JavaScript, so it is fixed when the artefact is made and
 * cannot be corrected by the host's environment afterwards. A build that fell
 * back to `http://127.0.0.1:8000` produced a site that loaded perfectly and
 * could not reach anything — the browser resolves that against the *visitor's*
 * machine — and nothing said so until someone opened it (audit finding P-3).
 *
 * So a production build **refuses** rather than defaulting:
 *
 *   API_BASE_URL=https://api.example.com npm run build
 *
 * `next dev` keeps the localhost default, because that is what it is for. If you
 * genuinely want a production build pointed at a local API — to smoke-test one
 * before deploying — say so explicitly with the same variable. The point is that
 * localhost becomes a decision rather than an accident.
 *
 * The browser never talks to a provider or to storage directly, only to our API,
 * and keeping the base URL configurable here is what keeps it that way.
 */

import { PHASE_PRODUCTION_BUILD } from 'next/constants.js';

/** Hosts that only mean anything on the machine the browser is running on. */
const LOOPBACK = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(:|\/|$)/i;

/**
 * Validated on the **build** phase alone, not on `NODE_ENV`.
 *
 * `next start` also evaluates this file with `NODE_ENV=production`, and
 * checking there was wrong twice over: by then the value is already inlined, so
 * the check proves nothing, and a correctly-built artefact would refuse to boot
 * in any environment that did not also carry the build variable. Found by
 * running the deployment's own start command rather than by reading it.
 */
export function assertApiBaseUrl(apiBaseUrl, allowLoopback) {
  if (!apiBaseUrl) {
    throw new Error(
      'API_BASE_URL is required for a production build. It is inlined into the ' +
        'browser bundle, so it must be an origin the visitor’s browser can reach ' +
        '— not an internal service name, and not a default. ' +
        'Example: API_BASE_URL=https://api.example.com npm run build',
    );
  }
  if (LOOPBACK.test(apiBaseUrl) && allowLoopback !== 'true') {
    throw new Error(
      `API_BASE_URL is ${apiBaseUrl}, which resolves against the visitor’s own ` +
        'machine rather than your API. If this build really is for local testing, ' +
        'set ALLOW_LOOPBACK_API_BASE_URL=true to say so deliberately.',
    );
  }
}

/** @type {(phase: string) => import('next').NextConfig} */
export default function nextConfig(phase) {
  const apiBaseUrl = process.env.API_BASE_URL;

  if (phase === PHASE_PRODUCTION_BUILD) {
    assertApiBaseUrl(apiBaseUrl, process.env.ALLOW_LOOPBACK_API_BASE_URL);
  }

  return {
    reactStrictMode: true,
    env: {
      // `next dev` only. A production build has already failed above if this is
      // missing, so the fallback can never reach a deployed bundle. On
      // `next start` the served bundle carries whatever the build inlined, and
      // this value is not read.
      API_BASE_URL: apiBaseUrl ?? 'http://127.0.0.1:8000',
      // Public Supabase configuration, also build-time. The anon key is
      // publishable by design — it identifies the project and carries no
      // privilege. The service-role key is server-side only and must never
      // appear here.
      //
      // Deliberately *not* required: a dev-stub deployment has no Supabase
      // project, and `isSupabaseConfigured()` makes the sign-in screen explain
      // itself rather than presenting a form that cannot work. Requiring them
      // here would make the offline demo unbuildable.
      SUPABASE_URL: process.env.SUPABASE_URL ?? '',
      SUPABASE_ANON_KEY: process.env.SUPABASE_ANON_KEY ?? '',
    },
  };
}
