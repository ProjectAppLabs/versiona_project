import { api } from '../../services/http';
import { useVersionStore } from '../versionStore';

jest.mock('../../services/http', () => ({
  api: { get: jest.fn(), patch: jest.fn(), post: jest.fn(), delete: jest.fn() },
}));

const mockGet = api.get as jest.Mock;
const mockPatch = api.patch as jest.Mock;
const mockDelete = api.delete as jest.Mock;
const mockPost = api.post as jest.Mock;

function pendingResponse() {
  let resolve!: (response: { data: unknown }) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<{ data: unknown }>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe('versionStore', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPatch.mockReset();
    mockDelete.mockReset();
    mockPost.mockReset();
    useVersionStore.setState(useVersionStore.getInitialState(), true);
  });

  it('fetchDetail stores the version detail', async () => {
    mockGet.mockResolvedValueOnce({ data: { public_id: 'v1', number: 1, sections: [] } });

    await useVersionStore.getState().fetchDetail('v1');

    expect(useVersionStore.getState().detail?.number).toBe(1);
  });

  it('fetchDetail surfaces backend errors', async () => {
    mockGet.mockRejectedValueOnce({ response: { data: { error: 'No encontrado' } } });

    await useVersionStore.getState().fetchDetail('v404');

    expect(useVersionStore.getState().error).toBe('No encontrado');
  });

  it('fetchFileUrl returns and stores the presigned url', async () => {
    mockGet.mockResolvedValueOnce({ data: { url: 'http://minio/file?sig=1' } });

    const url = await useVersionStore.getState().fetchFileUrl('v1');

    expect(url).toContain('sig=1');
    expect(useVersionStore.getState().fileUrl).toContain('sig=1');
  });

  it('editMessage patches and updates the loaded detail', async () => {
    useVersionStore.setState({ detail: { public_id: 'v1', message: 'antes' } as never });
    mockPatch.mockResolvedValueOnce({ data: { message: 'después' } });

    const ok = await useVersionStore.getState().editMessage('v1', 'después');

    expect(ok).toBe(true);
    expect(useVersionStore.getState().detail?.message).toBe('después');
  });

  it('editMessage returns false with the frozen-message error (I2b)', async () => {
    mockPatch.mockRejectedValueOnce({
      response: { data: { error: 'El mensaje quedó congelado' } },
    });

    const ok = await useVersionStore.getState().editMessage('v1', 'tarde');

    expect(ok).toBe(false);
    expect(useVersionStore.getState().error).toContain('congelado');
  });

  it('trashVersion and restoreVersion call their endpoints', async () => {
    mockDelete.mockResolvedValueOnce({});
    mockPost.mockResolvedValueOnce({});

    expect(await useVersionStore.getState().trashVersion('v1')).toBe(true);
    expect(await useVersionStore.getState().restoreVersion('v1')).toBe(true);
    expect(mockDelete).toHaveBeenCalledWith('versions/v1/');
    expect(mockPost).toHaveBeenCalledWith('versions/v1/restore/');
  });

  it('downloadUrl returns null and records the error on failure', async () => {
    mockGet.mockRejectedValueOnce(new Error('sin permiso'));

    const url = await useVersionStore.getState().downloadUrl('v1');

    expect(url).toBeNull();
    expect(useVersionStore.getState().error).toContain('sin permiso');
  });

  it('keeps the current metadata after an older version responds', async () => {
    const older = pendingResponse();
    const current = pendingResponse();
    mockGet.mockReturnValueOnce(older.promise).mockReturnValueOnce(current.promise);
    const olderRequest = useVersionStore.getState().fetchDetail('v1');
    const currentRequest = useVersionStore.getState().fetchDetail('v2');
    current.resolve({ data: { public_id: 'v2', number: 2, sections: [] } });
    await currentRequest;

    older.resolve({ data: { public_id: 'v1', number: 1, sections: [] } });
    await olderRequest;

    expect(useVersionStore.getState()).toMatchObject({
      detailVersionId: 'v2', detail: { public_id: 'v2', number: 2 }, isLoading: false,
    });
  });

  it('keeps the current metadata after an older request fails', async () => {
    const older = pendingResponse();
    mockGet.mockReturnValueOnce(older.promise)
      .mockResolvedValueOnce({ data: { public_id: 'v2', number: 2, sections: [] } });
    const olderRequest = useVersionStore.getState().fetchDetail('v1');
    await useVersionStore.getState().fetchDetail('v2');

    older.reject(new Error('old metadata failed'));
    await olderRequest;

    expect(useVersionStore.getState()).toMatchObject({
      detail: { public_id: 'v2' }, detailError: null, isLoading: false,
    });
  });

  it('returns each concurrent comparison URL without replacing the latest PDF', async () => {
    const before = pendingResponse();
    const after = pendingResponse();
    mockGet.mockReturnValueOnce(before.promise).mockReturnValueOnce(after.promise);
    const beforeRequest = useVersionStore.getState().fetchFileUrl('v1');
    const afterRequest = useVersionStore.getState().fetchFileUrl('v2');
    after.resolve({ data: { url: 'https://files.test/v2.pdf' } });
    const afterUrl = await afterRequest;

    before.resolve({ data: { url: 'https://files.test/v1.pdf' } });
    const beforeUrl = await beforeRequest;

    expect(beforeUrl).toBe('https://files.test/v1.pdf');
    expect(afterUrl).toBe('https://files.test/v2.pdf');
    expect(useVersionStore.getState()).toMatchObject({
      fileVersionId: 'v2', fileUrl: afterUrl, isFileLoading: false,
    });
  });

  it('keeps the PDF error when its metadata completes later', async () => {
    const metadata = pendingResponse();
    mockGet.mockReturnValueOnce(metadata.promise)
      .mockRejectedValueOnce(new Error('PDF unavailable'));
    const metadataRequest = useVersionStore.getState().fetchDetail('v2');
    await useVersionStore.getState().fetchFileUrl('v2');

    metadata.resolve({ data: { public_id: 'v2', number: 2, sections: [] } });
    await metadataRequest;

    expect(useVersionStore.getState()).toMatchObject({
      detail: { public_id: 'v2' }, detailError: null,
      fileUrl: null, fileError: 'PDF unavailable', isFileLoading: false,
    });
  });

  it('discards a pending PDF after its metadata fails', async () => {
    const metadata = pendingResponse();
    const file = pendingResponse();
    mockGet.mockReturnValueOnce(metadata.promise).mockReturnValueOnce(file.promise);
    const metadataRequest = useVersionStore.getState().fetchDetail('v2');
    const fileRequest = useVersionStore.getState().fetchFileUrl('v2');
    metadata.reject(new Error('Version unavailable'));
    await metadataRequest;

    file.resolve({ data: { url: 'https://files.test/v2.pdf' } });
    const url = await fileRequest;

    expect(url).toBe('https://files.test/v2.pdf');
    expect(useVersionStore.getState()).toMatchObject({
      detail: null, detailError: 'Version unavailable', fileUrl: null, isFileLoading: false,
    });
  });

  it('preserves the loaded PDF during a same-version metadata refresh', async () => {
    mockGet
      .mockResolvedValueOnce({ data: { public_id: 'v2', number: 2, sections: [] } })
      .mockResolvedValueOnce({ data: { url: 'https://files.test/v2.pdf' } });
    await useVersionStore.getState().fetchDetail('v2');
    await useVersionStore.getState().fetchFileUrl('v2');
    const refresh = pendingResponse();
    mockGet.mockReturnValueOnce(refresh.promise);

    const refreshRequest = useVersionStore.getState().fetchDetail('v2');

    expect(useVersionStore.getState()).toMatchObject({
      detail: { public_id: 'v2' }, fileUrl: 'https://files.test/v2.pdf', isLoading: true,
    });
    refresh.resolve({ data: { public_id: 'v2', number: 2, is_approved: true, sections: [] } });
    await refreshRequest;
    expect(useVersionStore.getState().detail?.is_approved).toBe(true);
  });
});
