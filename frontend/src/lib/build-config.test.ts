/**
 * `next.config.mjs` refuses to bake an unreachable API into a production build.
 *
 * Audit finding P-3, and the one deployment mistake that is invisible until a
 * real person opens the site: `API_BASE_URL` is substituted into the client
 * bundle by `next build`, so an absent value became `http://127.0.0.1:8000` —
 * which the *visitor's* browser resolves against their own machine. The build
 * succeeded, the pages rendered, every request failed, and nothing said why.
 *
 * The config is validated at module evaluation, so each case re-imports it with
 * a different environment. `vi.resetModules()` is what makes that a fresh
 * evaluation rather than a cache hit.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const CONFIG = '../../next.config.mjs';

let saved: NodeJS.ProcessEnv;

beforeEach(() => {
  saved = { ...process.env };
  vi.resetModules();
});

afterEach(() => {
  process.env = saved;
});

/** Import the config fresh under a given environment. */
async function load(env: Record<string, string | undefined>) {
  for (const [key, value] of Object.entries(env)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  vi.resetModules();
  return (await import(CONFIG)).default;
}

describe('a production build', () => {
  it('refuses when API_BASE_URL is missing', async () => {
    await expect(
      load({ NODE_ENV: 'production', API_BASE_URL: undefined }),
    ).rejects.toThrow(/API_BASE_URL is required/);
  });

  it('says what to do about it', async () => {
    // The message is the whole value of failing here rather than at runtime.
    await expect(load({ NODE_ENV: 'production', API_BASE_URL: undefined })).rejects.toThrow(
      /API_BASE_URL=https:\/\/api\.example\.com npm run build/,
    );
  });

  it.each([
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'https://127.0.0.1',
    'http://[::1]:8000',
    'http://0.0.0.0:8000',
  ])('refuses the loopback origin %s', async (url) => {
    await expect(
      load({
        NODE_ENV: 'production',
        API_BASE_URL: url,
        ALLOW_LOOPBACK_API_BASE_URL: undefined,
      }),
    ).rejects.toThrow(/resolves against the visitor/);
  });

  it('accepts a loopback origin when it is opted into deliberately', async () => {
    // Smoke-testing a production build against a local API is legitimate. The
    // point is that it becomes a decision rather than a default.
    const config = await load({
      NODE_ENV: 'production',
      API_BASE_URL: 'http://127.0.0.1:8000',
      ALLOW_LOOPBACK_API_BASE_URL: 'true',
    });
    expect(config.env.API_BASE_URL).toBe('http://127.0.0.1:8000');
  });

  it('inlines a real origin', async () => {
    const config = await load({
      NODE_ENV: 'production',
      API_BASE_URL: 'https://api.example.com',
    });
    expect(config.env.API_BASE_URL).toBe('https://api.example.com');
  });

  it('does not mistake a hostname that merely contains "localhost"', async () => {
    const config = await load({
      NODE_ENV: 'production',
      API_BASE_URL: 'https://localhost-api.example.com',
    });
    expect(config.env.API_BASE_URL).toBe('https://localhost-api.example.com');
  });
});

describe('development', () => {
  it('keeps the localhost default, because that is what dev is', async () => {
    const config = await load({ NODE_ENV: 'development', API_BASE_URL: undefined });
    expect(config.env.API_BASE_URL).toBe('http://127.0.0.1:8000');
  });
});

describe('Supabase configuration', () => {
  it('is not required, so a dev-stub deployment still builds', async () => {
    // `isSupabaseConfigured()` makes the sign-in screen explain itself when
    // these are absent. Requiring them here would make the offline demo
    // unbuildable, which is a standing requirement (CLAUDE.md §3.5).
    const config = await load({
      NODE_ENV: 'production',
      API_BASE_URL: 'https://api.example.com',
      SUPABASE_URL: undefined,
      SUPABASE_ANON_KEY: undefined,
    });
    expect(config.env.SUPABASE_URL).toBe('');
    expect(config.env.SUPABASE_ANON_KEY).toBe('');
  });

  it('is inlined when present, because the browser signs in directly', async () => {
    const config = await load({
      NODE_ENV: 'production',
      API_BASE_URL: 'https://api.example.com',
      SUPABASE_URL: 'https://project.supabase.co',
      SUPABASE_ANON_KEY: 'publishable-anon-key',
    });
    expect(config.env.SUPABASE_URL).toBe('https://project.supabase.co');
    expect(config.env.SUPABASE_ANON_KEY).toBe('publishable-anon-key');
  });

  it('never carries a service-role key', async () => {
    // The one secret that must not reach the browser. Asserted on the config's
    // own shape rather than trusting that nobody adds it later.
    const config = await load({
      NODE_ENV: 'production',
      API_BASE_URL: 'https://api.example.com',
      SUPABASE_SERVICE_ROLE_KEY: 'super-secret',
    });
    const inlined = JSON.stringify(config.env);
    expect(inlined).not.toContain('super-secret');
    expect(Object.keys(config.env)).not.toContain('SUPABASE_SERVICE_ROLE_KEY');
  });
});
