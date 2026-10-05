import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ObservationsPanel } from '../ObservationsPanel';
import type { ObservationAnchorRow, ObservationReplyRow, ObservationRow } from '../../../lib/types/observations';

const store = {
  versionId: 'v2', statusFilter: 'active', generation: 1, items: [] as ObservationRow[], nextCursor: null as string | null,
  isLoading: false, isSubmitting: false, error: null as string | null, loadError: null as string | null,
  replies: {} as Record<string, { items: ObservationReplyRow[]; nextCursor: string | null; isLoaded: boolean; isLoading: boolean; error: string | null }>,
  anchors: {} as Record<string, { items: ObservationAnchorRow[]; nextCursor: string | null; isLoaded: boolean; isLoading: boolean; error: string | null }>,
  contents: {} as Record<string, { content: string; nextOffset: number | null; eof: boolean; isLoaded: boolean; isLoading: boolean; error: string | null }>,
  mutations: {} as Record<string, boolean>,
  fetch: jest.fn(), reset: jest.fn(), loadMore: jest.fn(), retryLoad: jest.fn(), create: jest.fn(), reply: jest.fn(),
  setStatus: jest.fn(), loadReplies: jest.fn(), loadAnchors: jest.fn(), loadContent: jest.fn(),
};

jest.mock('../../../lib/stores/observationStore', () => ({
  useObservationStore: Object.assign(
    (selector: (s: Record<string, unknown>) => unknown) =>
      selector(store),
    { getState: () => store }
  ),
}));

jest.mock('next/navigation', () => ({
  usePathname: () => '/documents/document-1/versions/v2',
  useSearchParams: () => new URLSearchParams(),
}));

const currentAnchor = (over: Partial<ObservationAnchorRow> = {}): ObservationAnchorRow => ({
  version_public_id: 'v2', version_is_trashed: false, version_number: 2, page: 1,
  method: 'exact', text_snippet: 'Multa', quads_length: 40,
  quads_content_url: '/api/observations/o1/anchors/2/content/', ...over,
});

const observation = (over: Partial<ObservationRow> = {}): ObservationRow => ({
  public_id: 'o1',
  status: 'open',
  author_email: 'reviewer@versiona.test',
  section_key: 'obligaciones-del-contratista',
  section_heading: '3. OBLIGACIONES DEL CONTRATISTA',
  created_on: 1,
  resolved_in: null,
  reply_count: 0,
  current_anchor: currentAnchor(),
  body_preview: 'La multa parece baja.',
  body_length: 21,
  body_content_url: '/api/observations/o1/content/',
  created_at: '2026-07-12T10:00:00Z',
  ...over,
});

const baseProps = {
  versionId: 'v2',
  versionNumber: 2,
  sections: [{ stable_key: 's1', heading_text: '1. OBJETO', level: 1, order_index: 0,
               page_start: 1, page_end: 1, char_count: 10, bboxes: [], body_hash: 'h1' }],
  canCreate: true,
  canReply: true,
  currentUserEmail: 'reviewer@versiona.test',
};

