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

function pendingResponse() {
  let resolve!: (response: { data: unknown }) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<{ data: unknown }>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe('versionStore viewer URL under the DP-04 history lock', () => {
  beforeEach(() => {
    mockGet.mockReset();
    useVersionStore.setState(useVersionStore.getInitialState(), true);
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

  it('removes the previous PDF when the next version is history-locked', async () => {
    mockGet
      .mockResolvedValueOnce({ data: { url: 'https://files.test/v2.pdf' } })
      .mockResolvedValueOnce({ data: { public_id: 'v1', number: 1, sections: [] } })
      .mockRejectedValueOnce(historyLockError);
    await useVersionStore.getState().fetchFileUrl('v2');
    expect(useVersionStore.getState().fileUrl).toBe('https://files.test/v2.pdf');

    await useVersionStore.getState().fetchDetail('v1');
    await useVersionStore.getState().fetchFileUrl('v1');

    expect(useVersionStore.getState().fileUrl).toBeNull();
    expect(useVersionStore.getState().detail?.public_id).toBe('v1');
    expect(useUpgradeDialogStore.getState().isOpen).toBe(true);
  });

  it('ignores a replaced history-lock attempt while its replacement is pending', async () => {
    const old = pendingResponse();
    const replacement = pendingResponse();
    mockGet.mockReturnValueOnce(old.promise).mockReturnValueOnce(replacement.promise)
      .mockResolvedValueOnce({ data: { url: 'https://files.test/v2.pdf' } });
    const oldRequest = useVersionStore.getState().fetchFileUrl('v1');
    const replacementRequest = useVersionStore.getState().fetchFileUrl('v1');
    await useVersionStore.getState().fetchFileUrl('v2');

    old.reject(historyLockError);
    await oldRequest;

    expect(useUpgradeDialogStore.getState().isOpen).toBe(false);
    expect(useVersionStore.getState().fileUrl).toBe('https://files.test/v2.pdf');
    replacement.resolve({ data: { url: 'https://files.test/v1.pdf' } });
    expect(await replacementRequest).toBe('https://files.test/v1.pdf');
  });

  it('ignores a replaced history-lock attempt after its replacement finishes', async () => {
    const old = pendingResponse();
    const replacement = pendingResponse();
    mockGet.mockReturnValueOnce(old.promise).mockReturnValueOnce(replacement.promise)
      .mockResolvedValueOnce({ data: { url: 'https://files.test/v2.pdf' } });
    const oldRequest = useVersionStore.getState().fetchFileUrl('v1');
    const replacementRequest = useVersionStore.getState().fetchFileUrl('v1');
    await useVersionStore.getState().fetchFileUrl('v2');
    replacement.resolve({ data: { url: 'https://files.test/v1.pdf' } });
    await replacementRequest;

    old.reject(historyLockError);
    await oldRequest;

    expect(useUpgradeDialogStore.getState().isOpen).toBe(false);
    expect(useVersionStore.getState()).toMatchObject({
      fileVersionId: 'v2', fileUrl: 'https://files.test/v2.pdf', fileError: null,
    });
  });

  it('reports a history lock from the other side of a concurrent comparison', async () => {
    const before = pendingResponse();
    mockGet.mockReturnValueOnce(before.promise)
      .mockResolvedValueOnce({ data: { url: 'https://files.test/v2.pdf' } });
    const beforeRequest = useVersionStore.getState().fetchFileUrl('v1');
    await useVersionStore.getState().fetchFileUrl('v2');

    before.reject(historyLockError);
    expect(await beforeRequest).toBeNull();

    expect(useUpgradeDialogStore.getState()).toMatchObject({
      isOpen: true, detail: historyLockError.response.data.error,
    });
    expect(useVersionStore.getState()).toMatchObject({
      fileVersionId: 'v2', fileUrl: 'https://files.test/v2.pdf', fileError: null,
    });
  });

  it('ignores a history-lock response from a previous navigation', async () => {
    const previousFile = pendingResponse();
    mockGet.mockReturnValueOnce(previousFile.promise)
      .mockResolvedValueOnce({ data: { public_id: 'v2', number: 2, sections: [] } })
      .mockResolvedValueOnce({ data: { url: 'https://files.test/v2.pdf' } });
    const previousRequest = useVersionStore.getState().fetchFileUrl('v1');
    await useVersionStore.getState().fetchDetail('v2');
    await useVersionStore.getState().fetchFileUrl('v2');

    previousFile.reject(historyLockError);
    await previousRequest;

    expect(useUpgradeDialogStore.getState().isOpen).toBe(false);
    expect(useVersionStore.getState()).toMatchObject({
      detail: { public_id: 'v2' }, fileVersionId: 'v2', fileUrl: 'https://files.test/v2.pdf',
    });
  });
});
