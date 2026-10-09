import { api } from '../../services/http';
import { useUpgradeDialogStore } from '../upgradeDialogStore';
import { useVersionStore } from '../versionStore';

jest.mock('../../services/http', () => ({
  api: { get: jest.fn(), patch: jest.fn(), post: jest.fn(), delete: jest.fn() },
}));

const mockGet = api.get as jest.Mock;

const historyLockError = {
  response: {
    status: 402,
    data: { error: 'El historial de más de 30 días está bloqueado.', upgrade: true },
  },
};

describe('versionStore viewer URL under the DP-04 history lock', () => {
  beforeEach(() => {
    mockGet.mockReset();
    useVersionStore.setState({ detail: null, fileUrl: null, isLoading: false, error: null });
    useUpgradeDialogStore.setState({ isOpen: false, detail: null });
  });

  it('opens the upgrade dialog when the plan locks the version', async () => {
    mockGet.mockRejectedValueOnce(historyLockError);

    await useVersionStore.getState().fetchFileUrl('locked-version');

    expect(useUpgradeDialogStore.getState()).toMatchObject({
      isOpen: true,
      detail: 'El historial de más de 30 días está bloqueado.',
    });
  });

  it('keeps the upgrade dialog closed for an error that is not a plan lock', async () => {
    mockGet.mockRejectedValueOnce({ response: { status: 404, data: { error: 'No encontrado' } } });

    await useVersionStore.getState().fetchFileUrl('missing-version');

    expect(useUpgradeDialogStore.getState().isOpen).toBe(false);
  });
});
