import { describe, it, expect, beforeEach, afterEach } from '@jest/globals';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import SignInPage from '../page';
import { useAuthStore } from '../../../lib/stores/authStore';
import { useRouter } from 'next/navigation';
import { jwtDecode } from 'jwt-decode';

let mockGoogleCredential: string | null = 'token';
let mockGoogleError = false;

jest.mock('@react-oauth/google', () => ({
  GoogleLogin: ({ onSuccess, onError }: any) => (
    <button
      type="button"
      onClick={() => {
        if (mockGoogleError) {
          onError?.();
          return;
        }
        onSuccess?.({ credential: mockGoogleCredential ?? undefined });
      }}
    >
      Google Login
    </button>
  ),
}));

jest.mock('react-google-recaptcha', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require('react');
  const MockRecaptcha = React.forwardRef(
    ({ onChange: _onChange }: { onChange?: (token: string | null) => void }, ref: any) => {
      React.useImperativeHandle(ref, () => ({ reset: () => {} }));
      return <div data-testid="mock-recaptcha" />;
    },
  );
  MockRecaptcha.displayName = 'MockRecaptcha';
  return MockRecaptcha;
});

jest.mock('../../../lib/services/http', () => ({
  api: { get: jest.fn().mockRejectedValue(new Error('no key')), post: jest.fn() },
}));

jest.mock('next/navigation', () => ({
  useRouter: jest.fn(),
}));

jest.mock('jwt-decode', () => ({
  jwtDecode: jest.fn(),
}));

jest.mock('../../../lib/stores/authStore', () => ({
  useAuthStore: jest.fn(),
}));

const mockUseAuthStore = useAuthStore as unknown as jest.Mock;
const mockUseRouter = useRouter as unknown as jest.Mock;
const mockJwtDecode = jwtDecode as unknown as jest.Mock;
let user: ReturnType<typeof userEvent.setup>;

const setAuthStoreState = (state: any) => {
  mockUseAuthStore.mockImplementation((selector?: (store: any) => unknown) =>
    selector ? selector(state) : state
  );
};

