import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider } from 'next-themes';

import { LocaleToggle } from '../locale-toggle';
import { ThemeToggle } from '../theme-toggle';
import { useLocaleStore } from '@/lib/stores/localeStore';

const initialLocale = useLocaleStore.getState();

describe('Navigation preferences', () => {
  afterEach(() => {
    useLocaleStore.setState(initialLocale);
    localStorage.clear();
    document.documentElement.removeAttribute('class');
  });

  it.each(['light', 'dark', 'system'] as const)('applies the %s theme from the menu', async (theme) => {
    const user = userEvent.setup();
    render(<ThemeProvider attribute="class" defaultTheme="system"><ThemeToggle /></ThemeProvider>);
    const toggle = screen.getByRole('button', { name: 'Toggle theme' });
    await user.click(toggle);

    await user.click(screen.getByRole('menuitemradio', { name: new RegExp(theme, 'i') }));

    expect(localStorage.getItem('theme')).toBe(theme);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveFocus();
  });

  it('returns focus to the theme opener after keyboard dismissal', async () => {
    const user = userEvent.setup();
    render(<ThemeProvider><ThemeToggle /></ThemeProvider>);
    const toggle = screen.getByRole('button', { name: 'Toggle theme' });
    toggle.focus();
    await user.keyboard('{ArrowDown}{End}');
    expect(screen.getByRole('menuitemradio', { name: 'System' })).toHaveFocus();

    await user.keyboard('{Escape}');

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveFocus();
  });

  it.each([
    { locale: 'es', label: 'Switch to English', next: 'en', nextLabel: 'Cambiar a español' },
    { locale: 'en', label: 'Cambiar a español', next: 'es', nextLabel: 'Switch to English' },
  ] as const)('switches the $locale locale from its accessible control', async ({ locale, label, next, nextLabel }) => {
    const user = userEvent.setup();
    useLocaleStore.setState({ locale });
    render(<LocaleToggle />);

    await user.click(screen.getByRole('button', { name: label }));

    expect(useLocaleStore.getState().locale).toBe(next);
    expect(screen.getByRole('button', { name: nextLabel })).toBeInTheDocument();
  });
});
