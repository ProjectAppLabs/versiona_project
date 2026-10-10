import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { CompareView } from '../CompareView';
import type { ComparisonDetail } from '../../../lib/stores/compareStore';
import { api } from '../../../lib/services/http';
import { useVersionStore } from '../../../lib/stores/versionStore';
import { useUpgradeDialogStore } from '../../../lib/stores/upgradeDialogStore';

jest.mock('next/dynamic', () => ({
  __esModule: true,
  default: () => {
    const Stub = ({ file }: { file: string }) => <div data-testid="pdf-stub">{file}</div>;
    return Stub;
  },
}));

const compare = jest.fn();
const fetchSectionDiff = jest.fn();
const setActiveSection = jest.fn();
const reset = jest.fn();
let storeState: Record<string, unknown> = {};

jest.mock('../../../lib/stores/compareStore', () => ({
  useCompareStore: Object.assign(
    (selector: (s: Record<string, unknown>) => unknown) => selector(storeState),
    { getState: () => storeState }
  ),
}));
jest.mock('../../../lib/services/http', () => ({
  api: { get: jest.fn(), post: jest.fn().mockResolvedValue({ data: {} }) },
}));
const mockGet = api.get as jest.Mock;
const toast = jest.fn();
jest.mock('../../../components/ui/toast', () => ({
  useToast: () => ({ toast }),
}));

const comparison: ComparisonDetail = {
  public_id: 'cmp1',
  status: 'done',
  summary: { text: '2 modificadas, 1 eliminada, 1 agregada', counts: {} },
  has_changes: true,
  from_version: 'v1',
  to_version: 'v2',
  from_number: 1,
  to_number: 2,
  section_changes: [
    { stable_key: 'objeto', heading_from: '1. OBJETO', heading_to: '1. OBJETO',
      change_type: 'unchanged', similarity: 1, order_index: 0 },
    { stable_key: 'multas', heading_from: '3. MULTAS', heading_to: '3. MULTAS',
      change_type: 'modified', similarity: 0.9, order_index: 1 },
  ],
};

function setState(over: Record<string, unknown> = {}) {
  storeState = {
    comparison,
    requestKey: JSON.stringify(['d1', 'v1', 'v2']),
    diffs: {},
    activeSection: null,
    isLoading: false,
    error: null,
    compare,
    fetchSectionDiff,
    setActiveSection,
    reset,
    ...over,
  };
}

const baseProps = {
  documentId: 'd1',
  fromVersionId: 'v1',
  toVersionId: 'v2',
  view: 'side' as const,
  onViewChange: jest.fn(),
};