describe('SignInPage', () => {
  const originalGoogleClientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;

  beforeEach(() => {
    jest.clearAllMocks();
    mockGoogleCredential = 'token';
    mockGoogleError = false;
    process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID = 'test-client';
    window.history.pushState({}, '', '/sign-in');
    user = userEvent.setup();
  });

  afterEach(() => {
    if (originalGoogleClientId === undefined) {
      delete process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
    } else {
      process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID = originalGoogleClientId;
    }
  });

  it('renders missing Google Client ID message when env var not set', () => {
    delete process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
    setAuthStoreState({ signIn: jest.fn().mockResolvedValue({ requires2fa: false }), googleLogin: jest.fn() });
    mockUseRouter.mockReturnValue({ replace: jest.fn() });

    render(<SignInPage />);

    expect(screen.getByText('Missing NEXT_PUBLIC_GOOGLE_CLIENT_ID')).toBeInTheDocument();
  });

  it('signs in successfully and redirects', async () => {
    const signIn = jest.fn().mockResolvedValue({ requires2fa: false });
    setAuthStoreState({ signIn, googleLogin: jest.fn() });
    const replace = jest.fn();
    mockUseRouter.mockReturnValue({ replace });

    render(<SignInPage />);

    fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: 'user@example.com' } });
    const passwordInput = screen.getByPlaceholderText('Password');
    // Masking contract: catches a regression where the password field loses
    // type="password" and the credential is rendered in clear text on screen.
    expect(passwordInput).toHaveAttribute('type', 'password');
    fireEvent.change(passwordInput, { target: { value: 'password123' } });
    fireEvent.click(screen.getByRole('button', { name: 'Entrar' }));

    await waitFor(() => {
      expect(signIn).toHaveBeenCalledWith({ email: 'user@example.com', password: 'password123', captcha_token: undefined });
    });
    expect(replace).toHaveBeenCalledWith('/projects');
  });

  it('shows an error when sign in fails', async () => {
    const signIn = jest.fn().mockRejectedValue({ response: { data: { error: 'Invalid' } } });
    setAuthStoreState({ signIn, googleLogin: jest.fn() });
    mockUseRouter.mockReturnValue({ replace: jest.fn() });

    render(<SignInPage />);

    fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: 'user@example.com' } });
    fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'password123' } });
    fireEvent.click(screen.getByRole('button', { name: 'Entrar' }));

    expect(await screen.findByText('Invalid')).toBeInTheDocument();
  });

  it('shows default error when sign in fails without response', async () => {
    const signIn = jest.fn().mockRejectedValue(new Error('boom'));
    setAuthStoreState({ signIn, googleLogin: jest.fn() });
    mockUseRouter.mockReturnValue({ replace: jest.fn() });

    render(<SignInPage />);

    fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: 'user@example.com' } });
    fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'password123' } });
    fireEvent.click(screen.getByRole('button', { name: 'Entrar' }));

    expect(await screen.findByText('Credenciales inválidas')).toBeInTheDocument();
  });

  it('shows default error when sign in error payload is missing', async () => {
    const signIn = jest.fn().mockRejectedValue({ response: { data: null } });
    setAuthStoreState({ signIn, googleLogin: jest.fn() });
    mockUseRouter.mockReturnValue({ replace: jest.fn() });

    render(<SignInPage />);

    fireEvent.change(screen.getByPlaceholderText('Email'), { target: { value: 'user@example.com' } });
    fireEvent.change(screen.getByPlaceholderText('Password'), { target: { value: 'password123' } });
    fireEvent.click(screen.getByRole('button', { name: 'Entrar' }));

    expect(await screen.findByText('Credenciales inválidas')).toBeInTheDocument();
  });

  it('handles Google login success', async () => {
    const googleLogin = jest.fn().mockResolvedValue({ requires2fa: false });
    setAuthStoreState({ signIn: jest.fn().mockResolvedValue({ requires2fa: false }), googleLogin });
    const replace = jest.fn();
    mockUseRouter.mockReturnValue({ replace });
    mockJwtDecode.mockReturnValue({
      email: 'google@example.com',
      given_name: 'Google',
      family_name: 'User',
      picture: 'pic.png',
    });

    render(<SignInPage />);

    await user.click(screen.getByRole('button', { name: 'Google Login' }));

    await waitFor(() => {
      expect(googleLogin).toHaveBeenCalledWith({
        credential: 'token',
        email: 'google@example.com',
        given_name: 'Google',
        family_name: 'User',
        picture: 'pic.png',
      });
    });
    expect(replace).toHaveBeenCalledWith('/projects');
  });

  it('shows the TOTP form for a Google challenge', async () => {
    const googleLogin = jest.fn().mockResolvedValue({ requires2fa: true, challenge: 'challenge-1' });
    const replace = jest.fn();
    setAuthStoreState({
      signIn: jest.fn().mockResolvedValue({ requires2fa: false }),
      signIn2fa: jest.fn(),
      googleLogin,
    });
    mockUseRouter.mockReturnValue({ replace });
    mockJwtDecode.mockReturnValue({ email: 'google@example.com' });

    render(<SignInPage />);

    await user.click(screen.getByRole('button', { name: 'Google Login' }));

    // Fails if a Google account with TOTP is redirected before its second factor.
    expect(await screen.findByTestId('twofa-step')).toHaveTextContent('Verificación en dos pasos');
    expect(screen.getByTestId('twofa-verify')).toHaveTextContent('Verificar');
    expect(replace).not.toHaveBeenCalled();
  });

  it('keeps the TOTP form after an invalid Google challenge code', async () => {
    const googleLogin = jest.fn().mockResolvedValue({ requires2fa: true, challenge: 'challenge-1' });
    const signIn2fa = jest.fn().mockRejectedValue({ response: { data: { error: 'Código rechazado' } } });
    const replace = jest.fn();
    setAuthStoreState({
      signIn: jest.fn().mockResolvedValue({ requires2fa: false }),
      signIn2fa,
      googleLogin,
    });
    mockUseRouter.mockReturnValue({ replace });
    mockJwtDecode.mockReturnValue({ email: 'google@example.com' });

    render(<SignInPage />);

    await user.click(screen.getByRole('button', { name: 'Google Login' }));
    await screen.findByTestId('twofa-step');
    fireEvent.change(screen.getByTestId('twofa-code'), { target: { value: '123456' } });
    fireEvent.click(screen.getByTestId('twofa-verify'));

    // Fails if a rejected TOTP code discards the challenge or leaves the retry disabled.
    expect(await screen.findByRole('alert')).toHaveTextContent('Código rechazado');
    expect(screen.getByTestId('twofa-code')).toHaveValue('123456');
    expect(screen.getByTestId('twofa-verify')).toBeEnabled();
    expect(replace).not.toHaveBeenCalled();
  });

  it('routes to projects after verifying a Google challenge', async () => {
    const googleLogin = jest.fn().mockResolvedValue({ requires2fa: true, challenge: 'challenge-1' });
    const signIn2fa = jest.fn().mockResolvedValue(undefined);
    const replace = jest.fn();
    setAuthStoreState({
      signIn: jest.fn().mockResolvedValue({ requires2fa: false }),
      signIn2fa,
      googleLogin,
    });
    mockUseRouter.mockReturnValue({ replace });
    mockJwtDecode.mockReturnValue({ email: 'google@example.com' });

    render(<SignInPage />);

    await user.click(screen.getByRole('button', { name: 'Google Login' }));
    await screen.findByTestId('twofa-step');
    fireEvent.change(screen.getByTestId('twofa-code'), { target: { value: '123456' } });
    await user.click(screen.getByTestId('twofa-verify'));

    // Fails if the verified Google challenge is submitted with another challenge or code.
    await waitFor(() => {
      expect(signIn2fa).toHaveBeenCalledWith({ challenge: 'challenge-1', code: '123456' });
    });
    expect(replace).toHaveBeenCalledWith('/projects');
  });

  it('routes to the next path after verifying a Google challenge', async () => {
    window.history.pushState({}, '', '/sign-in?next=/projects/id');
    const googleLogin = jest.fn().mockResolvedValue({ requires2fa: true, challenge: 'challenge-1' });
    const signIn2fa = jest.fn().mockResolvedValue(undefined);
    const replace = jest.fn();
    setAuthStoreState({
      signIn: jest.fn().mockResolvedValue({ requires2fa: false }),
      signIn2fa,
      googleLogin,
    });
    mockUseRouter.mockReturnValue({ replace });
    mockJwtDecode.mockReturnValue({ email: 'google@example.com' });

    render(<SignInPage />);

    await user.click(screen.getByRole('button', { name: 'Google Login' }));
    await screen.findByTestId('twofa-step');
    fireEvent.change(screen.getByTestId('twofa-code'), { target: { value: '123456' } });
    await user.click(screen.getByTestId('twofa-verify'));

    // Fails if second-factor completion drops the requested return path.
    await waitFor(() => {
      expect(signIn2fa).toHaveBeenCalledWith({ challenge: 'challenge-1', code: '123456' });
    });
    expect(replace).toHaveBeenCalledWith('/projects/id');
  });

  it('shows an error when Google credential is missing', async () => {
    mockGoogleCredential = null;
    setAuthStoreState({ signIn: jest.fn().mockResolvedValue({ requires2fa: false }), googleLogin: jest.fn() });
    mockUseRouter.mockReturnValue({ replace: jest.fn() });

    render(<SignInPage />);

    await user.click(screen.getByRole('button', { name: 'Google Login' }));

    expect(await screen.findByText('No pudimos iniciar sesión con Google')).toBeInTheDocument();
  });

  it('shows error when Google login fails with response error', async () => {
    const googleLogin = jest
      .fn()
      .mockRejectedValue({ response: { data: { error: 'Google auth error' } } });
    setAuthStoreState({ signIn: jest.fn().mockResolvedValue({ requires2fa: false }), googleLogin });
    mockUseRouter.mockReturnValue({ replace: jest.fn() });
    mockJwtDecode.mockReturnValue({
      email: 'google@example.com',
      given_name: 'Google',
      family_name: 'User',
      picture: 'pic.png',
    });

    render(<SignInPage />);

    await user.click(screen.getByRole('button', { name: 'Google Login' }));

    expect(await screen.findByText('Google auth error')).toBeInTheDocument();
  });

  it('shows default error when Google login throws without response', async () => {
    const googleLogin = jest.fn().mockRejectedValue(new Error('boom'));
    setAuthStoreState({ signIn: jest.fn().mockResolvedValue({ requires2fa: false }), googleLogin });
    mockUseRouter.mockReturnValue({ replace: jest.fn() });
    mockJwtDecode.mockReturnValue({
      email: 'google@example.com',
      given_name: 'Google',
      family_name: 'User',
      picture: 'pic.png',
    });

    render(<SignInPage />);

    await user.click(screen.getByRole('button', { name: 'Google Login' }));

    expect(await screen.findByText('No pudimos iniciar sesión con Google')).toBeInTheDocument();
  });

  it('handles Google login error callback', async () => {
    mockGoogleError = true;
    setAuthStoreState({ signIn: jest.fn().mockResolvedValue({ requires2fa: false }), googleLogin: jest.fn() });
    mockUseRouter.mockReturnValue({ replace: jest.fn() });

    render(<SignInPage />);

    await user.click(screen.getByRole('button', { name: 'Google Login' }));

    expect(await screen.findByText('No pudimos iniciar sesión con Google')).toBeInTheDocument();
  });

  it('continues when jwt decode fails', async () => {
    const googleLogin = jest.fn().mockResolvedValue({ requires2fa: false });
    setAuthStoreState({ signIn: jest.fn().mockResolvedValue({ requires2fa: false }), googleLogin });
    const replace = jest.fn();
    mockUseRouter.mockReturnValue({ replace });
    mockJwtDecode.mockImplementation(() => {
      throw new Error('bad token');
    });

    render(<SignInPage />);

    await user.click(screen.getByRole('button', { name: 'Google Login' }));

    await waitFor(() => {
      expect(googleLogin).toHaveBeenCalledWith({
        credential: 'token',
        email: undefined,
        given_name: undefined,
        family_name: undefined,
        picture: undefined,
      });
    });
    expect(replace).toHaveBeenCalledWith('/projects');
  });
  it('explains explicit Google linking for an existing account without navigating into a session', async () => {
    const googleLogin = jest.fn().mockRejectedValue({ response: { status: 409, data: { code: 'google_link_required' } } });
    const replace = jest.fn();
    const signOut = jest.fn();
    Object.assign(mockUseAuthStore, { getState: () => ({ signOut }) });
    setAuthStoreState({ googleLogin, signIn: jest.fn(), signUp: jest.fn() });
    mockUseRouter.mockReturnValue({ replace });
    render(<SignInPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Google Login' }));
    expect(await screen.findByTestId('google-link-required')).toHaveTextContent('Tu cuenta y documentos se conservan');
    expect(screen.getByRole('link', { name: 'Verificar mi correo' })).toHaveAttribute('href', '/forgot-password');
    expect(replace).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('link', { name: 'Verificar mi correo' }));
    expect(signOut).toHaveBeenCalled();
  });

  it('returns a recovered linked Google account to settings', async () => {
    window.history.pushState({}, '', '/sign-in?next=/settings');
    const replace = jest.fn();
    setAuthStoreState({ signIn: jest.fn(), googleLogin: jest.fn().mockResolvedValue({ requires2fa: false }) });
    mockUseRouter.mockReturnValue({ replace });
    mockJwtDecode.mockReturnValue({ email: 'google@example.com' });
    render(<SignInPage />);
    await user.click(screen.getByRole('button', { name: 'Google Login' }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/settings'));
  });

});
