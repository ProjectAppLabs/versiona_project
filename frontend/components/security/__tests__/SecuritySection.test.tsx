import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { SecuritySection } from '../SecuritySection';
import { api } from '../../../lib/services/http';

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('../../../lib/stores/authStore', () => ({ useAuthStore: { getState: () => ({ signOut: jest.fn() }) } }));

jest.mock('../../../lib/services/http', () => ({
  api: { get: jest.fn(), post: jest.fn() },
}));
jest.mock('../../../lib/services/tokens', () => ({
  getRefreshToken: () => 'refresh-token',
}));
const toast = jest.fn();
jest.mock('../../../components/ui/toast', () => ({
  useToast: () => ({ toast }),
}));

const mockGet = api.get as jest.Mock;
const mockPost = api.post as jest.Mock;

function primeState({ enabled = false, sessions = [] as unknown[] } = {}) {
  mockGet.mockImplementation((url: string) => {
    if (url === 'me/security/') {
      return Promise.resolve({
        data: {
          totp_enabled: enabled,
          backup_codes_left: enabled ? 8 : 0,
          sso: 'DECISIÓN PENDIENTE',
          google_linked: false,
          has_usable_password: true,
        },
      });
    }
    return Promise.resolve({ data: { results: sessions } });
  });
}

describe('SecuritySection (A3)', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
    toast.mockReset();
  });

  it('[A3-F01-ui] enrolment shows QR, secret and asks for the first code', async () => {
    primeState();
    mockPost.mockResolvedValueOnce({
      data: { qr: 'data:image/png;base64,QQ==', secret: 'JBSWY3DPEHPK3PXP' },
    });

    render(<SecuritySection />);
    await userEvent.click(await screen.findByTestId('start-2fa'));

    expect(await screen.findByTestId('twofa-qr')).toBeInTheDocument();
    expect(screen.getByTestId('twofa-secret')).toHaveTextContent('JBSWY3DPEHPK3PXP');
    expect(screen.getByTestId('enable-2fa')).toBeDisabled();
  });

  it('[A3-F02-ui] enabling shows the backup codes exactly once', async () => {
    primeState();
    mockPost
      .mockResolvedValueOnce({ data: { qr: 'data:image/png;base64,QQ==', secret: 'S' } })
      .mockResolvedValueOnce({ data: { backup_codes: ['aaaa-bbbb', 'cccc-dddd'] } });

    render(<SecuritySection />);
    await userEvent.click(await screen.findByTestId('start-2fa'));
    await userEvent.type(screen.getByTestId('enable-code'), '123456');
    await userEvent.click(screen.getByTestId('enable-2fa'));

    expect(await screen.findByTestId('backup-codes')).toBeInTheDocument();
    expect(screen.getByText('aaaa-bbbb')).toBeInTheDocument();

    await userEvent.click(screen.getByTestId('backup-saved'));
    expect(screen.queryByTestId('backup-codes')).not.toBeInTheDocument();
  });

  it('[A3-F04-ui] lists sessions and revokes the others with the refresh token', async () => {
    primeState({
      enabled: true,
      sessions: [
        { id: 1, jti: 'aaaa1111', created_at: '2026-07-12T10:00:00Z',
          expires_at: '2026-07-19T10:00:00Z' },
        { id: 2, jti: 'bbbb2222', created_at: '2026-07-12T11:00:00Z',
          expires_at: '2026-07-19T11:00:00Z' },
      ],
    });
    mockPost.mockResolvedValue({ data: { revoked: 1 } });

    render(<SecuritySection />);
    await userEvent.click(await screen.findByTestId('revoke-others'));

    expect(mockPost).toHaveBeenCalledWith('me/sessions/revoke_others/', {
      refresh: 'refresh-token',
    });
  });

  it('[A3-A02-ui] disable requires a code', async () => {
    primeState({ enabled: true });
    mockPost.mockResolvedValue({ data: { totp_enabled: false } });

    render(<SecuritySection />);
    await userEvent.type(await screen.findByTestId('disable-code'), '654321');
    await userEvent.click(screen.getByTestId('disable-2fa'));

    expect(mockPost).toHaveBeenCalledWith('me/2fa/disable/', { code: '654321' });
  });
});
