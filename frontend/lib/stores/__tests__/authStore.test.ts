import { describe, it, expect, beforeEach, afterEach } from '@jest/globals';
import { act } from '@testing-library/react';

import { useAuthStore } from '../authStore';
import { api, publicApi } from '../../services/http';
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from '../../services/tokens';

jest.mock('../../services/http', () => ({
  publicApi: { post: jest.fn() },
  api: {
    post: jest.fn(),
    get: jest.fn(),
  },
}));

jest.mock('../../services/tokens', () => ({
  getAccessToken: jest.fn(),
  getRefreshToken: jest.fn(),
  setTokens: jest.fn(),
  clearTokens: jest.fn(),
}));

const mockPublicApi = publicApi as jest.Mocked<typeof publicApi>;
const mockApi = api as jest.Mocked<typeof api>;
const mockGetAccessToken = getAccessToken as jest.Mock;
const mockGetRefreshToken = getRefreshToken as jest.Mock;
const mockSetTokens = setTokens as jest.Mock;
const mockClearTokens = clearTokens as jest.Mock;

const resetAuthState = () => {
  useAuthStore.setState({
    accessToken: null,
    refreshToken: null,
    user: null,
    isAuthenticated: false,
  });
};

describe('authStore', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    resetAuthState();
    sessionStorage.clear();
    mockGetAccessToken.mockReturnValue(null);
    mockGetRefreshToken.mockReturnValue(null);
  });

  afterEach(() => {
    localStorage.removeItem('user_data');
  });

  it('syncs tokens from cookies', () => {
    mockGetAccessToken.mockReturnValue('access');
    mockGetRefreshToken.mockReturnValue('refresh');

    act(() => {
      useAuthStore.getState().syncFromCookies();
    });

    const state = useAuthStore.getState();
    expect(state.accessToken).toBe('access');
    expect(state.refreshToken).toBe('refresh');
    expect(state.isAuthenticated).toBe(true);
  });

  it('signs in successfully', async () => {
    mockGetAccessToken.mockReturnValue('access');
    mockGetRefreshToken.mockReturnValue('refresh');
    mockApi.post.mockResolvedValueOnce({
      status: 200,
      data: {
        access: 'access',
        refresh: 'refresh',
        user: {
          id: 1,
          email: 'user@example.com',
          first_name: 'Test',
          last_name: 'User',
          role: 'customer',
          is_staff: false,
        },
      },
    });

    let result: unknown;
    await act(async () => {
      result = await useAuthStore.getState().signIn({ email: 'user@example.com', password: 'password' });
    });

    expect(mockSetTokens).toHaveBeenCalledWith({ access: 'access', refresh: 'refresh' });
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
    expect(useAuthStore.getState().user?.email).toBe('user@example.com');
    expect(result).toEqual({ requires2fa: false });
  });

  it('throws when sign in response is missing tokens', async () => {
    mockApi.post.mockResolvedValueOnce({ data: { access: null, refresh: null } });

    await expect(useAuthStore.getState().signIn({ email: 'user@example.com', password: 'password' })).rejects.toThrow(
      'Invalid token response'
    );
  });

  it('signs up successfully', async () => {
    mockGetAccessToken.mockReturnValue('access');
    mockGetRefreshToken.mockReturnValue('refresh');
    mockApi.post.mockResolvedValueOnce({
      status: 200,
      data: {
        access: 'access',
        refresh: 'refresh',
        user: {
          id: 2,
          email: 'new@example.com',
          first_name: 'New',
          last_name: 'User',
          role: 'customer',
          is_staff: false,
        },
      },
    });

    await act(async () => {
      await useAuthStore.getState().signUp({ email: 'new@example.com', password: 'password' });
    });

    expect(mockSetTokens).toHaveBeenCalledWith({ access: 'access', refresh: 'refresh' });
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
  });

  it('throws when sign up response is missing tokens', async () => {
    mockApi.post.mockResolvedValueOnce({ data: { access: null, refresh: null } });

    await expect(
      useAuthStore.getState().signUp({ email: 'new@example.com', password: 'password' })
    ).rejects.toThrow('Invalid token response');
  });

  it('logs in with google credentials', async () => {
    mockGetAccessToken.mockReturnValue('access');
    mockGetRefreshToken.mockReturnValue('refresh');
    mockPublicApi.post.mockResolvedValueOnce({
      data: {
        access: 'access',
        refresh: 'refresh',
        user: {
          id: 3,
          email: 'google@example.com',
          first_name: 'Google',
          last_name: 'User',
          role: 'customer',
          is_staff: false,
        },
      },
    });

    let result: unknown;
    await act(async () => {
      result = await useAuthStore.getState().googleLogin({ credential: 'token', email: 'google@example.com' });
    });

    expect(mockSetTokens).toHaveBeenCalledWith({ access: 'access', refresh: 'refresh' });
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
    expect(result).toEqual({ requires2fa: false });
  });

  it('returns a second-factor challenge from sign in without authenticating', async () => {
    mockApi.post.mockResolvedValueOnce({
      status: 202,
      data: {
        requires_2fa: true,
        challenge: 'challenge-1',
        access: 'unexpected-access',
        refresh: 'unexpected-refresh',
        user: { id: 8, email: 'unexpected@example.com' },
      },
    });

    // Fails if a pending TOTP challenge is persisted as an authenticated session.
    const result = await useAuthStore.getState().signIn({ email: 'user@example.com', password: 'password' });

    expect(result).toEqual({ requires2fa: true, challenge: 'challenge-1' });
    expect(mockSetTokens).not.toHaveBeenCalled();
    expect(localStorage.getItem('user_data')).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it('returns a second-factor challenge from Google login without authenticating', async () => {
    mockPublicApi.post.mockResolvedValueOnce({
      status: 202,
      data: {
        requires_2fa: true,
        challenge: 'challenge-1',
        access: 'unexpected-access',
        refresh: 'unexpected-refresh',
        user: { id: 8, email: 'unexpected@example.com' },
      },
    });

    // Fails if a pending Google TOTP challenge writes authentication state before verification.
    const result = await useAuthStore.getState().googleLogin({ credential: 'token' });

    expect(result).toEqual({ requires2fa: true, challenge: 'challenge-1' });
    expect(mockSetTokens).not.toHaveBeenCalled();
    expect(localStorage.getItem('user_data')).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it.each([
    ['a missing second-factor marker', { challenge: 'challenge-1', access: 'access', refresh: 'refresh', user: { id: 8 } }],
    ['a false second-factor marker', { requires_2fa: false, challenge: 'challenge-1', access: 'access', refresh: 'refresh', user: { id: 8 } }],
    ['a non-string challenge', { requires_2fa: true, challenge: 123456, access: 'access', refresh: 'refresh', user: { id: 8 } }],
    ['a blank challenge', { requires_2fa: true, challenge: '   ', access: 'access', refresh: 'refresh', user: { id: 8 } }],
  ])('rejects sign in 202 response with %s', async (_label, data) => {
    mockApi.post.mockResolvedValueOnce({ status: 202, data });

    // Fails if token-shaped data lets a malformed sign-in challenge create a session.
    await expect(useAuthStore.getState().signIn({ email: 'user@example.com', password: 'password' })).rejects.toThrow(
      'Invalid challenge response'
    );

    expect(mockSetTokens).not.toHaveBeenCalled();
    expect(localStorage.getItem('user_data')).toBeNull();
    expect(useAuthStore.getState()).toMatchObject({ accessToken: null, refreshToken: null, user: null, isAuthenticated: false });
  });

  it.each([
    ['a missing second-factor marker', { challenge: 'challenge-1', access: 'access', refresh: 'refresh', user: { id: 8 } }],
    ['a false second-factor marker', { requires_2fa: false, challenge: 'challenge-1', access: 'access', refresh: 'refresh', user: { id: 8 } }],
    ['a non-string challenge', { requires_2fa: true, challenge: 123456, access: 'access', refresh: 'refresh', user: { id: 8 } }],
    ['a blank challenge', { requires_2fa: true, challenge: '   ', access: 'access', refresh: 'refresh', user: { id: 8 } }],
  ])('rejects Google login 202 response with %s', async (_label, data) => {
    mockPublicApi.post.mockResolvedValueOnce({ status: 202, data });

    // Fails if token-shaped data lets a malformed Google challenge create a session.
    await expect(useAuthStore.getState().googleLogin({ credential: 'token' })).rejects.toThrow('Invalid challenge response');

    expect(mockSetTokens).not.toHaveBeenCalled();
    expect(localStorage.getItem('user_data')).toBeNull();
    expect(useAuthStore.getState()).toMatchObject({ accessToken: null, refreshToken: null, user: null, isAuthenticated: false });
  });

  it('throws when google login response is missing tokens', async () => {
    mockPublicApi.post.mockResolvedValueOnce({ data: { access: null, refresh: null } });

    await expect(useAuthStore.getState().googleLogin({ credential: 'token' })).rejects.toThrow('Invalid token response');
  });

  it('signs out and clears tokens', () => {
    sessionStorage.setItem('google_link_ticket', 'old-proof');
    useAuthStore.setState({ isAuthenticated: true, accessToken: 'access', refreshToken: 'refresh' });

    act(() => {
      useAuthStore.getState().signOut();
    });

    expect(mockClearTokens).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(sessionStorage.getItem('google_link_ticket')).toBeNull();
  });

  it('sends a password reset code', async () => {
    mockPublicApi.post.mockResolvedValueOnce({ data: {} });

    await act(async () => {
      await useAuthStore.getState().sendPasswordResetCode('user@example.com');
    });

    expect(mockPublicApi.post).toHaveBeenCalledWith('send_passcode/', { email: 'user@example.com' });
  });

  it('resets password', async () => {
    mockPublicApi.post.mockResolvedValueOnce({ data: {} });

    await act(async () => {
      await useAuthStore
        .getState()
        .resetPassword({ email: 'user@example.com', code: '123456', new_password: 'password123' });
    });

    expect(mockPublicApi.post).toHaveBeenCalledWith('verify_passcode_and_reset_password/', {
      email: 'user@example.com',
      code: '123456',
      new_password: 'password123',
    });
  });

  it('restores the current user from validate_token', async () => {
    mockGetAccessToken.mockReturnValue('access');
    mockApi.get.mockResolvedValueOnce({
      data: {
        user: {
          id: 7,
          email: 'restore@example.com',
          first_name: 'Restore',
          last_name: 'User',
          role: 'customer',
          is_staff: false,
        },
      },
    });

    await act(async () => {
      await useAuthStore.getState().restoreUser();
    });

    expect(mockApi.get).toHaveBeenCalledWith('validate_token/');
    expect(useAuthStore.getState().user?.email).toBe('restore@example.com');
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
  });

  it('clears auth state when restoreUser fails', async () => {
    mockGetAccessToken.mockReturnValue('access');
    mockApi.get.mockRejectedValueOnce(new Error('boom'));
    useAuthStore.setState({
      accessToken: 'access',
      refreshToken: 'refresh',
      user: { id: 1, email: 'user@example.com', first_name: 'T', last_name: 'U', role: 'customer', is_staff: false },
      isAuthenticated: true,
    });

    await act(async () => {
      await useAuthStore.getState().restoreUser();
    });

    expect(mockClearTokens).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it('keeps authentication unchanged when Google requires explicit linking', async () => {
    const rejection = { response: { status: 409, data: { code: 'google_link_required' } } };
    mockPublicApi.post.mockRejectedValueOnce(rejection);
    await expect(useAuthStore.getState().googleLogin({ credential: 'signed-proof', email: 'untrusted@example.com' })).rejects.toBe(rejection);
    expect(mockPublicApi.post).toHaveBeenCalledWith('google_login/', { credential: 'signed-proof' });
    expect(mockSetTokens).not.toHaveBeenCalled();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it('clears authentication after email recovery without using its Google ticket as a session', async () => {
    useAuthStore.setState({ isAuthenticated: true, accessToken: 'old-access', refreshToken: 'old-refresh' });
    localStorage.setItem('user_data', '{"id":3}');
    mockPublicApi.post.mockResolvedValueOnce({ data: { google_link_ticket: 'email-proof' } });
    await useAuthStore.getState().resetPassword({ email: 'user@example.com', code: '123456', new_password: 'new-password' });
    expect(mockClearTokens).toHaveBeenCalled();
    expect(localStorage.getItem('user_data')).toBeNull();
    expect(useAuthStore.getState()).toMatchObject({ accessToken: null, refreshToken: null, user: null, isAuthenticated: false });
    expect(sessionStorage.getItem('google_link_ticket')).toContain('email-proof');
    expect(mockSetTokens).not.toHaveBeenCalled();
  });

});
