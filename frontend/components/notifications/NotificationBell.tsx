'use client';

/** Header bell (kit 5): unread badge + quick dropdown; full center at /inbox. */

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';

import { useDict } from '@/lib/i18n/dictionaries';
import { useNotificationStore } from '@/lib/stores/notificationStore';

export function NotificationBell() {
  const t = useDict('notifications');
  const items = useNotificationStore((s) => s.items);
  const unread = useNotificationStore((s) => s.unread);
  const fetch = useNotificationStore((s) => s.fetch);
  const markRead = useNotificationStore((s) => s.markRead);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void fetch();
    const interval = setInterval(() => void fetch(), 60_000);
    return () => clearInterval(interval);
  }, [fetch]);

  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [open]);

  return (
    <div ref={containerRef} className="relative w-fit shrink-0">
      <button
        data-testid="notification-bell"
        aria-label={t.title}
        aria-expanded={open}
        className="relative inline-flex h-11 w-11 items-center justify-center rounded-full p-2 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <svg
          className="h-5 w-5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          viewBox="0 0 24 24"
          aria-hidden
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M14.857 17.082a23.848 23.848 0 0 0 5.454-1.31A8.967 8.967 0 0 1 18 9.75V9A6 6 0 0 0 6 9v.75a8.967 8.967 0 0 1-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 0 1-5.714 0m5.714 0a3 3 0 1 1-5.714 0"
          />
        </svg>
        {unread > 0 ? (
          <span
            data-testid="notification-badge"
            className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold text-white"
          >
            {unread > 9 ? '9+' : unread}
          </span>
        ) : null}
      </button>

      {open ? (
        <div
          data-testid="notification-dropdown"
          className="absolute left-0 z-50 mt-2 w-80 max-w-[calc(100vw-3rem)] rounded-2xl border border-border bg-card p-2 shadow-lg lg:left-auto lg:right-0"
        >
          {items.length === 0 ? (
            <p className="px-3 py-4 text-sm text-muted-foreground">{t.empty}</p>
          ) : (
            <ul className="flex max-h-96 flex-col gap-2 overflow-y-auto">
              {items.slice(0, 6).map((item) => (
                <li key={item.public_id}>
                  <Link
                    className={`block min-h-11 rounded-xl px-3 py-2 text-sm hover:bg-accent ${
                      item.read_at ? 'opacity-60' : ''
                    }`}
                    href={item.link || '/inbox'}
                    onClick={() => {
                      void markRead(item.public_id);
                      setOpen(false);
                    }}
                  >
                    <p className="line-clamp-2 font-medium">{item.title}</p>
                    <p className="line-clamp-1 text-xs text-muted-foreground">{item.body}</p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <Link
            className="mt-2 flex min-h-11 items-center justify-center rounded-xl px-3 py-2 text-center text-sm text-primary hover:bg-accent"
            href="/inbox"
            onClick={() => setOpen(false)}
          >
            {t.viewAll}
          </Link>
        </div>
      ) : null}
    </div>
  );
}
