/**
 * The browser's half of authentication.
 *
 * Offline and deterministic: `fetch` and `localStorage` are both stubbed, so
 * nothing here needs a Supabase project, a network or a browser. A test that
 * reached out would fail on a train and pass in CI, which is worse than no
 * test at all.
 *
 * The module reads its Supabase configuration at import time, so each block
 * sets the environment first and imports the module fresh. That is the cost of
 * build-time config; isolating it in the helper below keeps it out of the way.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const PROJECT = 'https://project.supabase.co';
const ANON = 'anon-publishable-key';

/** A `localStorage` that behaves like the real one, including throwing. */
function installStorage(options: { throws?: boolean } = {}) {
  const data = new Map<string, string>();
  const store = {
    getItem: (k: string) => {
      if (options.throws) throw new Error('blocked');
      return data.get(k) ?? null;
    },
    setItem: (k: string, v: string) => {
      if (options.throws) throw new Error('blocked');
      data.set(k, v);
    },
    removeItem: (k: string) => {
      if (options.throws) throw new Error('blocked');
      data.delete(k);
    },
  };
  vi.stubGlobal('localStorage', store);
  return data;
}

/** Import `session.ts` fresh against a given configuration. */
async function loadSession(configured = true) {
  vi.resetModules();
  vi.stubEnv('SUPABASE_URL', configured ? PROJECT : '');
  vi.stubEnv('SUPABASE_ANON_KEY', configured ? ANON : '');
  return import('@/lib/session');
}

function tokenResponse(overrides: Record<string, unknown> = {}) {
  return {
    ok: true,
    json: async () => ({
      access_token: 'access-token-1',
      refresh_token: 'refresh-token-1',
      expires_in: 3600,
      user: { email: 'priya@example.test' },
      ...overrides,
    }),
  } as unknown as Response;
}

