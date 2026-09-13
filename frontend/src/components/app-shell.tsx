'use client';

/**
 * The workspace chrome: identity, organization switcher, navigation, and the
 * demo-mode badge.
 *
 * The badge is the one piece of chrome that carries meaning rather than
 * structure: when this instance declares itself a demonstration, every viewer
 * should be able to see that at a glance instead of wondering whether the
 * output in front of them came from a real model.
 */

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { api, type Me } from '@/lib/api';
import { StatusBadge } from '@/components/states';

export function AppShell({
  me,
  activeOrganizationId,
  onOrganizationChange,
  children,
}: {
  me: Me | null;
  activeOrganizationId: string | null;
  onOrganizationChange: (id: string) => void;
  children: React.ReactNode;
}) {
  // Said out loud, because "is this real output or a mock?" is the first
  // question anyone watching a demo has, and guessing is worse than either
  // answer. A failed health call simply shows nothing rather than a wrong
  // claim in either direction.
  const [demo, setDemo] = useState<boolean | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    api
      .getHealth(controller.signal)
      .then((health) => {
        if (!controller.signal.aborted) setDemo(health.demo_mode);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  return (
    <div className="min-h-screen">
      <header className="border-b border-line">
        <div className="mx-auto flex h-14 max-w-5xl items-center gap-4 px-6">
          <Link href="/app" className="text-sm font-semibold tracking-tight">
            campaign-os
          </Link>

          <nav className="flex gap-3 text-sm text-muted">
            <Link href="/app" className="hover:text-ink">
              Projects
            </Link>
            <Link href="/app/brands" className="hover:text-ink">
              Brands
            </Link>
            <Link href="/app/campaigns" className="hover:text-ink">
              Campaigns
            </Link>
          </nav>

          {me && me.organizations.length > 0 ? (
            <label className="flex items-center gap-2 text-sm">
              <span className="sr-only">Organization</span>
              <select
                value={activeOrganizationId ?? ''}
                onChange={(e) => onOrganizationChange(e.target.value)}
                className="rounded-md border border-line bg-transparent px-2 py-1 text-sm"
              >
                {me.organizations.map(({ organization }) => (
                  <option key={organization.id} value={organization.id}>
                    {organization.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          <div className="ml-auto flex items-center gap-3">
            {demo ? (
              <StatusBadge tone="active" title="Mock providers only — nothing leaves this machine.">
                Demo mode
              </StatusBadge>
            ) : null}
            <span className="text-sm text-muted">{me?.user.email ?? '—'}</span>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-10">{children}</main>
    </div>
  );
}
