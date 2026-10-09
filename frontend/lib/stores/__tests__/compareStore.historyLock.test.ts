import { api } from '../../services/http';
import { useCompareStore } from '../compareStore';
import { useUpgradeDialogStore } from '../upgradeDialogStore';

jest.mock('../../services/http', () => ({
  api: { get: jest.fn(), post: jest.fn() },
}));

const mockPost = api.post as jest.Mock;

const historyLockError = {
  response: {
    status: 402,
    data: { error: 'El historial de más de 30 días está bloqueado.', upgrade: true },
  },
};

describe('compareStore comparison under the DP-04 history lock', () => {
  beforeEach(() => {
    mockPost.mockReset();
    useCompareStore.setState({
      comparison: null,
      diffs: {},
      activeSection: null,
      isLoading: false,
      error: null,
    });
    useUpgradeDialogStore.setState({ isOpen: false, detail: null });
  });

  it('opens the upgrade dialog when the plan locks a compared version', async () => {
    mockPost.mockRejectedValueOnce(historyLockError);

    await useCompareStore.getState().compare('doc-1', 'locked-version', 'latest-version');

    expect(useUpgradeDialogStore.getState()).toMatchObject({
      isOpen: true,
      detail: 'El historial de más de 30 días está bloqueado.',
    });
  });

  it('keeps the upgrade dialog closed for an error that is not a plan lock', async () => {
    mockPost.mockRejectedValueOnce({
      response: { status: 409, data: { error: 'La versión aún no está analizada.' } },
    });

    await useCompareStore.getState().compare('doc-1', 'pending-version', 'latest-version');

    expect(useUpgradeDialogStore.getState().isOpen).toBe(false);
  });
});
