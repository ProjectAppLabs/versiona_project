'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { Menu, X } from 'lucide-react';

import { LocaleToggle } from '@/components/locale-toggle';
import { ThemeToggle } from '@/components/theme-toggle';
import { ROUTES } from '@/lib/constants';
import { useDict } from '@/lib/i18n/dictionaries';

export function PublicHeader() {
  const t = useDict('marketing');
  const common = useDict('common');
  const [open, setOpen] = useState(false);
  const headerRef = useRef<HTMLElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = () => {
      setOpen(false);
      menuButtonRef.current?.focus();
    };
    const onClick = (event: MouseEvent) => {
      // A popover can unmount its clicked item before this listener runs.
      const header = headerRef.current;
      if (header && !event.composedPath().includes(header)) close();
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

  const navLinks = [
    { href: ROUTES.COMPARAR, label: t.navCompare },
    { href: ROUTES.PRECIOS, label: t.navPricing },
    { href: ROUTES.HELP, label: t.navManual },
  ];

  return (
    <header
      ref={headerRef}
      data-testid="public-header"
      className="sticky top-0 z-40 border-b border-border bg-card/80 backdrop-blur"
    >
      <div className="max-w-6xl mx-auto px-6 py-4 flex flex-wrap items-center justify-between gap-4 lg:flex-nowrap">
        <Link className="inline-flex min-h-11 items-center font-semibold tracking-tight" href={ROUTES.HOME} onClick={closeNavigation}>
          Versiona
        </Link>

        <button
          ref={menuButtonRef}
          type="button"
          data-testid="public-nav-toggle"
          aria-label={open ? common.close : t.navToggle}
          aria-expanded={open}
          aria-controls="public-navigation"
          onClick={() => {
            if (open) closeNavigation();
            else setOpen(true);
          }}
          className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:hidden"
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>

        <nav
          id="public-navigation"
          data-testid="public-nav-menu"
          className={`${open ? 'flex' : 'hidden'} basis-full flex-col items-start gap-2 border-t border-border pt-4 text-sm lg:flex lg:basis-auto lg:flex-row lg:items-center lg:border-0 lg:pt-0`}
        >
          {navLinks.map((link) => (
            <Link
              key={link.href}
              className="inline-flex min-h-11 min-w-11 items-center px-2 py-2 rounded hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              href={link.href}
              onClick={closeNavigation}
            >
              {link.label}
            </Link>
          ))}
          <LocaleToggle />
          <ThemeToggle />
          <Link
            className="inline-flex min-h-11 items-center justify-center border border-border rounded-full px-4 py-2 hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            href={ROUTES.SIGN_IN}
            onClick={closeNavigation}
          >
            {common.signIn}
          </Link>
          <Link
            className="inline-flex min-h-11 items-center justify-center bg-primary text-primary-foreground rounded-full px-4 py-2 hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            href={ROUTES.SIGN_UP}
            onClick={closeNavigation}
          >
            {t.navSignUp}
          </Link>
        </nav>
      </div>
    </header>
  );
}
