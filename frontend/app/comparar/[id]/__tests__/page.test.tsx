import { act, cleanup, render, screen } from '@testing-library/react';

import CompararResultPage from '../page';
import { publicApi } from '@/lib/services/http';
import {
  type PublicComparisonDetail,
  usePublicCompareStore,
} from '@/lib/stores/publicCompareStore';

jest.mock('@/lib/services/http', () => ({
  publicApi: { get: jest.fn(), post: jest.fn() },
}));
let mockResultId = 'first';
jest.mock('next/navigation', () => ({
  useParams: () => ({ id: mockResultId }),
}));

const mockGet = publicApi.get as jest.Mock;

function result(publicId: string, status: PublicComparisonDetail['status']) {
  return {
    public_id: publicId,
    status,
    error_code: '',
    file_a_name: `${publicId}-before.pdf`,
    file_b_name: `${publicId}-after.pdf`,
    created_at: '2026-10-08T00:00:00Z',
    expires_at: '2026-10-09T00:00:00Z',
    result: {
      counts: { modified: 1, added: 0, removed: 0, unchanged: 0, renamed_only: 0 },
      summary_text: `${publicId} comparison`,
      sections: [],
      meta: { page_count_a: 1, page_count_b: 1 },
    },
  };
}

describe('public comparison result lifecycle', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    mockGet.mockReset();
    mockResultId = 'first';
    usePublicCompareStore.getState().reset();
  });

  afterEach(() => {
    cleanup();
    usePublicCompareStore.getState().reset();
    jest.useRealTimers();
  });

  it('stops polling when the result page unmounts', async () => {
    mockGet.mockResolvedValue({ data: result('first', 'processing') });
    const page = render(<CompararResultPage />);
    await act(() => jest.advanceTimersByTimeAsync(0));
    expect(screen.getByRole('status')).toHaveTextContent('Analizando y comparando');
    const signal = mockGet.mock.calls[0][1].signal as AbortSignal;

    page.unmount();
    await act(() => jest.advanceTimersByTimeAsync(60_000));

    expect(signal.aborted).toBe(true);
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it('keeps the selected result after the previous page request settles', async () => {
    let resolveFirst!: (value: { data: ReturnType<typeof result> }) => void;
    mockGet.mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }));
    mockGet.mockResolvedValueOnce({ data: result('second', 'done') });
    const page = render(<CompararResultPage />);
    const firstSignal = mockGet.mock.calls[0][1].signal as AbortSignal;

    mockResultId = 'second';
    page.rerender(<CompararResultPage />);
    await act(async () => {
      resolveFirst({ data: result('first', 'done') });
    });

    expect(screen.getByTestId('public-files-line')).toHaveTextContent(
      'second-before.pdf → second-after.pdf'
    );
    expect(screen.queryByText('first comparison')).not.toBeInTheDocument();
    expect(firstSignal.aborted).toBe(true);
    expect(mockGet).toHaveBeenCalledTimes(2);
  });
});
