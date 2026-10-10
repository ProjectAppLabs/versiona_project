import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import VersionViewerPage from '../page';
import { api } from '@/lib/services/http';
import { useReviewStore } from '@/lib/stores/reviewStore';
import { useVersionStore } from '@/lib/stores/versionStore';
import { useUpgradeDialogStore } from '@/lib/stores/upgradeDialogStore';

const mockScrollRequests: Array<number | null> = [];
const mockPdfRenders: Array<{ versionId: string; file: string }> = [];
let mockParams = { projectId: 'p1', versionId: 'v2' };

jest.mock('next/dynamic', () => ({
  __esModule: true,
  default: () => {
    // pdf.js cannot run in jsdom: the stub records each page the viewer is
    // asked to scroll to — the same prop change the real PdfViewer reacts to.
    const Stub = ({ file, scrollToPage }: { file: string; scrollToPage?: number | null }) => {
      const { useEffect } = jest.requireActual<typeof import('react')>('react');
      mockPdfRenders.push({ versionId: mockParams.versionId, file });
      useEffect(() => {
        mockScrollRequests.push(scrollToPage ?? null);
      }, [scrollToPage]);
      return <div data-testid="pdf-stub" data-file={file} />;
    };
    return Stub;
  },
}));
jest.mock('@/lib/services/http', () => ({ api: { get: jest.fn(), post: jest.fn() } }));
jest.mock('@/lib/hooks/useRequireAuth', () => ({
  useRequireAuth: () => ({ isAuthenticated: true }),
}));
jest.mock('next/navigation', () => ({
  useParams: () => mockParams,
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
}));
// Side panels fetch their own data and are covered by their own tests.
jest.mock('@/components/seals/SealsPanel', () => ({ SealsPanel: () => null }));
jest.mock('@/components/seals/SealActionBar', () => ({ SealActionBar: () => null }));
jest.mock('@/components/reviews/ReviewRequestPanel', () => ({ ReviewRequestPanel: () => null }));
jest.mock('@/components/certificates/CertificatePanel', () => ({ CertificatePanel: () => null }));
jest.mock('@/components/checks/ChecksPanel', () => ({ ChecksPanel: () => null }));
jest.mock('@/components/observations/ObservationsPanel', () => ({
  ObservationsPanel: () => null,
}));

const mockGet = api.get as jest.Mock;

const VERSION_DETAIL = {
  public_id: 'v2',
  number: 2,
  message: 'segunda entrega',
  is_draft: false,
  is_approved: false,
  effective_role: 'reviewer',
  sections: [
    {
      stable_key: 'objeto-del-contrato',
      heading_text: '1. OBJETO DEL CONTRATO',
      page_start: 1,
      page_end: 1,
    },
    {
      stable_key: 'obligaciones-del-contratista',
      heading_text: '3. OBLIGACIONES DEL CONTRATISTA',
      page_start: 3,
      page_end: 4,
    },
  ],
};

const REVIEW_CONTEXT = {
  my_last_sealed_version: 1,
  changed: [
    { stable_key: 'obligaciones-del-contratista', heading: '3. OBLIGACIONES DEL CONTRATISTA' },
  ],
  unchanged: [{ stable_key: 'objeto-del-contrato', heading: '1. OBJETO DEL CONTRATO' }],
};

