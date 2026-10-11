import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLayoutEffect } from 'react';

import { SealsPanel } from '../SealsPanel';
import { useToastStore } from '../../ui/toast';
import { api } from '../../../lib/services/http';
import { useLocaleStore } from '../../../lib/stores/localeStore';
import { useSealStore, type SealSummary, type ValidityRecord } from '../../../lib/stores/sealStore';

jest.mock('../../../lib/services/http', () => ({
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

const seal: SealSummary = {
  public_id: 's1',
  reviewer_email: 'a@versiona.test',
  version_number: 1,
  covers_all: false,
  covered_keys: ['objeto-del-contrato', 'definiciones'],
  key_id: 'k1',
  is_active: true,
  revoked_at: null,
  created_at: '2026-07-12T10:00:00Z',
};
const currentSeal = { ...seal, public_id: 's2', reviewer_email: 'b@versiona.test' };

const record = (over: Partial<ValidityRecord> = {}): ValidityRecord => ({
  seal,
  to_version: 2,
  decision: 'preserved',
  proposed_decision: 'preserved',
  reason_code: 'all_sections_unchanged',
  evidence: { verified: [{ stable_key: 'objeto-del-contrato' }] },
  decided_mode: 'auto',
  decided_by_email: null,
  decided_at: '2026-07-12T11:00:00Z',
  ...over,
});
const pendingRecord = (owner: SealSummary): ValidityRecord => record({
  seal: owner,
  decision: 'pending_confirmation',
  proposed_decision: 'invalidated',
  reason_code: 'section_modified',
  evidence: { changed: [{ stable_key: 'obligaciones-del-contratista', change_type: 'modified' }] },
  decided_mode: 'coordinator',
  decided_at: null,
});

function answer(seals: SealSummary[] = [], records: ValidityRecord[] = [], pending: ValidityRecord[] = []) {
  mockGet.mockResolvedValueOnce({ data: { seals, validity_records: records } })
    .mockResolvedValueOnce({ data: { pending } });
}

async function mount(props: Parameters<typeof SealsPanel>[0]) {
  let result!: ReturnType<typeof render>;
  await act(async () => { result = render(<SealsPanel {...props} />); });
  return result;
}

async function loadPreviousPlan() {
  answer([], [pendingRecord(seal)], [pendingRecord(seal)]);
  await useSealStore.getState().fetchSeals('v1');
  await useSealStore.getState().fetchPlan('v1');
}

describe('SealsPanel', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
    useSealStore.setState({
      versionId: null, seals: [], validityRecords: [], pendingPlan: [],
      isLoading: false, isSubmitting: false, error: null,
    });
    useToastStore.getState().clear();
    useLocaleStore.setState({ locale: 'es' });
  });

  it('[D4-L01] shows the guided empty state without seals', async () => {
    answer();

    await mount({ versionId: 'v1', canConfirmPlan: false });

    expect(screen.getByText('Esta versión aún no tiene sellos.')).toBeInTheDocument();
  });

  it('[D4-F01] lists the requested seal scope', async () => {
    answer([seal]);

    await mount({ versionId: 'v1', canConfirmPlan: false });

    expect(screen.getByTestId('seal-a@versiona.test')).toBeInTheDocument();
    expect(screen.getByText('Vigente')).toBeInTheDocument();
    expect(screen.getByText(/objeto-del-contrato, definiciones/)).toBeInTheDocument();
  });

  it('[D5-F02] explains preservation with hash equality', async () => {
    answer([], [record()]);

    await mount({ versionId: 'v2', canConfirmPlan: false });

    expect(screen.getByTestId('validity-a@versiona.test')).toHaveAttribute('data-decision', 'preserved');
    expect(screen.getByText('Conservado')).toBeInTheDocument();
    expect(screen.getByText(/igualdad de hash verificada/)).toBeInTheDocument();
  });

  it('[D5-F01] explains invalidation with the changed sections', async () => {
    answer([], [record({
      decision: 'invalidated', reason_code: 'section_modified',
      evidence: {
        changed: [{ stable_key: 'obligaciones-del-contratista', change_type: 'modified' }],
        still_intact: [{ stable_key: 'objeto-del-contrato' }],
      },
    })]);

    await mount({ versionId: 'v2', canConfirmPlan: false });

    expect(screen.getByText('Requiere re-revisión')).toBeInTheDocument();
    expect(screen.getByText(/obligaciones-del-contratista/)).toBeInTheDocument();
    expect(screen.getByText(/Secciones intactas del sello/)).toBeInTheDocument();
  });

  it('[D5-A04] hides confirmation from a reader', async () => {
    answer([], [], [pendingRecord(seal)]);

    await mount({ versionId: 'v2', canConfirmPlan: false });

    expect(screen.queryByTestId('invalidation-review-card')).not.toBeInTheDocument();
    expect(screen.getByTestId('seals-panel')).toBeInTheDocument();
  });

  it('[D5-A04] offers the loaded plan to its coordinator', async () => {
    answer([], [], [pendingRecord(seal)]);

    await mount({ versionId: 'v2', canConfirmPlan: true });

    expect(screen.getByTestId('invalidation-review-card')).toBeInTheDocument();
    expect(screen.getByTestId('plan-invalidated-s1')).toBeChecked();
  });

  it('[D4-A01] offers withdrawal on my active seal', async () => {
    answer([seal]);
    const onWithdraw = jest.fn();
    await mount({ versionId: 'v1', canConfirmPlan: false, currentUserEmail: seal.reviewer_email, onWithdraw });

    await userEvent.click(screen.getByTestId('withdraw-seal'));

    expect(onWithdraw).toHaveBeenCalledWith(seal);
    expect(screen.getByTestId('seal-a@versiona.test')).toBeInTheDocument();
  });

  it('[D4-A01] hides withdrawal on another reviewer seal', async () => {
    answer([seal]);

    await mount({ versionId: 'v1', canConfirmPlan: false, currentUserEmail: 'otra@versiona.test', onWithdraw: jest.fn() });

    expect(screen.queryByTestId('withdraw-seal')).not.toBeInTheDocument();
    expect(screen.getByTestId('seal-a@versiona.test')).toBeInTheDocument();
  });

  it('filters previous version evidence before effects run', async () => {
    answer([seal], [record()], [pendingRecord(seal)]);
    await useSealStore.getState().fetchSeals('v1');
    await useSealStore.getState().fetchPlan('v1');
    answer();
    let firstMarkup = '';
    function FirstRender() {
      useLayoutEffect(() => { firstMarkup = document.body.innerHTML; }, []);
      return <SealsPanel versionId="v2" canConfirmPlan />;
    }

    await act(async () => { render(<FirstRender />); });

    expect(firstMarkup).toContain('seals-loading');
    expect(firstMarkup).not.toContain('a@versiona.test');
    expect(firstMarkup).not.toContain('invalidation-review-card');
  });

  it('mounts the next version without the previous plan defaults', async () => {
    await loadPreviousPlan();
    const currentPlan = pendingResponse();
    mockGet.mockResolvedValueOnce({ data: { seals: [], validity_records: [pendingRecord(currentSeal)] } })
      .mockReturnValueOnce(currentPlan.promise);
    await mount({ versionId: 'v2', canConfirmPlan: true });

    expect(screen.getByTestId('validity-b@versiona.test')).toHaveAttribute('data-decision', 'pending_confirmation');
    expect(screen.queryByTestId('invalidation-review-card')).not.toBeInTheDocument();
    await act(async () => currentPlan.resolve({ data: { pending: [pendingRecord(currentSeal)] } }));

    expect(screen.getByTestId('plan-invalidated-s2')).toBeChecked();
    expect(screen.queryByTestId('plan-item-a@versiona.test')).not.toBeInTheDocument();
  });

  it('confirms the new version proposal after a retained panel rerenders', async () => {
    answer([], [pendingRecord(seal)], [pendingRecord(seal)]);
    const { rerender } = await mount({ versionId: 'v1', canConfirmPlan: true });
    const currentPlan = pendingResponse();
    mockGet.mockResolvedValueOnce({ data: { seals: [], validity_records: [pendingRecord(currentSeal)] } })
      .mockReturnValueOnce(currentPlan.promise);
    await act(async () => rerender(<SealsPanel versionId="v2" canConfirmPlan />));
    expect(screen.queryByTestId('invalidation-review-card')).not.toBeInTheDocument();
    await act(async () => currentPlan.resolve({ data: { pending: [pendingRecord(currentSeal)] } }));
    mockPost.mockResolvedValueOnce({ data: { resolved: [] } });
    mockGet.mockResolvedValueOnce({ data: {
      seals: [], validity_records: [record({ seal: currentSeal, decision: 'invalidated' })],
    } });

    await userEvent.click(screen.getByTestId('confirm-plan'));

    expect(mockPost).toHaveBeenCalledWith('versions/v2/seal_plan/', { decisions: { s2: 'invalidated' } });
    expect(screen.getByTestId('validity-b@versiona.test')).toHaveAttribute('data-decision', 'invalidated');
    expect(screen.queryByTestId('invalidation-review-card')).not.toBeInTheDocument();
  });

  it.each(['success', 'failure'] as const)('keeps current approval visible after the previous version %s', async (outcome) => {
    const olderSeals = pendingResponse();
    const olderPlan = pendingResponse();
    mockGet.mockReturnValueOnce(olderSeals.promise).mockReturnValueOnce(olderPlan.promise);
    const { rerender } = await mount({ versionId: 'v1', canConfirmPlan: true });
    answer([], [record({ seal: currentSeal, decision: 'invalidated' })]);
    await act(async () => rerender(<SealsPanel versionId="v2" canConfirmPlan />));
    const settle = {
      success: () => {
        olderSeals.resolve({ data: { seals: [seal], validity_records: [record()] } });
        olderPlan.resolve({ data: { pending: [pendingRecord(seal)] } });
      },
      failure: () => {
        olderSeals.reject(new Error('old seals unavailable'));
        olderPlan.reject(new Error('old plan unavailable'));
      },
    };

    await act(async () => settle[outcome]());

    expect(screen.getByTestId('validity-b@versiona.test')).toHaveAttribute('data-decision', 'invalidated');
    expect(screen.queryByTestId('seal-a@versiona.test')).not.toBeInTheDocument();
    expect(screen.queryByTestId('invalidation-review-card')).not.toBeInTheDocument();
    expect(useSealStore.getState().error).toBeNull();
  });

  it('ignores a previous version signature result after rerender', async () => {
    answer([seal]);
    const { rerender } = await mount({ versionId: 'v1', canConfirmPlan: false });
    const verification = pendingResponse();
    mockGet.mockReturnValueOnce(verification.promise);
    await userEvent.click(screen.getByTestId('verify-s1'));
    answer([currentSeal]);
    await act(async () => rerender(<SealsPanel versionId="v2" canConfirmPlan={false} />));

    await act(async () => verification.resolve({ data: { signature_valid: true } }));

    expect(screen.getByTestId('seal-b@versiona.test')).toBeInTheDocument();
    expect(useToastStore.getState().toasts).toEqual([]);
    expect(screen.queryByText('Ed25519 ✓')).not.toBeInTheDocument();
  });
});
