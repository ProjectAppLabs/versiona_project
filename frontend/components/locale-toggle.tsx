'use client';

/**
 * LocaleToggle — one-tap ES ⇄ EN switch over localeStore (persisted).
 * Anonymous visitors get a local preference; authed users still sync their
 * profile language from /settings. Mounted-guard mirrors ThemeToggle.
 */
import { useLocaleStore } from '@/lib/stores/localeStore';
import { useMounted } from '@/lib/hooks/useMounted';

export function LocaleToggle() {
  const locale = useLocaleStore((s) => s.locale);
  const setLocale = useLocaleStore((s) => s.setLocale);
  const mounted = useMounted();

  if (!mounted) {
    return <div className="h-11 w-11" aria-hidden />;
  }

  const next = locale === 'es' ? 'en' : 'es';

  return (
    <button
      type="button"
      data-testid="locale-toggle"
      aria-label={locale === 'es' ? 'Switch to English' : 'Cambiar a español'}
      onClick={() => setLocale(next)}
      className="inline-flex h-11 min-w-11 items-center justify-center rounded-full px-2.5 text-xs font-semibold uppercase tracking-wide text-foreground hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring transition-colors"
    >
      {next}
    </button>
  );
}
