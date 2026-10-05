import { api } from '../../services/http';
import type { ObservationAnchorRow, ObservationReplyRow, ObservationRow } from '../../types/observations';
import { useObservationStore } from '../observationStore';

jest.mock('../../services/http', () => ({ api: { get: jest.fn(), post: jest.fn() } }));

const mockGet = api.get as jest.Mock;
const mockPost = api.post as jest.Mock;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const anchor = (over: Partial<ObservationAnchorRow> = {}): ObservationAnchorRow => ({
  version_public_id: 'version-1', version_is_trashed: false, version_number: 1, page: 1,
  method: 'exact', text_snippet: 'Multa', quads_length: 12,
  quads_content_url: '/api/observations/o1/anchors/1/content/', ...over,
});

const row = (publicId: string, over: Partial<ObservationRow> = {}): ObservationRow => ({
  public_id: publicId, status: 'open', author_email: 'reviewer@versiona.test', section_key: 'multas',
  section_heading: 'Multas', created_on: 1, resolved_in: null, reply_count: 0, current_anchor: anchor(),
  body_preview: 'La multa parece baja.', body_length: 21,
  body_content_url: `/api/observations/${publicId}/content/`, created_at: '2026-10-02T10:00:00Z', ...over,
});

const replyRow = (publicId: string): ObservationReplyRow => ({
  public_id: publicId, author_email: 'editor@versiona.test', status_change: 'answered',
  created_at: '2026-10-02T10:05:00Z', body_preview: 'Corregido.', body_length: 10,
  body_content_url: `/api/observations/o1/replies/${publicId}/content/`,
});

