import { api } from '../../services/http';
import { useUpgradeDialogStore } from '../upgradeDialogStore';
import {
  useCompareStore,
  type ComparisonDetail,
  type SectionDiffDetail,
} from '../compareStore';

jest.mock('../../services/http', () => ({
  api: { get: jest.fn(), post: jest.fn() },
}));

const mockGet = api.get as jest.Mock;
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

const createComparison = (overrides: Partial<ComparisonDetail> = {}): ComparisonDetail => ({
  public_id: 'cmp-1',
  status: 'done',
  summary: { counts: { modified: 1 }, text: '1 sección modificada' },
  has_changes: true,
  from_version: 'ver-1',
  to_version: 'ver-2',
  from_number: 1,
  to_number: 2,
  section_changes: [],
  ...overrides,
});

const createDiff = (overrides: Partial<SectionDiffDetail> = {}): SectionDiffDetail => ({
  stable_key: 'sec-1',
  heading_from: '1. Alcance',
  heading_to: '1. Alcance',
  change_type: 'modified',
  similarity: 0.9,
  order_index: 0,
  word_diff: [{ op: 'equal', text: 'hola' }],
  bboxes_from: [{ page: 1, x0: 0, y0: 0, x1: 1, y1: 1 }],
  bboxes_to: [],
  ...overrides,
});

