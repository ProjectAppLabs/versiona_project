import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { PublicHeader } from '../PublicHeader';
import { useLocaleStore } from '@/lib/stores/localeStore';

const initialLocale = useLocaleStore.getState();

describe('Public header navigation', () => {
  beforeEach(() => useLocaleStore.setState({ locale: 'es' }));
  afterEach(() => {
    useLocaleStore.setState(initialLocale);
    localStorage.clear();
  });

  it('opens the navigation with its original destinations', async () => {
    const user = userEvent.setup();
    render(<PublicHeader />);

    await user.click(screen.getByTestId('public-nav-toggle'));

    expect(screen.getByTestId('public-nav-toggle')).toHaveAttribute('aria-expanded', 'true');
    expect(within(screen.getByTestId('public-nav-menu')).getAllByRole('link').map((link) => [
      link.textContent, link.getAttribute('href'),
    ])).toEqual([
      ['Comparar PDFs', '/comparar'],
      ['Precios', '/precios'],
      ['Manual', '/manual'],
      ['Iniciar sesión', '/sign-in'],
      ['Crear cuenta gratis', '/sign-up'],
    ]);
  });

  it('returns focus to the opener after Escape from a navigation link', async () => {
    const user = userEvent.setup();
    render(<PublicHeader />);
    const toggle = screen.getByTestId('public-nav-toggle');
    await user.click(toggle);
    screen.getByRole('link', { name: 'Manual' }).focus();

    await user.keyboard('{Escape}');

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveFocus();
  });

  it('returns focus to the opener after a pointer outside the header', async () => {
    const user = userEvent.setup();
    render(<><PublicHeader /><main>Contenido</main></>);
    const toggle = screen.getByTestId('public-nav-toggle');
    await user.click(toggle);

    await user.click(screen.getByRole('main'));

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveFocus();
  });

  it('closes the navigation with the same menu button', async () => {
    const user = userEvent.setup();
    render(<PublicHeader />);
    const toggle = screen.getByTestId('public-nav-toggle');
    await user.click(toggle);

    await user.click(screen.getByRole('button', { name: 'Cerrar' }));

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveFocus();
  });

  it('closes the navigation when its destination is chosen', async () => {
    const user = userEvent.setup();
    render(<PublicHeader />);
    const toggle = screen.getByTestId('public-nav-toggle');
    await user.click(toggle);

    fireEvent.click(screen.getByRole('link', { name: 'Precios' }));

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveFocus();
  });

  it('keeps the expanded navigation translated after changing locale', async () => {
    const user = userEvent.setup();
    render(<PublicHeader />);
    await user.click(screen.getByTestId('public-nav-toggle'));

    await user.click(screen.getByRole('button', { name: 'Switch to English' }));

    expect(within(screen.getByTestId('public-nav-menu')).getAllByRole('link').map((link) => (
      link.textContent
    ))).toEqual(['Compare PDFs', 'Pricing', 'Manual', 'Sign in', 'Create free account']);
    expect(screen.getByTestId('public-nav-toggle')).toHaveAttribute('aria-expanded', 'true');
  });

  it('keeps the navigation open after selecting a theme', async () => {
    const user = userEvent.setup();
    render(<PublicHeader />);
    const toggle = screen.getByTestId('public-nav-toggle');
    await user.click(toggle);
    const themeToggle = screen.getByRole('button', { name: 'Toggle theme' });
    await user.click(themeToggle);

    await user.click(screen.getByRole('menuitemradio', { name: 'Dark' }));

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(themeToggle).toHaveFocus();
  });
});