beforeEach(() => {
  installStorage();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

// ------------------------------------------------------------ configuration
describe('configuration', () => {
  it('reports configured when a project and key are present', async () => {
    const session = await loadSession(true);
    expect(session.isSupabaseConfigured()).toBe(true);
  });

  it('reports unconfigured in a dev-stub deployment', async () => {
    const session = await loadSession(false);
    expect(session.isSupabaseConfigured()).toBe(false);
  });

  it('refuses to sign in when there is no provider', async () => {
    const session = await loadSession(false);
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);

    await expect(session.signInWithPassword('a@b.test', 'pw')).rejects.toBeInstanceOf(
      session.SignInError,
    );
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------- storage
describe('session storage', () => {
  it('round-trips a session that was just established', async () => {
    const session = await loadSession();
    vi.stubGlobal('fetch', vi.fn(async () => tokenResponse()));

    await session.signInWithPassword('priya@example.test', 'pw');

    expect(session.getAccessToken()).toBe('access-token-1');
    expect(session.getSession()?.email).toBe('priya@example.test');
    expect(session.hasLiveSession()).toBe(true);
  });

  it('clears everything on demand', async () => {
    const session = await loadSession();
    vi.stubGlobal('fetch', vi.fn(async () => tokenResponse()));
    await session.signInWithPassword('a@b.test', 'pw');

    session.clearSession();

    expect(session.getSession()).toBeNull();
    expect(session.getAccessToken()).toBeNull();
    expect(session.hasLiveSession()).toBe(false);
  });

  it('survives storage that throws', async () => {
    // Private windows and blocked site data. An unreadable session is simply
    // no session — it must never take the page down with it.
    installStorage({ throws: true });
    const session = await loadSession();

    expect(session.getSession()).toBeNull();
    expect(() => session.clearSession()).not.toThrow();
  });

  it('treats a corrupt stored value as no session', async () => {
    const data = installStorage();
    data.set('campaign-os:session', '{ not json');
    const session = await loadSession();

    expect(session.getSession()).toBeNull();
  });
});

// ----------------------------------------------------------------- expiry
describe('expiry', () => {
  it('reports a live session before expiry', async () => {
    const session = await loadSession();
    vi.stubGlobal('fetch', vi.fn(async () => tokenResponse()));
    await session.signInWithPassword('a@b.test', 'pw');

    expect(session.hasLiveSession()).toBe(true);
    expect(await session.authorizationToken()).toBe('access-token-1');
  });

  it('subtracts headroom so a token is renewed before it dies', async () => {
    const session = await loadSession();
    vi.stubGlobal('fetch', vi.fn(async () => tokenResponse({ expires_in: 3600 })));
    const now = Date.now();

    const established = await session.signInWithPassword('a@b.test', 'pw');

    // A minute short of the provider's own expiry, never past it.
    expect(established.expiresAt).toBeLessThan(now + 3600 * 1000);
    expect(established.expiresAt).toBeGreaterThan(now + 3500 * 1000);
  });

  it('refreshes rather than returning an expired token', async () => {
    const session = await loadSession();
    vi.stubGlobal('fetch', vi.fn(async () => tokenResponse({ expires_in: 0 })));
    await session.signInWithPassword('a@b.test', 'pw');
    expect(session.hasLiveSession()).toBe(false);

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => tokenResponse({ access_token: 'access-token-2', expires_in: 3600 })),
    );
    expect(await session.authorizationToken()).toBe('access-token-2');
  });

  it('returns no token at all when there is no session', async () => {
    const session = await loadSession();
    expect(await session.authorizationToken()).toBeNull();
  });
});

// ---------------------------------------------------------------- sign in
describe('sign in', () => {
  it('posts the password grant with the project key', async () => {
    const session = await loadSession();
    const fetchSpy = vi.fn(async () => tokenResponse());
    vi.stubGlobal('fetch', fetchSpy);

    await session.signInWithPassword('priya@example.test', 'correct horse');

    const [url, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${PROJECT}/auth/v1/token?grant_type=password`);
    expect((init.headers as Record<string, string>).apikey).toBe(ANON);
    expect(JSON.parse(init.body as string)).toEqual({
      email: 'priya@example.test',
      password: 'correct horse',
    });
  });

  it("surfaces the provider's own wording for a rejected password", async () => {
    const session = await loadSession();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        json: async () => ({ error_description: 'Invalid login credentials' }),
      })) as unknown as typeof fetch,
    );

    await expect(session.signInWithPassword('a@b.test', 'wrong')).rejects.toThrow(
      'Invalid login credentials',
    );
    expect(session.getSession()).toBeNull();
  });

  it('does not store a session when the provider returns no token', async () => {
    const session = await loadSession();
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({}) })) as never);

    await expect(session.signInWithPassword('a@b.test', 'pw')).rejects.toBeInstanceOf(
      session.SignInError,
    );
    expect(session.getSession()).toBeNull();
  });

  it('reports an unreachable provider without leaking the cause', async () => {
    const session = await loadSession();
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('ECONNREFUSED at 10.0.0.1'); }));

    await expect(session.signInWithPassword('a@b.test', 'pw')).rejects.toThrow(
      /could not reach/i,
    );
  });
});

// ---------------------------------------------------------------- refresh
describe('refresh', () => {
  it('exchanges the refresh token for a new session', async () => {
    const session = await loadSession();
    vi.stubGlobal('fetch', vi.fn(async () => tokenResponse()));
    await session.signInWithPassword('a@b.test', 'pw');

    const fetchSpy = vi.fn(async () => tokenResponse({ access_token: 'access-token-2' }));
    vi.stubGlobal('fetch', fetchSpy);
    const refreshed = await session.refreshSession();

    expect(refreshed?.accessToken).toBe('access-token-2');
    const [url, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain('grant_type=refresh_token');
    expect(JSON.parse(init.body as string)).toEqual({ refresh_token: 'refresh-token-1' });
  });

  it('clears the session when the refresh is rejected', async () => {
    const session = await loadSession();
    vi.stubGlobal('fetch', vi.fn(async () => tokenResponse()));
    await session.signInWithPassword('a@b.test', 'pw');

    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({}) })) as never);
    expect(await session.refreshSession()).toBeNull();
    expect(session.getSession()).toBeNull();
  });

  it('returns null when there is nothing to refresh', async () => {
    const session = await loadSession();
    expect(await session.refreshSession()).toBeNull();
  });
});

// ----------------------------------------------------------------- logout
describe('sign out', () => {
  it('clears local state and revokes at the provider', async () => {
    const session = await loadSession();
    vi.stubGlobal('fetch', vi.fn(async () => tokenResponse()));
    await session.signInWithPassword('a@b.test', 'pw');

    const fetchSpy = vi.fn(async () => ({ ok: true, json: async () => ({}) }));
    vi.stubGlobal('fetch', fetchSpy as never);
    await session.signOut();

    expect(session.getSession()).toBeNull();
    expect(session.getAccessToken()).toBeNull();
    const [url, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${PROJECT}/auth/v1/logout`);
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer access-token-1');
  });

  it('still clears locally when the provider cannot be reached', async () => {
    // The one outcome nobody wants is a browser that still holds a usable
    // token because sign-out errored.
    const session = await loadSession();
    vi.stubGlobal('fetch', vi.fn(async () => tokenResponse()));
    await session.signInWithPassword('a@b.test', 'pw');

    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
    await expect(session.signOut()).resolves.toBeUndefined();
    expect(session.getSession()).toBeNull();
  });

  it('is harmless with no session and no provider', async () => {
    const session = await loadSession(false);
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);

    await session.signOut();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('notifies subscribers so every screen re-resolves', async () => {
    const session = await loadSession();
    const listener = vi.fn();
    session.onSessionChange(listener);

    session.clearSession();
    expect(listener).toHaveBeenCalled();
  });
});
