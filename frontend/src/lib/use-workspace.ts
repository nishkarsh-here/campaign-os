'use client';

/**
 * Workspace state: who am I, which organization am I acting in.
 *
 * One hook owns this so no component fetches `/me` on its own and no component
 * invents its own organization-selection rule. The choice is remembered in
 * localStorage — a per-viewer convenience, not state the server needs.
 */

import { useCallback, useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { ApiError, api, type Me } from '@/lib/api';
import { clearSession, onSessionChange } from '@/lib/session';

const STORAGE_KEY = 'campaign-os:active-organization';

function readStored(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    // Private windows and blocked site data throw on access.
    return null;
  }
}

export interface WorkspaceState {
  me: Me | null;
  organizationId: string | null;
  loading: boolean;
  error: ApiError | null;
  setOrganizationId: (id: string) => void;
  reload: () => void;
}

export function useWorkspace(): WorkspaceState {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [organizationId, setOrg] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);

    api
      .me(controller.signal)
      .then((result) => {
        setMe(result);
        const stored = readStored();
        const valid = result.organizations.some((m) => m.organization.id === stored);
        // Prefer a remembered choice, but only while it is still a real
        // membership — otherwise fall back rather than send a dead id.
        setOrg(
          valid ? stored : (result.active_organization_id ??
            result.organizations[0]?.organization.id ??
            null),
        );
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        const failure = err instanceof ApiError ? err : new ApiError('INTERNAL', String(err), 0);
        if (failure.code === 'UNAUTHENTICATED') {
          // One place, so every screen recovers the same way rather than each
          // deciding for itself. The path is carried through so the person
          // lands back where they were rather than at the front door.
          clearSession();
          const next = encodeURIComponent(pathname ?? '/app');
          router.replace(`/app/signin?next=${next}`);
          return;
        }
        setError(failure);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [nonce, router, pathname]);

  const setOrganizationId = useCallback((id: string) => {
    setOrg(id);
    try {
      localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* storage unavailable — the choice simply is not remembered */
    }
  }, []);

  // A sign-out in the shell must invalidate every screen's view of who is
  // signed in, not just the one that triggered it.
  useEffect(() => onSessionChange(() => setNonce((n) => n + 1)), []);

  return {
    me,
    organizationId,
    loading,
    error,
    setOrganizationId,
    reload: () => setNonce((n) => n + 1),
  };
}
