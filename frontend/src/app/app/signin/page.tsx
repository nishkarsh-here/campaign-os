'use client';

/**
 * Sign in.
 *
 * Deliberately plain: this uses the existing shell styling and adds no new
 * design vocabulary, because the design system is the next phase's work and
 * authentication should not be the thing that invents it.
 *
 * Two deployments, two behaviours. With `AUTH_PROVIDER=dev_stub` there is no
 * identity provider and nothing to sign in to — the page says so and offers a
 * way through, so the offline demo never hits a wall that does not apply to
 * it. With Supabase configured, this is a real password sign-in.
 */

import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { SignInError, isSupabaseConfigured, signInWithPassword } from '@/lib/session';
import { safeDestination } from '@/lib/redirect';

function SignInForm() {
  const router = useRouter();
  const params = useSearchParams();
  const destination = safeDestination(params.get('next'));
  const configured = isSupabaseConfigured();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signInWithPassword(email, password);
      router.replace(destination);
    } catch (err) {
      // Only a `SignInError` carries wording meant for a person. Anything else
      // becomes one sentence, because an unexpected failure must not leak a
      // stack, a URL or a provider payload onto the screen.
      setError(
        err instanceof SignInError ? err.message : 'Could not sign in. Please try again.',
      );
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-6">
      <p className="text-sm font-medium uppercase tracking-widest text-muted">campaign-os</p>
      <h1 className="mt-3 text-2xl font-semibold tracking-tight">Sign in</h1>

      {!configured ? (
        // Not an error: a dev-stub deployment is a supported configuration.
        // Saying so beats a form that cannot succeed.
        <div className="mt-6 rounded-lg border border-line bg-line/20 p-5">
          <h2 className="text-sm font-medium">No identity provider is configured</h2>
          <p className="mt-2 text-sm text-muted">
            This instance runs in development mode and authenticates every caller as the same
            demo user. There is nothing to sign in to.
          </p>
          <Link
            href={destination}
            className="mt-5 inline-block rounded-md border border-line px-3 py-1.5 text-sm hover:bg-line/40"
          >
            Continue to the workspace
          </Link>
        </div>
      ) : (
        <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
          <label className="block">
            <span className="text-sm text-muted">Email</span>
            <input
              type="email"
              name="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-md border border-line bg-transparent px-3 py-2 text-sm"
            />
          </label>

          <label className="block">
            <span className="text-sm text-muted">Password</span>
            <input
              type="password"
              name="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-md border border-line bg-transparent px-3 py-2 text-sm"
            />
          </label>

          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-md bg-ink px-4 py-2 text-sm font-medium text-surface disabled:opacity-60"
          >
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      )}
    </main>
  );
}

export default function SignInPage() {
  // `useSearchParams` requires a Suspense boundary to prerender.
  return (
    <Suspense fallback={<main className="mx-auto min-h-screen max-w-sm px-6 py-24" />}>
      <SignInForm />
    </Suspense>
  );
}
