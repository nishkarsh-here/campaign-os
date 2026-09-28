'use client';

/**
 * The application shell.
 *
 * UI-2A turned this from a single header strip into the product's frame: a
 * persistent rail from `lg` up, a drawer below it, and a slot the campaign
 * workspace fills with its Meridian.
 *
 * The prop contract is unchanged from UI-1 — `me`, `activeOrganizationId`,
 * `onOrganizationChange`, `children` — so the thirteen screens that render it
 * needed no edit. `rail` and `header` are additive.
 *
 * Two things live here rather than in any page, because they must not reset
 * when a person moves between stages: the organization they are acting in, and
 * the campaign navigation. That is what made the old flow feel one-way — every
 * page rebuilt its own chrome, so nothing carried across.
 */

import { useCallback, useEffect, useId, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { api, type Me } from '@/lib/api';
import { Button, Select, StatusBadge, cx } from '@/components/ui';
import { PRODUCT_NAV, isCurrent } from '@/lib/nav';
import { ROLE_LABEL, capabilitiesFor } from '@/lib/capabilities';
import { hasLiveSession, signOut } from '@/lib/session';

export function AppShell({
  me,
  activeOrganizationId,
  onOrganizationChange,
  /** The campaign workspace's Meridian. Absent on product-level screens. */
  rail,
  /** Campaign identity: title and place stamp, above the content. */
  header,
  /**
   * Content that spans the full content column, outside the page gutter.
   *
   * For the Atlas hero, which owns its own padding because it bleeds to the
   * edge. Everything else belongs in `children`, inside the measure.
   */
  bleed,
  /**
   * A persistent context column to the right of the work surface.
   *
   * Campaign-level context that must not reset as a person moves between
   * stages. Rendered as a third column from `xl`, and as a disclosure above
   * the content below that — the brief's "intentional stacked experience"
   * rather than a squeezed column. It is never a drawer that hides on desktop,
   * because context you have to open is context nobody reads.
   */
  aside,
  children,
}: {
  me: Me | null;
  activeOrganizationId: string | null;
  onOrganizationChange: (id: string) => void;
  rail?: React.ReactNode;
  header?: React.ReactNode;
  bleed?: React.ReactNode;
  aside?: React.ReactNode;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [drawerOpen, setDrawerOpen] = useState(false);

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

  // A navigation closes the drawer. Without this, tapping a link on a phone
  // leaves the drawer covering the page it just opened.
  useEffect(() => setDrawerOpen(false), [pathname]);

  const membership = me?.organizations.find((m) => m.organization.id === activeOrganizationId);
  const capabilities = capabilitiesFor(membership?.role ?? (me ? 'viewer' : null));

  const navigation = (
    <NavigationBody
      me={me}
      activeOrganizationId={activeOrganizationId}
      onOrganizationChange={onOrganizationChange}
      pathname={pathname}
      rail={rail}
      demo={demo}
      roleLabel={capabilities.unknown ? null : ROLE_LABEL[capabilities.role]}
    />
  );

  return (
    <div className="min-h-screen lg:flex">
      {/* First in the tab order: a keyboard user should not walk the whole
          rail on every page to reach the content. */}
      <a
        href="#main"
        className="skip-link absolute z-30 m-2 rounded-md bg-ink px-3 py-2 text-body text-surface"
      >
        Skip to content
      </a>

      {/* ---------------------------------------------------- desktop rail */}
      <div className="hidden w-64 shrink-0 border-r border-line lg:block">
        <div className="sticky top-0 flex h-screen flex-col overflow-y-auto px-4 py-5">
          {navigation}
        </div>
      </div>

      {/* ------------------------------------------------- compact top bar */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-b border-line lg:hidden">
          <div className="flex min-h-14 items-center gap-3 px-gutter">
            <MenuButton onOpen={() => setDrawerOpen(true)} />
            <Link href="/app" className="text-body font-semibold tracking-tight">
              campaign-os
            </Link>
            <div className="ml-auto flex items-center gap-2">
              {demo ? (
                <StatusBadge tone="active" title="Mock providers only — nothing leaves this machine.">
                  Demo
                </StatusBadge>
              ) : null}
            </div>
          </div>
          {/* The Meridian sits under the bar on compact widths, where a
              vertical rail has nowhere to go. */}
          {rail ? <div className="border-t border-line px-gutter pt-3">{rail}</div> : null}
        </header>

        {drawerOpen ? <Drawer onClose={() => setDrawerOpen(false)}>{navigation}</Drawer> : null}

        {bleed}

        {header ? (
          <div className="border-b border-line px-gutter py-5 sm:px-gutter-lg lg:px-xl">
            <div className="mx-auto max-w-page">{header}</div>
          </div>
        ) : null}

        {aside ? (
          <div className="mx-auto flex w-full max-w-[100rem] flex-1 flex-col xl:flex-row xl:items-start xl:gap-xl xl:px-xl">
            <main
              id="main"
              className="min-w-0 flex-1 px-gutter py-8 sm:px-gutter-lg sm:py-10 xl:px-0"
            >
              {/* Narrower than the full page measure, because a work surface
                  beside a context column should not also be full width. */}
              <div className="mx-auto max-w-page xl:mx-0">{children}</div>
            </main>
            <aside className="w-full shrink-0 px-gutter pb-10 sm:px-gutter-lg xl:sticky xl:top-6 xl:w-80 xl:px-0 xl:py-10">
              {aside}
            </aside>
          </div>
        ) : (
          <main id="main" className="px-gutter py-8 sm:px-gutter-lg sm:py-10 lg:px-xl">
            <div className="mx-auto max-w-page">{children}</div>
          </main>
        )}
      </div>
    </div>
  );
}

// -------------------------------------------------------------- navigation

/**
 * The rail's contents, rendered once and placed twice — in the desktop column
 * and inside the drawer. One definition, so the two cannot drift into showing
 * different navigation, which is a bug users notice and reviewers do not.
 */
function NavigationBody({
  me,
  activeOrganizationId,
  onOrganizationChange,
  pathname,
  rail,
  demo,
  roleLabel,
}: {
  me: Me | null;
  activeOrganizationId: string | null;
  onOrganizationChange: (id: string) => void;
  pathname: string | null;
  rail?: React.ReactNode;
  demo: boolean | null;
  roleLabel: string | null;
}) {
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <Link href="/app" className="text-h3 tracking-tight">
          campaign-os
        </Link>
        {demo ? (
          <StatusBadge tone="active" title="Mock providers only — nothing leaves this machine.">
            Demo mode
          </StatusBadge>
        ) : null}
      </div>

      {me && me.organizations.length > 0 ? (
        <label className="mt-5 block">
          <span className="text-label uppercase text-muted">Organization</span>
          <Select
            value={activeOrganizationId ?? ''}
            onChange={(e) => onOrganizationChange(e.target.value)}
            className="mt-1.5 py-1.5 text-small"
          >
            {me.organizations.map(({ organization }) => (
              <option key={organization.id} value={organization.id}>
                {organization.name}
              </option>
            ))}
          </Select>
        </label>
      ) : null}

      <nav aria-label="Primary" className="mt-6">
        <ul className="space-y-0.5">
          {PRODUCT_NAV.map((item) => {
            const current = isCurrent(item.href, pathname);
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  aria-current={current ? 'page' : undefined}
                  className={cx(
                    'block rounded-md px-2.5 py-2 transition-colors duration-fast ease-out',
                    current
                      ? // The accent bar, not colour alone, is what marks the
                        // current destination.
                        'border-l-2 border-accent bg-line/40 pl-2 font-medium text-ink'
                      : 'text-muted hover:bg-line/30 hover:text-ink',
                  )}
                >
                  <span className="block text-body">{item.label}</span>
                  <span className="mt-0.5 block text-caption text-muted">{item.hint}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* The campaign journey, when there is one. Below the product
          navigation, because it is navigation *within* the place you are. */}
      {rail ? (
        <div className="mt-7 border-t border-line pt-5">
          <p className="mb-2 px-2.5 text-label uppercase text-muted">This campaign</p>
          {rail}
        </div>
      ) : null}

      <div className="mt-auto pt-8">
        <Identity me={me} roleLabel={roleLabel} />
      </div>
    </>
  );
}

function Identity({ me, roleLabel }: { me: Me | null; roleLabel: string | null }) {
  const router = useRouter();
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => setSignedIn(hasLiveSession()), []);

  return (
    <div className="border-t border-line pt-4">
      <p className="truncate text-small text-ink">{me?.user.email ?? '—'}</p>
      {roleLabel ? (
        // Shown because the interface behaves differently per role, and a
        // person who cannot see an Approve button deserves to know why.
        <p className="mt-0.5 text-label uppercase text-muted">{roleLabel}</p>
      ) : null}
      {signedIn ? (
        <Button
          variant="ghost"
          size="sm"
          className="mt-2 -ml-3"
          onClick={() => {
            // Local state is cleared first inside `signOut`, so the redirect
            // can never race a still-authenticated request.
            void signOut().then(() => router.replace('/app/signin'));
          }}
        >
          Sign out
        </Button>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------ drawer

function MenuButton({ onOpen }: { onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label="Open navigation"
      className="-ml-1 rounded-md p-1.5 text-muted transition-colors duration-fast hover:bg-line/40 hover:text-ink"
    >
      {/* Decorative: the button's accessible name is on the button. */}
      <svg aria-hidden="true" viewBox="0 0 20 20" className="h-5 w-5" fill="none">
        <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    </button>
  );
}

/**
 * The compact-width navigation drawer.
 *
 * Focus handling is the whole job here, and it is the part that is usually
 * skipped: focus moves in on open, `Escape` closes, `Tab` cycles inside rather
 * than escaping to the page behind, and focus returns to the button that
 * opened it. Without the last one a keyboard user is dropped at the top of the
 * document every time they close it.
 */
function Drawer({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();

  const focusables = useCallback(
    () =>
      Array.from(
        panel.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), select, input, [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ),
    [],
  );

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    focusables()[0]?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = focusables();
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) return;
      // Wrap at both ends, so focus cannot reach the page under the overlay.
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      // Back to where they were, not to the top of the document.
      opener?.focus?.();
    };
  }, [focusables, onClose]);

  return (
    <div className="fixed inset-0 z-20 lg:hidden">
      {/* The scrim closes on click but is not a control: the keyboard route
          out is Escape, and the drawer holds its own focus. */}
      <div
        onClick={onClose}
        aria-hidden="true"
        className="absolute inset-0 bg-ink/40 transition-opacity duration-fast"
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="arrive absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col overflow-y-auto border-r border-line bg-surface px-4 py-5 shadow-modal"
      >
        <h2 id={titleId} className="sr-only">
          Navigation
        </h2>
        <button
          type="button"
          onClick={onClose}
          className="absolute right-3 top-3 rounded-md p-1.5 text-muted hover:bg-line/40 hover:text-ink"
          aria-label="Close navigation"
        >
          <svg aria-hidden="true" viewBox="0 0 20 20" className="h-4 w-4" fill="none">
            <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </button>
        {children}
      </div>
    </div>
  );
}