const RESPONSES: Record<string, unknown> = {
  'versions/v2/': VERSION_DETAIL,
  'versions/v2/file/': { url: 'https://files.test/v2.pdf' },
  'versions/v2/review_context/': REVIEW_CONTEXT,
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

describe('VersionViewerPage review context (D2)', () => {
  beforeEach(() => {
    mockScrollRequests.length = 0;
    mockPdfRenders.length = 0;
    mockParams = { projectId: 'p1', versionId: 'v2' };
    useVersionStore.setState(useVersionStore.getInitialState(), true);
    useReviewStore.setState(useReviewStore.getInitialState(), true);
    useUpgradeDialogStore.setState(useUpgradeDialogStore.getInitialState(), true);
    mockGet.mockReset();
    mockGet.mockImplementation((url: string) => Promise.resolve({ data: RESPONSES[url] }));
  });

  it('[D2] scrolls the viewer to the first page of a changed section picked in the context bar', async () => {
    const user = userEvent.setup();
    render(<VersionViewerPage />);
    const changedSection = await screen.findByTestId(
      'context-changed-obligaciones-del-contratista'
    );

    await user.click(changedSection);

    await waitFor(() => expect(mockScrollRequests.at(-1)).toBe(3));
  });

  it('[D2] scrolls again when the same changed section is picked a second time', async () => {
    const user = userEvent.setup();
    render(<VersionViewerPage />);
    const changedSection = await screen.findByTestId(
      'context-changed-obligaciones-del-contratista'
    );

    await user.click(changedSection);
    await waitFor(() => expect(mockScrollRequests.at(-1)).toBe(3));
    await user.click(changedSection);

    await waitFor(() =>
      expect(mockScrollRequests.filter((page) => page === 3)).toHaveLength(2)
    );
  });

  it('[C3] removes the previous PDF as soon as the route changes', async () => {
    const metadata = pendingResponse();
    const file = pendingResponse();
    const { rerender } = render(<VersionViewerPage />);
    await waitFor(() => expect(screen.getByTestId('pdf-stub'))
      .toHaveAttribute('data-file', 'https://files.test/v2.pdf'));
    const responses: Record<string, Promise<{ data: unknown }>> = {
      'versions/v1/': metadata.promise,
      'versions/v1/file/': file.promise,
      'versions/v1/review_context/': Promise.resolve({ data: REVIEW_CONTEXT }),
    };
    mockGet.mockImplementation((url: string) => responses[url]);

    mockParams = { projectId: 'p1', versionId: 'v1' };
    rerender(<VersionViewerPage />);

    expect(screen.queryByTestId('pdf-stub')).not.toBeInTheDocument();
    await act(async () => metadata.resolve({ data: { ...VERSION_DETAIL, public_id: 'v1', number: 1 } }));
    expect(screen.getByRole('heading', { name: 'Versión v1' })).toBeInTheDocument();
    expect(screen.queryByTestId('pdf-stub')).not.toBeInTheDocument();
    await act(async () => file.resolve({ data: { url: 'https://files.test/v1.pdf' } }));
    expect(screen.getByTestId('pdf-stub')).toHaveAttribute('data-file', 'https://files.test/v1.pdf');
    expect(mockPdfRenders.filter((entry) => entry.versionId === 'v1'))
      .toEqual([{ versionId: 'v1', file: 'https://files.test/v1.pdf' }]);
  });

  it('[C3] ignores a previous route that completes after the current route', async () => {
    const oldMetadata = pendingResponse();
    const oldFile = pendingResponse();
    const currentMetadata = pendingResponse();
    const currentFile = pendingResponse();
    const responses: Record<string, Promise<{ data: unknown }>> = {
      'versions/v1/': oldMetadata.promise, 'versions/v1/file/': oldFile.promise,
      'versions/v2/': currentMetadata.promise, 'versions/v2/file/': currentFile.promise,
      'versions/v2/review_context/': Promise.resolve({ data: REVIEW_CONTEXT }),
    };
    mockGet.mockImplementation((url: string) => responses[url]);
    mockParams = { projectId: 'p1', versionId: 'v1' };
    const { rerender } = render(<VersionViewerPage />);
    mockParams = { projectId: 'p1', versionId: 'v2' };
    rerender(<VersionViewerPage />);
    await act(async () => {
      currentMetadata.resolve({ data: VERSION_DETAIL });
      currentFile.resolve({ data: { url: 'https://files.test/v2.pdf' } });
    });

    await act(async () => {
      oldMetadata.resolve({ data: { ...VERSION_DETAIL, public_id: 'v1', number: 1 } });
      oldFile.resolve({ data: { url: 'https://files.test/v1.pdf' } });
    });

    expect(screen.getByRole('heading', { name: 'Versión v2' })).toBeInTheDocument();
    expect(screen.getByTestId('pdf-stub')).toHaveAttribute('data-file', 'https://files.test/v2.pdf');
    expect(mockPdfRenders.filter((entry) => entry.file === 'https://files.test/v1.pdf')).toEqual([]);
  });

  it('[C3] retries the failed PDF without refetching its successful metadata', async () => {
    const user = userEvent.setup();
    const metadata = pendingResponse();
    const file = pendingResponse();
    const responses: Record<string, Promise<{ data: unknown }>> = {
      'versions/v2/': metadata.promise, 'versions/v2/file/': file.promise,
      'versions/v2/review_context/': Promise.resolve({ data: REVIEW_CONTEXT }),
    };
    mockGet.mockImplementation((url: string) => responses[url]);
    render(<VersionViewerPage />);
    await act(async () => file.reject({ response: { status: 503, data: { error: 'PDF temporalmente no disponible' } } }));
    await act(async () => metadata.resolve({ data: VERSION_DETAIL }));
    expect(screen.getByTestId('async-error')).toHaveTextContent('PDF temporalmente no disponible');
    expect(screen.getByRole('heading', { name: 'Versión v2' })).toBeInTheDocument();
    expect(screen.queryByTestId('pdf-stub')).not.toBeInTheDocument();
    responses['versions/v2/file/'] = Promise.resolve({ data: { url: 'https://files.test/v2.pdf' } });

    await user.click(screen.getByRole('button', { name: 'Reintentar' }));

    await waitFor(() => expect(screen.getByTestId('pdf-stub'))
      .toHaveAttribute('data-file', 'https://files.test/v2.pdf'));
    expect(screen.queryByTestId('async-error')).not.toBeInTheDocument();
    expect(mockGet.mock.calls.filter(([url]) => url === 'versions/v2/')).toHaveLength(1);
  });

  it('[C3] keeps the metadata failure visible after the PDF arrives', async () => {
    const metadata = pendingResponse();
    const file = pendingResponse();
    const responses: Record<string, Promise<{ data: unknown }>> = {
      'versions/v2/': metadata.promise, 'versions/v2/file/': file.promise,
    };
    mockGet.mockImplementation((url: string) => responses[url]);
    render(<VersionViewerPage />);
    await act(async () => metadata.reject(new Error('Versión no disponible')));

    await act(async () => file.resolve({ data: { url: 'https://files.test/v2.pdf' } }));

    expect(screen.getByTestId('async-error')).toHaveTextContent('Versión no disponible');
    expect(screen.queryByTestId('pdf-stub')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Versión v2' })).not.toBeInTheDocument();
  });
});
