import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { GoogleLinkPanel } from '../GoogleLinkPanel';
import { saveGoogleLinkTicket, getGoogleLinkTicket } from '../../../lib/services/google-link-ticket';
import { api } from '../../../lib/services/http';
import { setTokens } from '../../../lib/services/tokens';

const mockPush = jest.fn();
const mockSignOut = jest.fn();
const mockSync = jest.fn();
const mockSetState = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush }) }));
jest.mock('../../../lib/stores/authStore', () => ({ useAuthStore: {
  getState: () => ({ signOut: mockSignOut, syncFromCookies: mockSync }), setState: (...args: unknown[]) => mockSetState(...args),
} }));
jest.mock('../../../lib/services/http', () => ({ api: { post: jest.fn() } }));
jest.mock('../../../lib/services/tokens', () => ({ setTokens: jest.fn() }));
jest.mock('@react-oauth/google', () => ({ GoogleLogin: ({ onSuccess }: { onSuccess: (result: { credential: string }) => void }) => <button type="button" onClick={() => onSuccess({ credential: 'google-proof' })}>Choose Google</button> }));

const post = api.post as jest.Mock;
const onLinked = jest.fn().mockResolvedValue(undefined);
function renderPanel(totpEnabled = false, linked = false, hasUsablePassword = true) {
  return render(<GoogleLinkPanel linked={linked} hasUsablePassword={hasUsablePassword} totpEnabled={totpEnabled} onLinked={onLinked} />);
}
async function fillForm() {
  fireEvent.change(await screen.findByTestId('google-link-current'), { target: { value: 'current-password' } });
  fireEvent.change(screen.getByTestId('google-link-new'), { target: { value: 'different-password' } });
  fireEvent.change(screen.getByTestId('google-link-confirm'), { target: { value: 'different-password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Choose Google' }));
}

beforeEach(() => {
  jest.clearAllMocks(); sessionStorage.clear(); localStorage.clear();
  process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID = 'client';
});

it('requires recovery before offering a linking form', async () => {
  renderPanel();
  fireEvent.click(await screen.findByTestId('google-link-recover'));
  expect(mockSignOut).toHaveBeenCalled();
  expect(mockSignOut.mock.invocationCallOrder[0]).toBeLessThan(mockPush.mock.invocationCallOrder[0]);
  expect(mockPush).toHaveBeenCalledWith('/forgot-password');
  expect(post).not.toHaveBeenCalled();
});

it('shows linked state without offering identity replacement', () => {
  renderPanel(false, true, false);
  expect(screen.getByText('Tu cuenta ya está vinculada con Google.')).toBeInTheDocument();
  expect(screen.queryByTestId('google-link-form')).not.toBeInTheDocument();
});

it('offers recovery to an unlinked account with no usable password', () => {
  saveGoogleLinkTicket('email-proof');
  renderPanel(false, false, false);
  expect(screen.queryByTestId('google-link-form')).not.toBeInTheDocument();
  expect(screen.getByTestId('google-link-recover')).toBeInTheDocument();
});

it('replaces the complete session after verified linking', async () => {
  saveGoogleLinkTicket('email-proof');
  const user = { id: 1, email: 'same@example.com' };
  post.mockResolvedValueOnce({ data: { access: 'new-access', refresh: 'new-refresh', user } });
  renderPanel(true);
  await fillForm();
  expect(screen.getByTestId('google-link-submit')).toBeDisabled();
  fireEvent.change(screen.getByTestId('google-link-code'), { target: { value: 'backup-code' } });
  fireEvent.click(screen.getByTestId('google-link-submit'));
  await waitFor(() => expect(onLinked).toHaveBeenCalled());
  expect(post).toHaveBeenCalledWith('me/google/link/', { credential: 'google-proof', google_link_ticket: 'email-proof', current_password: 'current-password', new_password: 'different-password', code: 'backup-code' });
  expect(setTokens).toHaveBeenCalledWith({ access: 'new-access', refresh: 'new-refresh' });
  expect(mockSync).toHaveBeenCalled();
  expect(mockSetState).toHaveBeenCalledWith({ user });
  expect(getGoogleLinkTicket()).toBeNull();
  expect(screen.queryByTestId('google-link-current')).not.toBeInTheDocument();
});

it('stops linking when the recovery proof expires while the form is open', async () => {
  saveGoogleLinkTicket('email-proof');
  renderPanel();
  await fillForm();
  sessionStorage.clear();
  fireEvent.click(screen.getByTestId('google-link-submit'));
  expect(await screen.findByRole('alert')).toHaveTextContent('La verificación del correo venció');
  expect(post).not.toHaveBeenCalled();
});

it('requires a different new password', async () => {
  saveGoogleLinkTicket('email-proof');
  renderPanel(); await fillForm();
  fireEvent.change(screen.getByTestId('google-link-new'), { target: { value: 'current-password' } });
  fireEvent.change(screen.getByTestId('google-link-confirm'), { target: { value: 'current-password' } });
  fireEvent.click(screen.getByTestId('google-link-submit'));
  expect(await screen.findByRole('alert')).toHaveTextContent('debe ser distinta');
  expect(post).not.toHaveBeenCalled();
});

it('does not offer to repeat a mutation with an uncertain response', async () => {
  saveGoogleLinkTicket('email-proof'); post.mockRejectedValueOnce(new Error('network lost'));
  renderPanel(); await fillForm();
  fireEvent.click(screen.getByTestId('google-link-submit'));
  expect(await screen.findByRole('alert')).toHaveTextContent('Inicia sesión con tu nueva contraseña');
  expect(screen.queryByTestId('google-link-submit')).not.toBeInTheDocument();
  expect(post).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Iniciar sesión con la nueva contraseña' }));
  expect(mockPush).toHaveBeenCalledWith('/sign-in?next=/settings');
});

it('allows correcting a definitive verification rejection', async () => {
  saveGoogleLinkTicket('email-proof');
  post.mockRejectedValueOnce({ response: { status: 403, data: { error: 'Código incorrecto' } } });
  renderPanel(); await fillForm(); fireEvent.click(screen.getByTestId('google-link-submit'));
  expect(await screen.findByRole('alert')).toHaveTextContent('Código incorrecto');
  expect(screen.getByTestId('google-link-submit')).toBeEnabled();
  expect(getGoogleLinkTicket()).toBe('email-proof');
});