describe('CompareView (E1)', () => {
  beforeEach(() => {
    compare.mockReset();
    reset.mockReset();
    fetchSectionDiff.mockResolvedValue(null);
    mockGet.mockReset().mockResolvedValue({ data: { url: 'http://minio/f.pdf' } });
    useVersionStore.setState(useVersionStore.getInitialState(), true);
    useUpgradeDialogStore.getState().hide();
    window.history.replaceState(null, '', '/');
    setState();
  });

  it('[E1-F01] the side-by-side view renders both viewers and the summary', async () => {
    await renderCompare(baseProps);

    expect(compare).toHaveBeenCalledWith('d1', 'v1', 'v2');
    expect(screen.getByTestId('side-before')).toBeInTheDocument();
    expect(screen.getByTestId('side-after')).toBeInTheDocument();
    expect(screen.getByText(/2 modificadas, 1 eliminada, 1 agregada/)).toBeInTheDocument();
  });

  it('[E1-F01b] the summary view shows the exact counters', async () => {
    await renderCompare({ ...baseProps, view: 'summary' });

    expect(screen.getByTestId('count-modified')).toHaveTextContent('1');
    expect(screen.getByTestId('count-unchanged')).toHaveTextContent('1');
  });

  it('[E1-F02] next-change selects the first changed section', async () => {
    await renderCompare(baseProps);

    await userEvent.click(screen.getByTestId('next-change'));

    expect(setActiveSection).toHaveBeenCalledWith('multas');
    expect(fetchSectionDiff).toHaveBeenCalledWith('multas');
  });

  it('[E1-L01] a comparison without changes shows the explicit empty state', async () => {
    setState({
      comparison: { ...comparison, has_changes: false, section_changes: [] },
    });

    await renderCompare(baseProps);

    expect(screen.getByTestId('no-changes')).toBeInTheDocument();
    expect(screen.getByText('Sin cambios entre estas versiones')).toBeInTheDocument();
  });

  it('[E1-E01] a failed comparison offers retry', async () => {
    setState({ comparison: null, error: 'La versión v2 aún no está analizada' });

    await renderCompare(baseProps);

    expect(screen.getByTestId('async-error')).toHaveTextContent('no está analizada');
    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(compare).toHaveBeenCalledTimes(2);
  });

  it('[E2-F01-ui] the save button posts the chosen name', async () => {
    const { api } = jest.requireMock('../../../lib/services/http');
    window.prompt = jest.fn().mockReturnValue('Entrega 1 vs 2');

    await renderCompare(baseProps);
    await userEvent.click(screen.getByTestId('save-comparison'));

    expect(api.post).toHaveBeenCalledWith('comparisons/cmp1/save/', {
      name: 'Entrega 1 vs 2',
    });
  });

  it('keeps the current PDF pair after older URLs respond', async () => {
    // Bug: a reused CompareView cannot apply the previous pair's late PDFs.
    const oldFrom = pendingResponse();
    const oldTo = pendingResponse();
    mockGet.mockReturnValueOnce(oldFrom.promise).mockReturnValueOnce(oldTo.promise)
      .mockResolvedValueOnce({ data: { url: 'v3.pdf' } })
      .mockResolvedValueOnce({ data: { url: 'v4.pdf' } });
    const { rerender } = await renderCompare(baseProps);
    setCurrentPair();
    await act(async () => { rerender(<CompareView {...baseProps} fromVersionId="v3" toVersionId="v4" />); });

    await act(async () => {
      oldFrom.resolve({ data: { url: 'v1.pdf' } });
      oldTo.resolve({ data: { url: 'v2.pdf' } });
    });

    expect(within(screen.getByTestId('side-before')).getByTestId('pdf-stub')).toHaveTextContent('v3.pdf');
    expect(within(screen.getByTestId('side-after')).getByTestId('pdf-stub')).toHaveTextContent('v4.pdf');
  });

  it('removes the previous PDFs while a new pair loads', async () => {
    mockGet.mockResolvedValueOnce({ data: { url: 'v1.pdf' } })
      .mockResolvedValueOnce({ data: { url: 'v2.pdf' } });
    const { rerender } = await renderCompare(baseProps);
    expect(await screen.findByText('v1.pdf')).toBeInTheDocument();
    mockGet.mockReturnValue(new Promise(() => {}));
    setCurrentPair();

    rerender(<CompareView {...baseProps} fromVersionId="v3" toVersionId="v4" />);

    expect(screen.getByTestId('side-before')).toHaveTextContent('v3');
    expect(screen.queryAllByTestId('pdf-stub')).toHaveLength(0);
  });

  it('ignores an old PDF history lock after the pair changes', async () => {
    const old = pendingResponse();
    mockGet.mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce({ data: { url: 'v2.pdf' } })
      .mockResolvedValueOnce({ data: { url: 'v3.pdf' } })
      .mockResolvedValueOnce({ data: { url: 'v4.pdf' } });
    const { rerender } = await renderCompare(baseProps);
    setCurrentPair();
    await act(async () => { rerender(<CompareView {...baseProps} fromVersionId="v3" toVersionId="v4" />); });

    await act(async () => { old.reject(historyLockError); });

    expect(useUpgradeDialogStore.getState().isOpen).toBe(false);
    expect(within(screen.getByTestId('side-before')).getByTestId('pdf-stub')).toHaveTextContent('v3.pdf');
  });

  it('ignores a PDF history lock after unmounting', async () => {
    const old = pendingResponse();
    mockGet.mockReturnValueOnce(old.promise).mockResolvedValueOnce({ data: { url: 'v2.pdf' } });
    const { unmount } = await renderCompare(baseProps);
    unmount();

    await act(async () => { old.reject(historyLockError); });

    expect(useUpgradeDialogStore.getState()).toMatchObject({ isOpen: false, detail: null });
  });

  it('reports a current PDF history lock from the first side', async () => {
    const before = pendingResponse();
    mockGet.mockReturnValueOnce(before.promise).mockResolvedValueOnce({ data: { url: 'v2.pdf' } });
    await renderCompare(baseProps);
    expect(await screen.findByText('v2.pdf')).toBeInTheDocument();

    await act(async () => { before.reject(historyLockError); });

    expect(useUpgradeDialogStore.getState()).toMatchObject({ isOpen: true, detail: historyLockError.response.data.error });
    expect(within(screen.getByTestId('side-after')).getByTestId('pdf-stub')).toHaveTextContent('v2.pdf');
  });
});

function pendingResponse() {
  let resolve!: (response: { data: unknown }) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<{ data: unknown }>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

const historyLockError = {
  response: { status: 402, data: { upgrade: true, error: 'El historial anterior está bloqueado.' } },
};

function setCurrentPair() {
  setState({
    requestKey: JSON.stringify(['d1', 'v3', 'v4']),
    comparison: { ...comparison, public_id: 'cmp-current', from_version: 'v3', to_version: 'v4', from_number: 3, to_number: 4 },
  });
}

async function renderCompare(props: Parameters<typeof CompareView>[0]) {
  let result!: ReturnType<typeof render>;
  await act(async () => { result = render(<CompareView {...props} />); });
  return result;
}
