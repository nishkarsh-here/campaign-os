/**
 * What the request path does with a session.
 *
 * Three claims, each of which would be a real defect if it stopped being true:
 * an authenticated request carries the token, an unauthenticated deployment
 * sends no header at all, and a rejected credential is discarded rather than
 * retried for ever.
 *
 * `fetch` is stubbed throughout. Nothing here reaches the API or Supabase.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const PROJECT = 'https://project.supabase.co';
const ANON = 'anon-publishable-key';

function installStorage() {
  const data = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  });
  return data;
}

/** Both modules, imported fresh against one configuration. */
async function load(configured = true) {
  vi.resetModules();
  vi.stubEnv('SUPABASE_URL', configured ? PROJECT : '');
  vi.stubEnv('SUPABASE_ANON_KEY', configured ? ANON : '');
  const session = await import('@/lib/session');
  const api = await import('@/lib/api');
  return { session, api };
}

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => null },
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

function errorResponse(code: string, message: string, status: number) {
  return jsonResponse({ error: { code, message } }, status);
}

/** Establish a live session without going near the network twice. */
async function signIn(session: typeof import('@/lib/session')) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        access_token: 'access-token-1',
        refresh_token: 'refresh-token-1',
        expires_in: 3600,
        user: { email: 'priya@example.test' },
      }),
    })) as never,
  );
  await session.signInWithPassword('priya@example.test', 'pw');
}

beforeEach(() => {
  installStorage();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('authorization header', () => {
  it('is attached when a session exists', async () => {
    const { session, api } = await load();
    await signIn(session);

    const fetchSpy = vi.fn(async () => jsonResponse({ ok: true }));
    vi.stubGlobal('fetch', fetchSpy as never);
    await api.apiFetch('/me');

    const [, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer access-token-1');
  });

  it('is absent in a dev-stub deployment', async () => {
    // The offline demo must keep working with no identity provider: the
    // backend authenticates its configured demo user and ignores credentials.
    const { api } = await load(false);
    const fetchSpy = vi.fn(async () => jsonResponse({ ok: true }));
    vi.stubGlobal('fetch', fetchSpy as never);

    await api.apiFetch('/me');

    const [, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('travels alongside the organization header, not instead of it', async () => {
    const { session, api } = await load();
    await signIn(session);

    const fetchSpy = vi.fn(async () => jsonResponse({ ok: true }));
    vi.stubGlobal('fetch', fetchSpy as never);
    await api.apiFetch('/campaigns', { organizationId: 'org-1' });

    const [, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer access-token-1');
    expect(headers['X-Organization-Id']).toBe('org-1');
  });

  it('is attached to uploads as well as JSON requests', async () => {
    // A second fetch call site existed and was easy to miss.
    const { session, api } = await load();
    await signIn(session);

    const fetchSpy = vi.fn(async () => jsonResponse({ ok: true }));
    vi.stubGlobal('fetch', fetchSpy as never);
    await api.apiUpload('/brands/b1/documents', new FormData(), 'org-1');

    const [, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer access-token-1');
  });

  it('never sends a service-role key', async () => {
    const { session, api } = await load();
    await signIn(session);

    const fetchSpy = vi.fn(async () => jsonResponse({ ok: true }));
    vi.stubGlobal('fetch', fetchSpy as never);
    await api.apiFetch('/me');

    const rendered = JSON.stringify(fetchSpy.mock.calls[0]);
    expect(rendered).not.toContain('service_role');
    expect(rendered).not.toContain('SERVICE');
  });
});

describe('UNAUTHENTICATED', () => {
  it('discards the stored session', async () => {
    const { session, api } = await load();
    await signIn(session);
    expect(session.getAccessToken()).toBe('access-token-1');

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => errorResponse('UNAUTHENTICATED', 'Sign in to continue.', 401)) as never,
    );
    await expect(api.apiFetch('/me')).rejects.toMatchObject({ code: 'UNAUTHENTICATED' });

    // The token the server just refused must not be sent again.
    expect(session.getSession()).toBeNull();
    expect(session.getAccessToken()).toBeNull();
  });

  it('discards it on a rejected upload too', async () => {
    const { session, api } = await load();
    await signIn(session);

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => errorResponse('UNAUTHENTICATED', 'Sign in to continue.', 401)) as never,
    );
    await expect(
      api.apiUpload('/brands/b1/documents', new FormData(), 'org-1'),
    ).rejects.toMatchObject({ code: 'UNAUTHENTICATED' });
    expect(session.getSession()).toBeNull();
  });

  it('surfaces the code so the guard can route to sign-in', async () => {
    const { api } = await load();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => errorResponse('UNAUTHENTICATED', 'Sign in to continue.', 401)) as never,
    );

    await expect(api.apiFetch('/me')).rejects.toMatchObject({
      code: 'UNAUTHENTICATED',
      status: 401,
    });
  });
});

describe('FORBIDDEN', () => {
  it('keeps the session, because the credential is fine', async () => {
    // A permission failure is not an identity failure. Clearing the session
    // here would sign a legitimate user out of the whole product.
    const { session, api } = await load();
    await signIn(session);

    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        errorResponse('FORBIDDEN', 'You do not belong to any organization yet.', 403),
      ) as never,
    );
    await expect(api.apiFetch('/campaigns')).rejects.toMatchObject({ code: 'FORBIDDEN' });

    expect(session.getAccessToken()).toBe('access-token-1');
  });

  it('carries a message written for a person, with no internals', async () => {
    const { api } = await load();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        errorResponse('FORBIDDEN', 'You do not belong to any organization yet.', 403),
      ) as never,
    );

    await expect(api.apiFetch('/campaigns')).rejects.toMatchObject({
      code: 'FORBIDDEN',
      message: 'You do not belong to any organization yet.',
    });
  });
});

describe('the sign-in redirect target', () => {
  it('only accepts same-origin application paths', async () => {
    // `next` comes from the query string. Honouring it blindly would make the
    // sign-in page an open redirect.
    const { safeDestination } = await import('@/lib/redirect');

    expect(safeDestination('/app/campaigns/abc')).toBe('/app/campaigns/abc');
    expect(safeDestination(null)).toBe('/app');
    expect(safeDestination('https://evil.example/app')).toBe('/app');
    expect(safeDestination('//evil.example')).toBe('/app');
    expect(safeDestination('/etc/passwd')).toBe('/app');
  });
});
