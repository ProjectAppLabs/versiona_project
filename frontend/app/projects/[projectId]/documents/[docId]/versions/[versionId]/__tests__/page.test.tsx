import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import VersionViewerPage from '../page';
import { api } from '@/lib/services/http';

const mockScrollRequests: Array<number | null> = [];

jest.mock('next/dynamic', () => ({
  __esModule: true,
  default: () => {
    // pdf.js cannot run in jsdom: the stub records each page the viewer is
    // asked to scroll to — the same prop change the real PdfViewer reacts to.
    const Stub = ({ scrollToPage }: { scrollToPage?: number | null }) => {
      const { useEffect } = jest.requireActual<typeof import('react')>('react');
      useEffect(() => {
        mockScrollRequests.push(scrollToPage ?? null);
      }, [scrollToPage]);
      return <div data-testid="pdf-stub" />;
    };
    return Stub;
  },
}));
jest.mock('@/lib/services/http', () => ({ api: { get: jest.fn(), post: jest.fn() } }));
jest.mock('@/lib/hooks/useRequireAuth', () => ({
  useRequireAuth: () => ({ isAuthenticated: true }),
}));
jest.mock('next/navigation', () => ({
  useParams: () => ({ projectId: 'p1', versionId: 'v2' }),
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

describe('VersionViewerPage review context (D2)', () => {
  beforeEach(() => {
    mockScrollRequests.length = 0;
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
});
