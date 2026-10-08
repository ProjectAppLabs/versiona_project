import { publicApi } from '../../services/http';
import {
  type PublicComparisonDetail,
  usePublicCompareStore,
} from '../publicCompareStore';

jest.mock('../../services/http', () => ({
  publicApi: { get: jest.fn(), post: jest.fn() },
}));

const mockPost = publicApi.post as jest.Mock;
const mockGet = publicApi.get as jest.Mock;

const pdf = (name: string) =>
  new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], name, {
    type: 'application/pdf',
  });

function comparison(
  publicId: string,
  status: PublicComparisonDetail['status'] = 'done'
): PublicComparisonDetail {
  return {
    public_id: publicId,
    status,
    error_code: status === 'failed' ? 'processing_failed' : '',
    file_a_name: `${publicId}-v1.pdf`,
    file_b_name: `${publicId}-v2.pdf`,
    created_at: '2026-10-08T00:00:00Z',
    expires_at: '2026-10-09T00:00:00Z',
    result: {
      counts: { modified: 0, added: 0, removed: 0, unchanged: 0, renamed_only: 0 },
      summary_text: publicId,
      sections: [],
      meta: { page_count_a: 1, page_count_b: 1 },
    },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe('publicCompareStore', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    mockPost.mockReset();
    mockGet.mockReset();
    usePublicCompareStore.getState().reset();
  });

  afterEach(() => {
    usePublicCompareStore.getState().reset();
    jest.useRealTimers();
  });

  it('returns the public id after uploading two files', async () => {
    mockPost.mockResolvedValueOnce({ data: { public_id: 'abc', status: 'done' } });
    const store = usePublicCompareStore.getState();
    store.setSlot('a', pdf('v1.pdf'));
    store.setSlot('b', pdf('v2.pdf'));

    const id = await usePublicCompareStore.getState().submit();

    expect(id).toBe('abc');
    expect(usePublicCompareStore.getState().phase).toBe('processing');
  });

  it('rejects a non-pdf file client-side before uploading', async () => {
    const store = usePublicCompareStore.getState();
    store.setSlot('a', new File(['x'], 'foto.png', { type: 'image/png' }));
    store.setSlot('b', pdf('v2.pdf'));

    const id = await usePublicCompareStore.getState().submit();

    expect(id).toBeNull();
    expect(usePublicCompareStore.getState().errorKey).toBe('notPdf');
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('maps the 422 ocr_required response to the upsell error key', async () => {
    mockPost.mockRejectedValueOnce({
      response: { status: 422, data: { error_code: 'ocr_required' } },
    });
    const store = usePublicCompareStore.getState();
    store.setSlot('a', pdf('scan.pdf'));
    store.setSlot('b', pdf('v2.pdf'));

    await usePublicCompareStore.getState().submit();

    expect(usePublicCompareStore.getState().errorKey).toBe('scannedNeedsOcr');
  });

  it('maps a 429 response to the rate-limited error key', async () => {
    mockPost.mockRejectedValueOnce({ response: { status: 429, data: {} } });
    const store = usePublicCompareStore.getState();
    store.setSlot('a', pdf('v1.pdf'));
    store.setSlot('b', pdf('v2.pdf'));

    await usePublicCompareStore.getState().submit();

    expect(usePublicCompareStore.getState().errorKey).toBe('rateLimited');
  });

  it('loads a done comparison into the done phase', async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        public_id: 'abc',
        status: 'done',
        error_code: '',
        file_a_name: 'v1.pdf',
        file_b_name: 'v2.pdf',
        created_at: 'x',
        expires_at: 'y',
        result: { counts: {}, summary_text: '', sections: [], meta: {} },
      },
    });

    await usePublicCompareStore.getState().load('abc');

    expect(usePublicCompareStore.getState().phase).toBe('done');
  });

  it('marks the expired result from a 410 response', async () => {
    mockGet.mockRejectedValueOnce({
      response: { status: 410, data: { error_code: 'expired' } },
    });

    await usePublicCompareStore.getState().load('abc');

    expect(usePublicCompareStore.getState().errorKey).toBe('expired');
  });

  it.each<PublicComparisonDetail['status']>(['done', 'failed', 'processing'])(
    'preserves the newer result after an older %s response',
    async (status) => {
      const oldResponse = deferred<{ data: PublicComparisonDetail }>();
      mockGet.mockReturnValueOnce(oldResponse.promise);
      mockGet.mockResolvedValueOnce({ data: comparison('new') });
      const oldLoad = usePublicCompareStore.getState().load('old');
      const oldSignal = mockGet.mock.calls[0][1].signal as AbortSignal;

      await usePublicCompareStore.getState().load('new');
      oldResponse.resolve({ data: comparison('old', status) });
      await oldLoad;
      await jest.advanceTimersByTimeAsync(60_000);

      expect(usePublicCompareStore.getState().detail?.public_id).toBe('new');
      expect(usePublicCompareStore.getState().phase).toBe('done');
      expect(usePublicCompareStore.getState().errorKey).toBeNull();
      expect(oldSignal.aborted).toBe(true);
      expect(mockGet).toHaveBeenCalledTimes(2);
    }
  );

  it('preserves the newer result after an older transport failure', async () => {
    const oldResponse = deferred<{ data: PublicComparisonDetail }>();
    mockGet.mockReturnValueOnce(oldResponse.promise);
    mockGet.mockResolvedValueOnce({ data: comparison('new') });
    const oldLoad = usePublicCompareStore.getState().load('old');

    await usePublicCompareStore.getState().load('new');
    oldResponse.reject({ response: { status: 410, data: { error_code: 'expired' } } });
    await oldLoad;

    expect(usePublicCompareStore.getState().detail?.public_id).toBe('new');
    expect(usePublicCompareStore.getState().phase).toBe('done');
    expect(usePublicCompareStore.getState().errorKey).toBeNull();
  });

  it('keeps the reset state after an outstanding response', async () => {
    const response = deferred<{ data: PublicComparisonDetail }>();
    mockGet.mockReturnValueOnce(response.promise);
    const loading = usePublicCompareStore.getState().load('old');
    const signal = mockGet.mock.calls[0][1].signal as AbortSignal;

    usePublicCompareStore.getState().reset();
    response.resolve({ data: comparison('old', 'processing') });
    await loading;
    await jest.advanceTimersByTimeAsync(60_000);

    expect(usePublicCompareStore.getState().phase).toBe('idle');
    expect(usePublicCompareStore.getState().detail).toBeNull();
    expect(usePublicCompareStore.getState().errorKey).toBeNull();
    expect(signal.aborted).toBe(true);
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it('discards a response after its caller aborts', async () => {
    const response = deferred<{ data: PublicComparisonDetail }>();
    const controller = new AbortController();
    mockGet.mockReturnValueOnce(response.promise);
    const loading = usePublicCompareStore.getState().load('old', controller.signal);
    const transportSignal = mockGet.mock.calls[0][1].signal as AbortSignal;

    controller.abort();
    response.resolve({ data: comparison('old') });
    await loading;

    expect(transportSignal.aborted).toBe(true);
    expect(usePublicCompareStore.getState().detail).toBeNull();
    expect(usePublicCompareStore.getState().phase).toBe('processing');
    expect(usePublicCompareStore.getState().errorKey).toBeNull();
  });

  it('cancels the polling delay when reset', async () => {
    mockGet.mockResolvedValue({ data: comparison('old', 'processing') });
    const loading = usePublicCompareStore.getState().load('old');
    await jest.advanceTimersByTimeAsync(0);
    expect(usePublicCompareStore.getState().detail?.public_id).toBe('old');

    usePublicCompareStore.getState().reset();
    await loading;
    await jest.advanceTimersByTimeAsync(60_000);

    expect(usePublicCompareStore.getState().phase).toBe('idle');
    expect(usePublicCompareStore.getState().detail).toBeNull();
    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(jest.getTimerCount()).toBe(0);
  });

  it('cancels the polling delay when its caller aborts', async () => {
    const controller = new AbortController();
    mockGet.mockResolvedValue({ data: comparison('old', 'pending') });
    const loading = usePublicCompareStore.getState().load('old', controller.signal);
    await jest.advanceTimersByTimeAsync(0);

    controller.abort();
    await loading;
    await jest.advanceTimersByTimeAsync(60_000);

    expect(usePublicCompareStore.getState().detail?.status).toBe('pending');
    expect(usePublicCompareStore.getState().phase).toBe('processing');
    expect(usePublicCompareStore.getState().errorKey).toBeNull();
    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(jest.getTimerCount()).toBe(0);
  });

  it('backs off polling to the ten-second cap', async () => {
    const controller = new AbortController();
    mockGet.mockResolvedValue({ data: comparison('current', 'processing') });
    const loading = usePublicCompareStore.getState().load('current', controller.signal);

    await jest.advanceTimersByTimeAsync(2000);
    expect(mockGet).toHaveBeenCalledTimes(2);
    await jest.advanceTimersByTimeAsync(2999);
    expect(mockGet).toHaveBeenCalledTimes(2);
    await jest.advanceTimersByTimeAsync(1);
    expect(mockGet).toHaveBeenCalledTimes(3);
    await jest.advanceTimersByTimeAsync(4500 + 6750 + 10_000);
    expect(mockGet).toHaveBeenCalledTimes(6);
    await jest.advanceTimersByTimeAsync(9999);
    expect(mockGet).toHaveBeenCalledTimes(6);
    await jest.advanceTimersByTimeAsync(1);
    expect(mockGet).toHaveBeenCalledTimes(7);
    controller.abort();
    await loading;
  });

  it('stops processing after the five-minute timeout', async () => {
    mockGet.mockResolvedValue({ data: comparison('current', 'processing') });
    const loading = usePublicCompareStore.getState().load('current');

    await jest.advanceTimersByTimeAsync(310_000);
    await loading;

    expect(usePublicCompareStore.getState().phase).toBe('error');
    expect(usePublicCompareStore.getState().errorKey).toBe('genericFailed');
    expect(usePublicCompareStore.getState().detail?.public_id).toBe('current');
    expect(jest.getTimerCount()).toBe(0);
  });

  it('maps a failed comparison to its domain error', async () => {
    mockGet.mockResolvedValueOnce({
      data: { ...comparison('current', 'failed'), error_code: 'ocr_required' },
    });

    await usePublicCompareStore.getState().load('current');

    expect(usePublicCompareStore.getState().detail?.status).toBe('failed');
    expect(usePublicCompareStore.getState().phase).toBe('error');
    expect(usePublicCompareStore.getState().errorKey).toBe('scannedNeedsOcr');
  });

  it('does not request a result with an already aborted signal', async () => {
    const controller = new AbortController();
    controller.abort();

    await usePublicCompareStore.getState().load('old', controller.signal);

    expect(mockGet).not.toHaveBeenCalled();
    expect(usePublicCompareStore.getState().phase).toBe('idle');
    expect(usePublicCompareStore.getState().detail).toBeNull();
  });
});
