import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderToString } from 'react-dom/server';

import Header from '../Header';
import { api } from '@/lib/services/http';
import { useAuthStore } from '@/lib/stores/authStore';
import { useLocaleStore } from '@/lib/stores/localeStore';
import { useNotificationStore } from '@/lib/stores/notificationStore';
import { useOrgStore } from '@/lib/stores/orgStore';

jest.mock('@/lib/services/http', () => ({
  api: { get: jest.fn() },
}));

const initialAuth = useAuthStore.getState();
const initialOrgs = useOrgStore.getState();
const initialNotifications = useNotificationStore.getState();
const initialLocale = useLocaleStore.getState();

describe('Authenticated header navigation', () => {
  beforeEach(() => {
    (api.get as jest.Mock).mockResolvedValue({ data: { results: [], unread: 0 } });
    useAuthStore.setState({ isAuthenticated: true });
    useOrgStore.setState({
      orgs: [{ public_id: 'org-1', name: 'Acme', slug: 'acme', kind: 'team', role: 'admin' }],
    });
    useNotificationStore.setState({ items: [], unread: 0 });
    useLocaleStore.setState({ locale: 'es' });
  });

  afterEach(() => {
    useAuthStore.setState(initialAuth);
    useOrgStore.setState(initialOrgs);
    useNotificationStore.setState(initialNotifications);
    useLocaleStore.setState(initialLocale);
    localStorage.clear();
    jest.clearAllMocks();
  });

  it('opens the navigation with its original destinations', async () => {
    const user = userEvent.setup();
    render(<Header />);

    await user.click(screen.getByTestId('app-nav-toggle'));

    expect(screen.getByTestId('app-nav-toggle')).toHaveAttribute('aria-expanded', 'true');
    expect(within(screen.getByTestId('app-nav-menu')).getAllByRole('link').map((link) => [
      link.textContent, link.getAttribute('href'),
    ])).toEqual([
      ['Ayuda', '/manual'],
      ['Panel', '/projects'],
      ['Plan y uso', '/org/usage'],
      ['Papelera', '/org/trash'],
      ['Configuración', '/settings'],
    ]);
  });

  it('returns focus to the opener after Escape from a navigation link', async () => {
    const user = userEvent.setup();
    render(<Header />);
    const toggle = screen.getByTestId('app-nav-toggle');
    await user.click(toggle);
    screen.getByRole('link', { name: 'Plan y uso' }).focus();

    await user.keyboard('{Escape}');

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveFocus();
  });

  it('returns focus to the opener after a pointer outside the header', async () => {
    const user = userEvent.setup();
    render(<><Header /><main>Contenido</main></>);
    const toggle = screen.getByTestId('app-nav-toggle');
    await user.click(toggle);

    await user.click(screen.getByRole('main'));

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveFocus();
  });

  it('closes the navigation when its destination is chosen', async () => {
    const user = userEvent.setup();
    render(<Header />);
    const toggle = screen.getByTestId('app-nav-toggle');
    await user.click(toggle);

    fireEvent.click(screen.getByRole('link', { name: 'Configuración' }));

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveFocus();
  });

  it('signs out through the expanded navigation', async () => {
    const user = userEvent.setup();
    render(<Header />);
    await user.click(screen.getByTestId('app-nav-toggle'));

    await user.click(screen.getByRole('button', { name: 'Salir' }));

    expect(screen.getByTestId('public-header')).toBeInTheDocument();
    expect(screen.queryByTestId('app-header')).not.toBeInTheDocument();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it('keeps the navigation open after selecting a theme', async () => {
    const user = userEvent.setup();
    render(<Header />);
    const toggle = screen.getByTestId('app-nav-toggle');
    await user.click(toggle);
    const themeToggle = screen.getByRole('button', { name: 'Toggle theme' });
    await user.click(themeToggle);

    await user.click(screen.getByRole('menuitemradio', { name: 'Dark' }));

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(themeToggle).toHaveFocus();
  });

  it('renders the public header before the browser has mounted', () => {
    const html = renderToString(<Header />);

    expect(html).toContain('data-testid="public-header"');
    expect(html).not.toContain('data-testid="app-header"');
  });
});