describe('ObservationsPanel (D3)', () => {
  beforeEach(() => {
    store.versionId = 'v2';
    store.statusFilter = 'active';
    store.generation = 1;
    store.items = [];
    store.nextCursor = null;
    store.isLoading = false;
    store.isSubmitting = false;
    store.error = null;
    store.loadError = null;
    store.replies = {};
    store.anchors = {};
    store.contents = {};
    store.mutations = {};
    Object.values(store).forEach((value) => { if (jest.isMockFunction(value)) value.mockReset(); });
  });

  it('[D3-Display] renders the guided empty state for the active version', () => {
    // Fails if an empty, loaded observation panel loses the instruction that tells reviewers how to proceed.
    render(<ObservationsPanel {...baseProps} />);

    expect(screen.getByText('Sin observaciones')).toBeInTheDocument();
    expect(screen.getByText('Un revisor puede anclar observaciones a las secciones del documento.')).toBeInTheDocument();
  });

  it('[D3-Display] shows the current version anchor health next to an open thread', () => {
    // Fails if the current anchor metadata is no longer rendered with the thread it describes.
    store.items = [observation()];

    render(<ObservationsPanel {...baseProps} />);

    expect(screen.getByTestId('observation-o1')).toHaveAttribute('data-status', 'open');
    expect(screen.getByTestId('observation-anchor-o1')).toHaveTextContent('3. OBLIGACIONES DEL CONTRATISTA — Ancla exacta');
  });

  it('[D3-P02] does not offer observation creation to a non-reviewer', () => {
    // Fails if a read-only member receives a control whose server request will be rejected.
    render(<ObservationsPanel {...baseProps} canCreate={false} />);

    expect(screen.getByText('Sin observaciones')).toBeInTheDocument();
    expect(screen.queryByTestId('add-observation')).not.toBeInTheDocument();
  });

  it('[D3-P03] hides resolve from a reviewer who did not open an answered thread', () => {
    // Fails if a reviewer receives a Resolve button for a thread that the server reserves for its author or an admin.
    store.items = [observation({ status: 'answered', author_email: 'other@versiona.test' })];

    render(<ObservationsPanel {...baseProps} canResolveAny={false} />);

    expect(screen.getByTestId('observation-o1')).toHaveAttribute('data-status', 'answered');
    expect(screen.queryByTestId('resolve-o1')).not.toBeInTheDocument();
  });

  it('[D3-P04] offers resolve to an admin on an answered thread from another reviewer', () => {
    // Fails if an admin loses the client affordance for the server-authorized resolution transition.
    store.items = [observation({ status: 'answered', author_email: 'other@versiona.test' })];

    render(<ObservationsPanel {...baseProps} canResolveAny />);

    expect(screen.getByTestId('resolve-o1')).toHaveTextContent('Marcar resuelta');
  });

  it('[D3-Display] offers child controls and marks a trashed historical version as unavailable', async () => {
    // Fails if the panel hides paged children or offers a link to a version that returns 404.
    store.items = [observation({ reply_count: 2 })];
    store.replies = { o1: { items: [], nextCursor: 'older-replies', isLoaded: true, isLoading: false, error: null } };
    store.anchors = {
      o1: {
        items: [currentAnchor({ version_number: 1, version_public_id: 'deleted-v1', version_is_trashed: true })],
        nextCursor: null, isLoaded: true, isLoading: false, error: null,
      },
    };

    render(<ObservationsPanel {...baseProps} />);
    await userEvent.click(screen.getByTestId('observation-replies-o1'));
    await userEvent.click(screen.getByTestId('observation-history-o1'));

    expect(screen.getByTestId('observation-replies-more-o1')).toHaveTextContent('Cargar respuestas anteriores');
    expect(screen.getByTestId('observation-history-list-o1')).toHaveTextContent('Esta versión está en la papelera.');
    expect(screen.queryByTestId('observation-history-version-o1-1')).not.toBeInTheDocument();
  });

  it('[D3-Display] waits for a complete anchor JSON before highlighting it', async () => {
    // Fails if partial JSON is parsed or a selection is highlighted before its final chunk arrives.
    const onSelectAnchor = jest.fn();
    const url = '/api/observations/o1/anchors/2/content/';
    store.items = [observation()];
    store.loadContent.mockImplementationOnce(async () => {
      store.contents[url] = { content: '[{"page":2,', nextOffset: 12, eof: false, isLoaded: true, isLoading: false, error: null };
    }).mockImplementationOnce(async () => {
      store.contents[url] = { content: '[{"page":2,"x0":0.1,"y0":0.2,"x1":0.9,"y1":0.8}]', nextOffset: 58, eof: true, isLoaded: true, isLoading: false, error: null };
    });

    render(<ObservationsPanel {...baseProps} onSelectAnchor={onSelectAnchor} />);
    await userEvent.click(screen.getByTestId('observation-anchor-o1'));

    expect(onSelectAnchor).not.toHaveBeenCalled();
    expect(screen.getByTestId('observation-anchor-more-o1')).toHaveTextContent('Seguir cargando ancla');

    await userEvent.click(screen.getByTestId('observation-anchor-more-o1'));
    await waitFor(() => expect(onSelectAnchor).toHaveBeenCalledWith([
      { page: 2, x0: 0.1, y0: 0.2, x1: 0.9, y1: 0.8 },
    ]));
  });

  it('[D3-Display] shows the reply posted locally and retains an explicit older-page control', async () => {
    // Fails if posting a reply opens an empty nested panel or hides the remaining replies page.
    store.items = [observation({ reply_count: 2, status: 'answered' })];
    store.replies = {
      o1: {
        items: [{ public_id: 'new-reply', author_email: 'editor@versiona.test', status_change: 'answered',
          created_at: '2026-10-02T12:00:00Z', body_preview: 'Ya quedó.', body_length: 9,
          body_content_url: '/api/observations/o1/replies/new-reply/content/' }],
        nextCursor: null, isLoaded: false, isLoading: false, error: null,
      },
    };
    store.reply.mockResolvedValue(true);

    render(<ObservationsPanel {...baseProps} />);
    await userEvent.type(screen.getByTestId('reply-input-o1'), 'Ya quedó.');
    await userEvent.click(screen.getByTestId('reply-send-o1'));

    expect(store.reply).toHaveBeenCalledWith('v2', 'o1', 'Ya quedó.');
    expect(screen.getByTestId('observation-reply-new-reply')).toHaveTextContent('Ya quedó.');
    expect(screen.getByTestId('observation-replies-more-o1')).toHaveTextContent('Cargar respuestas anteriores');
  });
});