describe('compareStore', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
    useCompareStore.setState({
      comparison: null,
      diffs: {},
      activeSection: null,
      isLoading: false,
      error: null,
    });
    useUpgradeDialogStore.getState().hide();
  });

  it('stores the comparison returned by the API', async () => {
    const comparison = createComparison();
    mockPost.mockResolvedValueOnce({ data: comparison });

    await useCompareStore.getState().compare('doc-1', 'ver-1', 'ver-2');

    expect(useCompareStore.getState().comparison).toEqual(comparison);
    expect(useCompareStore.getState().isLoading).toBe(false);
  });

  it('keeps the current comparison after an older pair responds', async () => {
    // Bug: navigating to v2/v3 must not let a late v1/v2 response replace it.
    const older = pendingResponse();
    const current = pendingResponse();
    mockPost.mockReturnValueOnce(older.promise).mockReturnValueOnce(current.promise);
    const olderRequest = useCompareStore.getState().compare('doc-1', 'ver-1', 'ver-2');
    const currentRequest = useCompareStore.getState().compare('doc-1', 'ver-2', 'ver-3');
    const expected = createComparison({ public_id: 'current', from_version: 'ver-2', to_version: 'ver-3' });
    current.resolve({ data: expected });
    await currentRequest;

    older.resolve({ data: createComparison({ public_id: 'older' }) });
    await olderRequest;

    expect(useCompareStore.getState().comparison).toEqual(expected);
  });

  it('sends the version pair to the document comparisons endpoint', async () => {
    mockPost.mockResolvedValueOnce({ data: createComparison() });

    await useCompareStore.getState().compare('doc-1', 'ver-1', 'ver-2');

    expect(mockPost).toHaveBeenCalledWith('documents/doc-1/comparisons/', {
      from_version: 'ver-1',
      to_version: 'ver-2',
    });
  });

  it('clears the previous result while a new compare is in flight', () => {
    useCompareStore.setState({
      comparison: createComparison(),
      diffs: { 'sec-1': createDiff() },
    });
    mockPost.mockReturnValueOnce(new Promise(() => {}));

    void useCompareStore.getState().compare('doc-1', 'ver-1', 'ver-2');

    expect(useCompareStore.getState().isLoading).toBe(true);
    expect(useCompareStore.getState().comparison).toBeNull();
    expect(useCompareStore.getState().diffs).toEqual({});
  });

  it('stores the server error message when compare fails', async () => {
    mockPost.mockRejectedValueOnce({
      response: { data: { error: 'La versión origen no está analizada' } },
    });

    await useCompareStore.getState().compare('doc-1', 'ver-1', 'ver-2');

    expect(useCompareStore.getState().error).toBe('La versión origen no está analizada');
    expect(useCompareStore.getState().isLoading).toBe(false);
  });

  it('falls back to the thrown message when the response has no error field', async () => {
    mockPost.mockRejectedValueOnce(new Error('Network Error'));

    await useCompareStore.getState().compare('doc-1', 'ver-1', 'ver-2');

    expect(useCompareStore.getState().error).toBe('Network Error');
  });

  it('uses the generic message when the failure carries no details', async () => {
    mockPost.mockRejectedValueOnce({});

    await useCompareStore.getState().compare('doc-1', 'ver-1', 'ver-2');

    expect(useCompareStore.getState().error).toBe('No se pudo comparar');
  });

  it('returns null from fetchSectionDiff without a loaded comparison', async () => {
    // quality: allow-negation-only (early-return guard with no other state mutated on this path — compareStore.ts:69 'if (!comparison) return null' — both existing assertions, the null return AND the non-call of mockGet, already fully describe this branch's behavior; nothing else to anchor on without duplicating the sibling test at line 123)
    const result = await useCompareStore.getState().fetchSectionDiff('sec-1');

    expect(result).toBeNull();
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('fetches the section diff from the comparison endpoint', async () => {
    useCompareStore.setState({ comparison: createComparison() });
    const diff = createDiff();
    mockGet.mockResolvedValueOnce({ data: diff });

    const result = await useCompareStore.getState().fetchSectionDiff('sec-1');

    expect(mockGet).toHaveBeenCalledWith('comparisons/cmp-1/sections/sec-1/diff/');
    expect(result).toEqual(diff);
  });

  it('caches the fetched section diff in the store', async () => {
    useCompareStore.setState({ comparison: createComparison() });
    const diff = createDiff();
    mockGet.mockResolvedValueOnce({ data: diff });

    await useCompareStore.getState().fetchSectionDiff('sec-1');

    expect(useCompareStore.getState().diffs['sec-1']).toEqual(diff);
  });

  it('serves a cached section diff without refetching', async () => {
    const cached = createDiff();
    useCompareStore.setState({
      comparison: createComparison(),
      diffs: { 'sec-1': cached },
    });

    const result = await useCompareStore.getState().fetchSectionDiff('sec-1');

    expect(result).toBe(cached);
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('stores the error when the section diff request fails', async () => {
    useCompareStore.setState({ comparison: createComparison() });
    mockGet.mockRejectedValueOnce({
      response: { data: { error: 'Sección no encontrada' } },
    });

    const result = await useCompareStore.getState().fetchSectionDiff('sec-9');

    expect(result).toBeNull();
    expect(useCompareStore.getState().error).toBe('Sección no encontrada');
  });

  it('setActiveSection stores the active section key', () => {
    useCompareStore.getState().setActiveSection('sec-2');

    expect(useCompareStore.getState().activeSection).toBe('sec-2');
  });

  it('reset clears the comparison state', () => {
    useCompareStore.setState({
      comparison: createComparison(),
      diffs: { 'sec-1': createDiff() },
      activeSection: 'sec-1',
      error: 'boom',
    });

    useCompareStore.getState().reset();

    expect(useCompareStore.getState()).toMatchObject({
      comparison: null,
      diffs: {},
      activeSection: null,
      error: null,
    });
  });

  it('keeps the current comparison after an older pair fails', async () => {
    const older = pendingResponse();
    mockPost.mockReturnValueOnce(older.promise)
      .mockResolvedValueOnce({ data: createComparison({ public_id: 'current' }) });
    const olderRequest = useCompareStore.getState().compare('doc-1', 'ver-1', 'ver-2');
    await useCompareStore.getState().compare('doc-1', 'ver-2', 'ver-3');

    older.reject(new Error('old comparison unavailable'));
    await olderRequest;

    expect(useCompareStore.getState()).toMatchObject({
      comparison: { public_id: 'current' }, error: null, isLoading: false,
    });
  });

  it('ignores a history lock from an older pair', async () => {
    const older = pendingResponse();
    mockPost.mockReturnValueOnce(older.promise)
      .mockResolvedValueOnce({ data: createComparison({ public_id: 'current' }) });
    const olderRequest = useCompareStore.getState().compare('doc-1', 'ver-1', 'ver-2');
    await useCompareStore.getState().compare('doc-1', 'ver-2', 'ver-3');

    older.reject({ response: { status: 402, data: { upgrade: true, error: 'Old history lock' } } });
    await olderRequest;

    expect(useUpgradeDialogStore.getState().isOpen).toBe(false);
    expect(useCompareStore.getState()).toMatchObject({ comparison: { public_id: 'current' }, error: null });
  });

  it('keeps the current section diff after an older comparison diff responds', async () => {
    useCompareStore.setState({ comparison: createComparison() });
    const older = pendingResponse();
    mockGet.mockReturnValueOnce(older.promise).mockResolvedValueOnce({ data: createDiff() });
    mockPost.mockResolvedValueOnce({ data: createComparison({ public_id: 'current' }) });
    const oldRequest = useCompareStore.getState().fetchSectionDiff('sec-1');
    await useCompareStore.getState().compare('doc-1', 'ver-2', 'ver-3');
    await useCompareStore.getState().fetchSectionDiff('sec-1');

    older.resolve({ data: createDiff({ word_diff: [{ op: 'delete', text: 'old content' }] }) });
    await oldRequest;

    expect(useCompareStore.getState().diffs['sec-1']).toEqual(createDiff());
  });

  it('ignores a section error from an older comparison', async () => {
    useCompareStore.setState({ comparison: createComparison() });
    const older = pendingResponse();
    mockGet.mockReturnValueOnce(older.promise);
    mockPost.mockResolvedValueOnce({ data: createComparison({ public_id: 'current' }) });
    const oldRequest = useCompareStore.getState().fetchSectionDiff('sec-1');
    await useCompareStore.getState().compare('doc-1', 'ver-2', 'ver-3');

    older.reject(new Error('old section unavailable'));
    await oldRequest;

    expect(useCompareStore.getState()).toMatchObject({ comparison: { public_id: 'current' }, error: null });
  });

  it('keeps the comparison reset after its pending response arrives', async () => {
    const pending = pendingResponse();
    mockPost.mockReturnValueOnce(pending.promise);
    const request = useCompareStore.getState().compare('doc-1', 'ver-1', 'ver-2');
    useCompareStore.getState().reset();

    pending.resolve({ data: createComparison() });
    await request;

    expect(useCompareStore.getState()).toMatchObject({ comparison: null, diffs: {}, isLoading: false });
  });

  it('clears the selected section when a new comparison begins', () => {
    useCompareStore.setState({ comparison: createComparison(), activeSection: 'sec-1' });
    mockPost.mockReturnValueOnce(new Promise(() => {}));

    void useCompareStore.getState().compare('doc-1', 'ver-2', 'ver-3');

    expect(useCompareStore.getState()).toMatchObject({ comparison: null, activeSection: null, isLoading: true });
  });
});
