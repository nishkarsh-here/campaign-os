/**
 * The browser's half of authentication.
 *
 * One module owns the access token: how it is obtained, where it is kept, when
 * it is refreshed and how it is discarded. Nothing else in the app reads or
 * writes it, which is what makes "is this request authenticated?" answerable
 * in one place rather than inferred from whichever component last ran.
 *
 * **Two modes, one shape.** With `AUTH_PROVIDER=dev_stub` the backend
 * authenticates every caller as the same user and ignores the credential
 * entirely, so there is no token to hold and `getAccessToken()` returns null —
 * the offline demo keeps working with no identity provider, exactly as before.
 * With `AUTH_PROVIDER=supabase` a real session is obtained here and every
 * request carries it. The rest of the app does not branch on which.
 *
 * **What is kept.** The access token, the refresh token and an absolute expiry,
 * in `localStorage`. That is a deliberate trade: it survives a reload, and it
 * is readable by any script that achieves XSS on this origin. The alternative —
 * an httpOnly cookie set by our own API — is stronger and is recorded as the
 * next step rather than pretended to be done.
 */

const STORAGE_KEY = 'campaign-os:session';

/** Public Supabase configuration, inlined at build time by `next.config.mjs`. */
const SUPABASE_URL = process.env.SUPABASE_URL ?? '';
const SUPABASE_ANON_KEY = process.env.SUPABASE_ANON_KEY ?? '';

export interface Session {
  accessToken: string;
  refreshToken: string | null;
  /** Epoch milliseconds. Absolute, so a sleeping laptop cannot extend it. */
  expiresAt: number;
  email: string | null;
}

/** Raised for a sign-in that failed for a reason worth showing someone. */
export class SignInError extends Error {}

/**
 * Can this build obtain a session at all?
 *
 * False in dev-stub deployments, where no Supabase project is configured and
 * none is needed. The sign-in screen uses this to explain itself rather than
 * presenting a form that cannot work.
 */
export function isSupabaseConfigured(): boolean {
  return Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);
}

// --------------------------------------------------------------- storage
function read(): Session | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Session>;
    if (typeof parsed.accessToken !== 'string' || typeof parsed.expiresAt !== 'number') {
      return null;
    }
    return {
      accessToken: parsed.accessToken,
      refreshToken: typeof parsed.refreshToken === 'string' ? parsed.refreshToken : null,
      expiresAt: parsed.expiresAt,
      email: typeof parsed.email === 'string' ? parsed.email : null,
    };
  } catch {
    // Private windows, blocked site data, and anything that wrote nonsense
    // here previously. An unreadable session is simply no session.
    return null;
  }
}

function write(session: Session | null): void {
  try {
    if (session) localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable — the session just does not survive a reload */
  }
}

export function getSession(): Session | null {
  return read();
}

export function getAccessToken(): string | null {
  return read()?.accessToken ?? null;
}

export function clearSession(): void {
  write(null);
  notify();
}

// ------------------------------------------------------------ subscription
type Listener = () => void;
const listeners = new Set<Listener>();

/** Lets the shell re-render when the session changes in either direction. */
export function onSessionChange(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function notify(): void {
  for (const listener of listeners) listener();
}

// ------------------------------------------------------------- obtaining
interface TokenResponse {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
  user?: { email?: string };
  error_description?: string;
  msg?: string;
}

async function grant(body: Record<string, string>, query: string): Promise<Session> {
  if (!isSupabaseConfigured()) {
    throw new SignInError('This deployment has no identity provider configured.');
  }

  let response: Response;
  try {
    response = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=${query}`, {
      method: 'POST',
      headers: { apikey: SUPABASE_ANON_KEY, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    throw new SignInError('Could not reach the identity provider.');
  }

  const payload = (await response.json().catch(() => ({}))) as TokenResponse;
  if (!response.ok || !payload.access_token) {
    // The provider's own wording where it gave one, because "invalid login
    // credentials" is more use than a status code. Never the response body
    // wholesale — that can carry more than a person needs to see.
    throw new SignInError(
      payload.error_description ?? payload.msg ?? 'That email and password were not accepted.',
    );
  }

  const session: Session = {
    accessToken: payload.access_token,
    refreshToken: payload.refresh_token ?? null,
    // A minute of headroom, so a token is renewed just before it dies rather
    // than just after — which would surface as a spurious sign-out.
    expiresAt: Date.now() + Math.max(0, (payload.expires_in ?? 3600) - 60) * 1000,
    email: payload.user?.email ?? null,
  };
  write(session);
  notify();
  return session;
}

export function signInWithPassword(email: string, password: string): Promise<Session> {
  return grant({ email, password }, 'password');
}

/**
 * Exchange the refresh token for a new session.
 *
 * Returns null rather than throwing when there is nothing to refresh or the
 * refresh is itself rejected: the caller's next step is the same either way,
 * which is to treat the session as gone.
 */
export async function refreshSession(): Promise<Session | null> {
  const current = read();
  if (!current?.refreshToken) return null;
  try {
    return await grant({ refresh_token: current.refreshToken }, 'refresh_token');
  } catch {
    clearSession();
    return null;
  }
}

/**
 * End the session, here and at the provider.
 *
 * The local session is cleared **first and unconditionally**: if the network
 * call fails, the one outcome nobody wants is a browser that still holds a
 * usable token because sign-out errored. Revoking at Supabase is best-effort
 * on top of that, not a precondition for it.
 */
export async function signOut(): Promise<void> {
  const current = read();
  write(null);
  notify();

  if (!current?.accessToken || !isSupabaseConfigured()) return;
  try {
    await fetch(`${SUPABASE_URL}/auth/v1/logout`, {
      method: 'POST',
      headers: {
        apikey: SUPABASE_ANON_KEY,
        Authorization: `Bearer ${current.accessToken}`,
      },
    });
  } catch {
    // Already signed out locally. A provider that cannot be reached leaves the
    // refresh token alive until it expires, which is the documented trade and
    // not something the user can act on.
  }
}

/** True when a stored session exists and has not passed its expiry. */
export function hasLiveSession(): boolean {
  const current = read();
  return Boolean(current && current.expiresAt > Date.now());
}

/**
 * The token to send with a request, refreshing first if it has aged out.
 *
 * Returns null when there is no session, which is the normal state in dev-stub
 * deployments — the request simply goes out unauthenticated and the backend
 * resolves its configured demo identity.
 */
export async function authorizationToken(): Promise<string | null> {
  const current = read();
  if (!current) return null;
  if (current.expiresAt > Date.now()) return current.accessToken;
  const refreshed = await refreshSession();
  return refreshed?.accessToken ?? null;
}
