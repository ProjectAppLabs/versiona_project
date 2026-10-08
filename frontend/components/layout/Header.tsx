'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { Menu, X } from 'lucide-react';

import { PublicHeader } from '@/components/marketing/PublicHeader';
import { NotificationBell } from '@/components/notifications/NotificationBell';
import { ThemeToggle } from '@/components/theme-toggle';
import { ROUTES } from '@/lib/constants';
import { useAuthStore } from '@/lib/stores/authStore';
import { useOrgStore } from '@/lib/stores/orgStore';
import { useDict } from '@/lib/i18n/dictionaries';
import { useMounted } from '@/lib/hooks/useMounted';

export default function Header() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const signOut = useAuthStore((s) => s.signOut);
  const t = useDict('common');
  const marketing = useDict('marketing');
  const orgs = useOrgStore((s) => s.orgs);
  const fetchOrgs = useOrgStore((s) => s.fetchOrgs);
  const [open, setOpen] = useState(false);
  const headerRef = useRef<HTMLElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  // authStore seeds isAuthenticated from a cookie via js-cookie, which is
  // browser-only: the server always computes `false` and the client `true` for a
  // signed-in visitor. Branching the tree on it directly meant server and client
  // rendered DIFFERENT navs, and React reported a hydration mismatch on every
  // authenticated page load — which also lets it discard the server HTML and
  // re-render the whole tree. Same fix as theme-toggle and locale-toggle: render
  // the server-consistent branch until mounted, then swap deliberately.
  const mounted = useMounted();

  useEffect(() => {
    if (isAuthenticated && orgs.length === 0) void fetchOrgs();
  }, [isAuthenticated, orgs.length, fetchOrgs]);

  useEffect(() => {
    if (!open) return;
    const close = () => {
      setOpen(false);
      menuButtonRef.current?.focus();
    };
    const onClick = (event: MouseEvent) => {
      if (!headerRef.current?.contains(event.target as Node)) close();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented) {
        event.preventDefault();
        close();
      }
    };
    document.addEventListener('click', onClick);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('click', onClick);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  function closeNavigation() {
    setOpen(false);
    menuButtonRef.current?.focus();
  }

  // The trash is an org-admin surface (docs/plan/03 §3): hide it for everyone
  // else instead of letting them walk into a 403.
  const canSeeTrash = orgs.some((org) => org.role === 'owner' || org.role === 'admin');

  if (!mounted || !isAuthenticated) {
    return <PublicHeader />;
  }

  return (
    <header ref={headerRef} data-testid="app-header" className="sticky top-0 z-40 border-b border-border bg-card/80 backdrop-blur">
      <div className="max-w-6xl mx-auto px-6 py-4 flex flex-wrap items-center justify-between gap-4 lg:flex-nowrap">
        <Link className="inline-flex min-h-11 items-center font-semibold tracking-tight" href="/" onClick={closeNavigation}>
          Versiona
        </Link>

        <button
          ref={menuButtonRef}
          type="button"
          data-testid="app-nav-toggle"
          aria-label={open ? t.close : marketing.navToggle}
          aria-expanded={open}
          aria-controls="app-navigation"
          onClick={() => {
            if (open) closeNavigation();
            else setOpen(true);
          }}
          className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:hidden"
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>

        <nav
          id="app-navigation"
          data-testid="app-nav-menu"
          onClick={(event) => {
            if (event.target instanceof Element && event.target.closest('a')) closeNavigation();
          }}
          className={`${open ? 'flex' : 'hidden'} basis-full flex-col items-start gap-2 border-t border-border pt-4 text-sm lg:flex lg:basis-auto lg:flex-row lg:items-center lg:gap-4 lg:border-0 lg:pt-0`}
        >
          <Link
            className="inline-flex min-h-11 min-w-11 items-center px-2 py-2 rounded hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            href={ROUTES.HELP}
          >
            {t.help}
          </Link>

          <ThemeToggle />

          <Link
            className="inline-flex min-h-11 min-w-11 items-center px-2 py-2 rounded hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            href="/projects"
          >{t.panel}</Link>
          <Link
            data-testid="nav-plan-usage"
            className="inline-flex min-h-11 min-w-11 items-center px-2 py-2 rounded hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            href={ROUTES.ORG_USAGE}
          >{t.planUsage}</Link>
          {canSeeTrash ? (
            <Link
              className="inline-flex min-h-11 min-w-11 items-center px-2 py-2 rounded hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              href="/org/trash"
            >
              {t.trash}
            </Link>
          ) : null}
          <Link
            className="inline-flex min-h-11 min-w-11 items-center px-2 py-2 rounded hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            href="/settings"
          >{t.settings}</Link>
          <NotificationBell />
          <button
            className="inline-flex min-h-11 items-center justify-center border border-border rounded-full px-4 py-2 hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => {
              closeNavigation();
              signOut();
            }}
            type="button"
          >{t.signOut}</button>
        </nav>
      </div>
    </header>
  );
}