describe('observationStore', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
    useObservationStore.getState().reset();
  });

  it('[D3-Failure] keeps the first page while retrying a failed next page', async () => {
    // Fails if a failed "load more" clears visible threads or duplicates an overlapping row.
    const firstPage = Array.from({ length: 25 }, (_, index) => row(`o${index + 1}`));
    const nextPage = deferred<{ data: { results: ObservationRow[]; next_cursor: string | null } }>();
    mockGet.mockResolvedValueOnce({ data: { results: firstPage, next_cursor: 'page-2' } });
    mockGet.mockImplementationOnce(() => nextPage.promise);

    await useObservationStore.getState().fetch('version-1', 'all');
    const firstAttempt = useObservationStore.getState().loadMore();
    nextPage.reject({ response: { data: { error: 'Sin red' } } });
    await firstAttempt;

    expect(useObservationStore.getState().items.map((item) => item.public_id)).toEqual(
      Array.from({ length: 25 }, (_, index) => `o${index + 1}`)
    );
    expect(useObservationStore.getState().failedLoad).toBe('more');

    mockGet.mockResolvedValueOnce({ data: { results: [row('o25'), row('o26')], next_cursor: null } });
    await useObservationStore.getState().retryLoad();

    expect(useObservationStore.getState().items.map((item) => item.public_id)).toEqual(
      Array.from({ length: 26 }, (_, index) => `o${index + 1}`)
    );
    expect(useObservationStore.getState().loadError).toBeNull();
  });

  it('[D3-Failure] ignores late thread children and reply mutations from the previous version', async () => {
    // Fails if an aborted generation leaks its thread, child text, or mutation into another version.
    const oldReplies = deferred<{ data: { results: ObservationReplyRow[]; next_cursor: string | null } }>();
    const oldAnchors = deferred<{ data: { results: ObservationAnchorRow[]; next_cursor: string | null } }>();
    const oldContent = deferred<{ data: { content: string; offset: number; next_offset: number; eof: boolean } }>();
    const oldReply = deferred<{ data: { reply: ObservationReplyRow; status: 'answered' } }>();
    mockGet.mockImplementation((url: string) => {
      if (url === 'versions/version-old/observations/') return Promise.resolve({ data: { results: [row('old')], next_cursor: null } });
      if (url === 'observations/old/replies/') return oldReplies.promise;
      if (url === 'observations/old/anchors/') return oldAnchors.promise;
      if (url === 'observations/old/content/') return oldContent.promise;
      if (url === 'versions/version-new/observations/') return Promise.resolve({ data: { results: [row('new')], next_cursor: null } });
      throw new Error(`unexpected GET ${url}`);
    });
    mockPost.mockImplementation(() => oldReply.promise);

    await useObservationStore.getState().fetch('version-old', 'all');
    const pendingReplies = useObservationStore.getState().loadReplies('old');
    const pendingAnchors = useObservationStore.getState().loadAnchors('old');
    const pendingContent = useObservationStore.getState().loadContent('/api/observations/old/content/');
    const pendingMutation = useObservationStore.getState().reply('version-old', 'old', 'Arreglado');
    await useObservationStore.getState().fetch('version-new', 'all');

    oldReplies.resolve({ data: { results: [replyRow('old-reply')], next_cursor: null } });
    oldAnchors.resolve({ data: { results: [anchor()], next_cursor: null } });
    oldContent.resolve({ data: { content: 'viejo', offset: 0, next_offset: 5, eof: true } });
    oldReply.resolve({ data: { reply: replyRow('old-reply'), status: 'answered' } });
    await Promise.all([pendingReplies, pendingAnchors, pendingContent, pendingMutation]);

    expect(useObservationStore.getState().versionId).toBe('version-new');
    expect(useObservationStore.getState().items.map((item) => item.public_id)).toEqual(['new']);
    expect(useObservationStore.getState().replies).toEqual({});
    expect(useObservationStore.getState().anchors).toEqual({});
    expect(useObservationStore.getState().contents).toEqual({});
    expect(useObservationStore.getState().mutations).toEqual({});
  });

  it('[D3-Success] continues Unicode content at the server offset and stops at EOF', async () => {
    // Fails if the client derives an offset from JavaScript string length instead of the server cursor.
    mockGet.mockResolvedValueOnce({ data: { results: [row('o1')], next_cursor: null } });
    mockGet.mockResolvedValueOnce({ data: { content: 'á🙂', offset: 0, next_offset: 77, eof: false } });
    mockGet.mockResolvedValueOnce({ data: { content: ' final', offset: 77, next_offset: 83, eof: true } });

    await useObservationStore.getState().fetch('version-1', 'all');
    await useObservationStore.getState().loadContent('/api/observations/o1/content/');
    await useObservationStore.getState().loadContent('/api/observations/o1/content/');
    await useObservationStore.getState().loadContent('/api/observations/o1/content/');

    const contentCalls = mockGet.mock.calls.filter(([url]) => url === 'observations/o1/content/');
    expect(contentCalls.map(([, options]) => options.params.offset)).toEqual([0, 77]);
    expect(useObservationStore.getState().contents['/api/observations/o1/content/']).toMatchObject({
      content: 'á🙂 final', nextOffset: 83, eof: true,
    });
  });

  it('[D3-Display] adds a focused history thread only once outside the first page', async () => {
    // Fails if a history URL points at a thread that the first cursor page never inserts.
    mockGet.mockResolvedValueOnce({ data: { results: [row('first')], next_cursor: 'page-2' } });
    mockGet.mockResolvedValueOnce({ data: row('focused', { status: 'resolved' }) });

    await useObservationStore.getState().fetch('version-2', 'all', 'focused');

    expect(useObservationStore.getState().items.map((item) => item.public_id)).toEqual(['focused', 'first']);
    expect(useObservationStore.getState().statusFilter).toBe('all');
    expect(mockGet).toHaveBeenLastCalledWith('observations/focused/', expect.objectContaining({
      params: { version: 'version-2' },
    }));
  });

  it('[D3-Display] keeps a posted reply while an older replies page resolves', async () => {
    // Fails if an in-flight older page overwrites the reply that was just posted locally.
    const olderReplies = deferred<{ data: { results: ObservationReplyRow[]; next_cursor: string | null } }>();
    mockGet.mockResolvedValueOnce({ data: { results: [row('o1', { reply_count: 1 })], next_cursor: null } });
    mockGet.mockImplementationOnce(() => olderReplies.promise);
    mockPost.mockResolvedValueOnce({ data: { reply: replyRow('new-reply'), status: 'answered' } });

    await useObservationStore.getState().fetch('version-1', 'all');
    const loadingOlder = useObservationStore.getState().loadReplies('o1');
    await useObservationStore.getState().reply('version-1', 'o1', 'Nueva respuesta');
    olderReplies.resolve({ data: { results: [replyRow('old-reply')], next_cursor: 'older' } });
    await loadingOlder;

    expect(useObservationStore.getState().replies.o1.items.map((item) => item.public_id)).toEqual(['new-reply', 'old-reply']);
    expect(useObservationStore.getState().replies.o1.nextCursor).toBe('older');
    expect(useObservationStore.getState().items[0].reply_count).toBe(2);
  });
});
