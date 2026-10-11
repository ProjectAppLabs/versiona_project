import { api } from '../../services/http';
import { useSealStore, type ValidityRecord } from '../sealStore';

jest.mock('../../services/http', () => ({
  api: { get: jest.fn(), post: jest.fn() },
}));

const mockGet = api.get as jest.Mock;
const mockPost = api.post as jest.Mock;

function pendingResponse() {
  let resolve!: (value: { data: unknown }) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<{ data: unknown }>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

const seal = {
  public_id: 's1',
  reviewer_email: 'revisor@versiona.test',
  version_number: 1,
  covers_all: false,
  covered_keys: ['objeto-del-contrato'],
  key_id: 'k1',
  is_active: true,
  revoked_at: null,
  created_at: '2026-07-12T10:00:00Z',
};

const currentSeal = { ...seal, public_id: 's2', reviewer_email: 'actual@versiona.test' };
const pendingRecord: ValidityRecord = {
  seal: currentSeal,
  to_version: 2,
  decision: 'pending_confirmation',
  proposed_decision: 'invalidated',
  reason_code: 'section_modified',
  evidence: { changed: [{ stable_key: 'objeto-del-contrato', change_type: 'modified' }] },
  decided_mode: 'coordinator',
  decided_by_email: null,
  decided_at: null,
};

async function loadCurrentVersion() {
  mockGet.mockResolvedValueOnce({ data: { seals: [currentSeal], validity_records: [] } });
  await useSealStore.getState().fetchSeals('v2');
  mockGet.mockResolvedValueOnce({ data: { pending: [pendingRecord] } });
  await useSealStore.getState().fetchPlan('v2');
}

describe('sealStore', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
    useSealStore.setState({
      versionId: null, seals: [], validityRecords: [], pendingPlan: [],
      isLoading: false, isSubmitting: false, error: null,
    });
  });

  it('fetchSeals loads the requested seal validity', async () => {
    mockGet.mockResolvedValueOnce({
      data: { seals: [seal], validity_records: [{ decision: 'preserved', seal }] },
    });

    await useSealStore.getState().fetchSeals('v1');

    expect(useSealStore.getState().seals).toHaveLength(1);
    expect(useSealStore.getState().validityRecords[0].decision).toBe('preserved');
  });

  it('[D4-F01-ui] createSeal refreshes the placed seal', async () => {
    mockPost.mockResolvedValueOnce({ data: seal });
    mockGet.mockResolvedValueOnce({ data: { seals: [seal], validity_records: [] } });

    const ok = await useSealStore.getState().createSeal('v1', {
      coversAll: false,
      sectionKeys: ['objeto-del-contrato'],
    });

    expect(ok).toBe(true);
    expect(mockPost).toHaveBeenCalledWith('versions/v1/seals/', {
      covers_all: false,
      section_keys: ['objeto-del-contrato'],
    });
    expect(useSealStore.getState().seals).toEqual([seal]);
  });

  it('createSeal surfaces the backend rejection', async () => {
    mockPost.mockRejectedValueOnce({
      response: { data: { error: 'Ya tienes un sello activo en esta versión.' } },
    });

    const ok = await useSealStore.getState().createSeal('v1', { coversAll: true });

    expect(ok).toBe(false);
    expect(useSealStore.getState().error).toContain('sello activo');
  });

  it('[D5-A04-ui] confirmPlan removes the resolved plan', async () => {
    mockGet.mockResolvedValueOnce({ data: { pending: [pendingRecord] } });
    await useSealStore.getState().fetchPlan('v2');
    expect(useSealStore.getState().pendingPlan).toEqual([pendingRecord]);
    mockPost.mockResolvedValueOnce({ data: { resolved: [] } });
    mockGet.mockResolvedValueOnce({ data: { seals: [], validity_records: [] } });

    const ok = await useSealStore.getState().confirmPlan('v2', { s2: 'invalidated' });

    expect(ok).toBe(true);
    expect(mockPost).toHaveBeenCalledWith('versions/v2/seal_plan/', {
      decisions: { s2: 'invalidated' },
    });
    expect(useSealStore.getState().pendingPlan).toEqual([]);
  });

  it('verifySeal returns the offline verification material', async () => {
    mockGet.mockResolvedValueOnce({
      data: { signature_valid: true, binds_version_sha256: true, algorithm: 'Ed25519' },
    });

    const result = await useSealStore.getState().verifySeal('v1', 's1');

    expect(result?.signature_valid).toBe(true);
    expect(result?.algorithm).toBe('Ed25519');
  });

  it.each(['fetchSeals', 'fetchPlan'] as const)('%s ignores a previous version response', async (fetch) => {
    // A late answer must not show another document's approval beside v2's PDF.
    const older = pendingResponse();
    mockGet.mockReturnValueOnce(older.promise);
    const oldRequest = useSealStore.getState()[fetch]('v1');
    await loadCurrentVersion();

    older.resolve({ data: { seals: [seal], validity_records: [], pending: [] } });
    await oldRequest;

    expect(useSealStore.getState()).toMatchObject({
      seals: [currentSeal], pendingPlan: [pendingRecord], error: null, isLoading: false,
    });
  });

  it.each(['fetchSeals', 'fetchPlan'] as const)('%s ignores a previous version failure', async (fetch) => {
    const older = pendingResponse();
    mockGet.mockReturnValueOnce(older.promise);
    const oldRequest = useSealStore.getState()[fetch]('v1');
    await loadCurrentVersion();

    older.reject(new Error('previous version unavailable'));
    await oldRequest;

    expect(useSealStore.getState()).toMatchObject({
      seals: [currentSeal], pendingPlan: [pendingRecord], error: null, isLoading: false,
    });
  });

  // Regression: returning to the same UUID cannot revive an earlier visit.
  it.each([
    { fetch: 'fetchSeals', expected: { seals: [currentSeal], pendingPlan: [] } },
    { fetch: 'fetchPlan', expected: { seals: [], pendingPlan: [pendingRecord] } },
  ] as const)('$fetch keeps the new visit after returning to an earlier version', async ({ fetch, expected }) => {
    const older = pendingResponse();
    mockGet.mockReturnValueOnce(older.promise);
    const oldRequest = useSealStore.getState()[fetch]('v1');
    await loadCurrentVersion();
    mockGet.mockResolvedValueOnce({
      data: { seals: [currentSeal], validity_records: [], pending: [pendingRecord] },
    });
    await useSealStore.getState()[fetch]('v1');

    older.resolve({ data: { seals: [seal], validity_records: [], pending: [] } });
    await oldRequest;

    expect(useSealStore.getState()).toMatchObject(expected);
  });

  it.each(['create', 'revoke', 'confirm'] as const)('%s preserves the current version after an old mutation succeeds', async (operation) => {
    const mutation = pendingResponse();
    mockPost.mockReturnValueOnce(mutation.promise);
    mockGet.mockResolvedValueOnce({ data: { seals: [seal], validity_records: [] } });
    await useSealStore.getState().fetchSeals('v1');
    const actions = {
      create: () => useSealStore.getState().createSeal('v1', { coversAll: true }),
      revoke: () => useSealStore.getState().revokeSeal('v1', 's1'),
      confirm: () => useSealStore.getState().confirmPlan('v1', { s1: 'invalidated' }),
    };
    const request = actions[operation]();
    await loadCurrentVersion();
    mockGet.mockResolvedValue({ data: { seals: [seal], validity_records: [] } });

    mutation.resolve({ data: {} });
    const result = await request;

    expect(result).toBe(true);
    expect(useSealStore.getState()).toMatchObject({
      seals: [currentSeal], pendingPlan: [pendingRecord], error: null, isSubmitting: false,
    });
    expect(mockGet.mock.calls.map(([url]) => url)).toEqual([
      'versions/v1/seals/', 'versions/v2/seals/', 'versions/v2/seal_plan/',
    ]);
  });

  it.each(['create', 'revoke', 'confirm'] as const)('%s preserves the current version after an old mutation fails', async (operation) => {
    const mutation = pendingResponse();
    mockPost.mockReturnValueOnce(mutation.promise);
    mockGet.mockResolvedValueOnce({ data: { seals: [seal], validity_records: [] } });
    await useSealStore.getState().fetchSeals('v1');
    const actions = {
      create: () => useSealStore.getState().createSeal('v1', { coversAll: true }),
      revoke: () => useSealStore.getState().revokeSeal('v1', 's1'),
      confirm: () => useSealStore.getState().confirmPlan('v1', { s1: 'invalidated' }),
    };
    const request = actions[operation]();
    await loadCurrentVersion();

    mutation.reject(new Error('old mutation rejected'));
    const result = await request;

    expect(result).toBe(false);
    expect(useSealStore.getState()).toMatchObject({
      seals: [currentSeal], pendingPlan: [pendingRecord], error: null, isSubmitting: false,
    });
  });

  it('confirmPlan keeps the resolved plan empty after a pending read finishes', async () => {
    await loadCurrentVersion();
    const older = pendingResponse();
    mockGet.mockReturnValueOnce(older.promise);
    const read = useSealStore.getState().fetchPlan('v2');
    mockPost.mockResolvedValueOnce({ data: { resolved: [] } });
    mockGet.mockResolvedValueOnce({ data: { seals: [currentSeal], validity_records: [] } });

    await useSealStore.getState().confirmPlan('v2', { s2: 'invalidated' });
    older.resolve({ data: { pending: [pendingRecord] } });
    await read;

    expect(useSealStore.getState()).toMatchObject({ pendingPlan: [], seals: [currentSeal] });
  });

  it('verifySeal ignores an error from a previous version', async () => {
    const older = pendingResponse();
    mockGet.mockReturnValueOnce(older.promise);
    const request = useSealStore.getState().verifySeal('v1', 's1');
    await loadCurrentVersion();

    older.reject(new Error('old signature unavailable'));
    const result = await request;

    expect(result).toBeNull();
    expect(useSealStore.getState()).toMatchObject({ seals: [currentSeal], error: null });
  });

  it('fetchPlan removes the previous version evidence before its answer', async () => {
    await loadCurrentVersion();
    const pending = pendingResponse();
    mockGet.mockReturnValueOnce(pending.promise);

    const request = useSealStore.getState().fetchPlan('v3');
    const loading = useSealStore.getState();
    pending.resolve({ data: { pending: [] } });
    await request;

    expect(loading).toMatchObject({ seals: [], validityRecords: [], pendingPlan: [] });
    expect(useSealStore.getState().pendingPlan).toEqual([]);
  });
});
