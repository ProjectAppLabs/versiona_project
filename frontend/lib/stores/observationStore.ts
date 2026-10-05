'use client';

import { create } from 'zustand';

import { api } from '@/lib/services/http';
import type {
  LoadedObservationContent,
  LoadedObservationPage,
  ObservationAnchorRow,
  ObservationContentChunk,
  ObservationFilter,
  ObservationPage,
  ObservationReplyRow,
  ObservationRow,
  ObservationStatus,
} from '@/lib/types/observations';

export type { ObservationAnchorRow, ObservationReplyRow, ObservationRow } from '@/lib/types/observations';

interface ObservationState {
  versionId: string | null;
  statusFilter: ObservationFilter;
  generation: number;
  items: ObservationRow[];
  nextCursor: string | null;
  isLoading: boolean;
  isSubmitting: boolean;
  error: string | null;
  loadError: string | null;
  failedLoad: 'first' | 'more' | 'focused' | null;
  focusedObservationId: string | null;
  replies: Record<string, LoadedObservationPage<ObservationReplyRow>>;
  anchors: Record<string, LoadedObservationPage<ObservationAnchorRow>>;
  contents: Record<string, LoadedObservationContent>;
  mutations: Record<string, boolean>;
  updatedSummaries: Record<string, ObservationRow>;
  reset: () => void;
  retryLoad: () => Promise<void>;
  fetchFocused: (observationId: string) => Promise<void>;
  fetch: (versionId: string, status?: ObservationFilter, focusedObservationId?: string | null) => Promise<void>;
  loadMore: () => Promise<void>;
  loadReplies: (observationId: string) => Promise<void>;
  loadAnchors: (observationId: string) => Promise<void>;
  loadContent: (url: string) => Promise<void>;
  create: (
    versionId: string,
    payload: { body: string; sectionKey?: string }
  ) => Promise<boolean>;
  reply: (versionId: string, observationId: string, body: string) => Promise<boolean>;
  setStatus: (versionId: string, observationId: string, status: ObservationStatus) => Promise<boolean>;
}

const requests = new Set<AbortController>();

function controllerForRequest() {
  const controller = new AbortController();
  requests.add(controller);
  return controller;
}

function cancelRequests() {
  requests.forEach((controller) => controller.abort());
  requests.clear();
}

function messageOf(err: unknown): string {
  return (
    (err as { response?: { data?: { error?: string } } })?.response?.data?.error ??
    (err as Error)?.message ??
    'Algo salió mal'
  );
}

function emptyPage<T>(): LoadedObservationPage<T> {
  return { items: [], nextCursor: null, isLoaded: false, isLoading: false, error: null };
}

function emptyContent(): LoadedObservationContent {
  return { content: '', nextOffset: 0, eof: false, isLoaded: false, isLoading: false, error: null };
}

function mergeRows<T>(old: T[], added: T[], keyOf: (row: T) => string | number): T[] {
  const rows = new Map(old.map((row) => [keyOf(row), row]));
  added.forEach((row) => { if (!rows.has(keyOf(row))) rows.set(keyOf(row), row); });
  return [...rows.values()];
}

function belongsToFilter(row: ObservationRow, filter: ObservationFilter) {
  return filter === 'all' || (filter === 'active' ? row.status !== 'resolved' : row.status === filter);
}

function contentPath(url: string): string {
  // Server-generated root-relative URLs belong to the authenticated API client.
  return url.replace(/^\/api\//, '');
}

export const useObservationStore = create<ObservationState>((set, get) => {
  const stillCurrent = (generation: number) => get().generation === generation;

  const updateSummary = (row: ObservationRow) => {
    set((state) => ({
      items: belongsToFilter(row, state.statusFilter)
        ? state.items.map((item) => item.public_id === row.public_id ? row : item)
        : state.items.filter((item) => item.public_id !== row.public_id),
      updatedSummaries: { ...state.updatedSummaries, [row.public_id]: row },
    }));
  };

  async function loadChildPage<T>(
    url: string,
    currentPage: LoadedObservationPage<T>,
    save: (page: LoadedObservationPage<T>) => void,
    keyOf: (row: T) => string | number,
    readCurrent: () => LoadedObservationPage<T> | undefined
  ) {
    if (!get().versionId || currentPage.isLoading || (currentPage.isLoaded && !currentPage.nextCursor)) return;
    const generation = get().generation;
    const controller = controllerForRequest();
    save({ ...currentPage, isLoading: true, error: null });
    try {
      const { data } = await api.get<ObservationPage<T>>(url, {
        params: currentPage.nextCursor ? { cursor: currentPage.nextCursor } : undefined,
        signal: controller.signal,
      });
      if (stillCurrent(generation)) {
        // A reply may have been posted while its page was in flight.
        const latest = readCurrent();
        save({
          items: mergeRows(latest?.items ?? currentPage.items, data.results, keyOf),
          nextCursor: data.next_cursor,
          isLoaded: true,
          isLoading: false,
          error: null,
        });
      }
    } catch (err) {
      if (stillCurrent(generation)) {
        const latest = readCurrent();
        save({ ...(latest ?? currentPage), isLoading: false, error: messageOf(err) });
      }
    } finally {
      requests.delete(controller);
    }
  }

  return {
    versionId: null,
    statusFilter: 'active',
    generation: 0,
    items: [],
    nextCursor: null,
    isLoading: false,
    isSubmitting: false,
    error: null,
    loadError: null,
    failedLoad: null,
    focusedObservationId: null,
    replies: {},
    anchors: {},
    contents: {},
    mutations: {},
    updatedSummaries: {},

    reset: () => {
      cancelRequests();
      set((state) => ({
        generation: state.generation + 1, versionId: null, items: [], nextCursor: null,
        isLoading: false, isSubmitting: false, error: null,
        loadError: null, failedLoad: null, focusedObservationId: null,
        replies: {}, anchors: {}, contents: {}, mutations: {}, updatedSummaries: {},
      }));
    },

    retryLoad: async () => {
      const { versionId, statusFilter, focusedObservationId, failedLoad } = get();
      if (!versionId || get().isLoading) return;
      if (failedLoad === 'more') await get().loadMore();
      else if (failedLoad === 'focused' && focusedObservationId) await get().fetchFocused(focusedObservationId);
      else if (failedLoad === 'first') await get().fetch(versionId, statusFilter, focusedObservationId);
    },

    fetchFocused: async (observationId) => {
      const { versionId, generation } = get();
      if (!versionId) return;
      const controller = controllerForRequest();
      set({ isLoading: true, error: null, loadError: null, failedLoad: null });
      try {
        const { data } = await api.get<ObservationRow>(`observations/${encodeURIComponent(observationId)}/`, {
          params: { version: versionId }, signal: controller.signal,
        });
        if (stillCurrent(generation)) set((state) => {
          const summary = state.updatedSummaries[data.public_id] ?? data;
          return {
            items: belongsToFilter(summary, state.statusFilter)
              ? mergeRows([summary], state.items, (item) => item.public_id)
              : state.items,
            isLoading: false,
          };
        });
      } catch (err) {
        if (stillCurrent(generation)) set({
          isLoading: false, error: messageOf(err), loadError: messageOf(err), failedLoad: 'focused',
        });
      } finally {
        requests.delete(controller);
      }
    },

    fetch: async (versionId, statusFilter = 'active', focusedObservationId) => {
      cancelRequests();
      const generation = get().generation + 1;
      set({
        versionId, statusFilter, generation, items: [], nextCursor: null,
        isLoading: true, isSubmitting: false, error: null,
        loadError: null, failedLoad: null, focusedObservationId: focusedObservationId ?? null,
        replies: {}, anchors: {}, contents: {}, mutations: {}, updatedSummaries: {},
      });
      const controller = controllerForRequest();
      try {
        const { data } = await api.get<ObservationPage<ObservationRow>>(`versions/${versionId}/observations/`, {
          params: { status: statusFilter },
          signal: controller.signal,
        });
        if (!stillCurrent(generation)) return;
        set({ items: data.results, nextCursor: data.next_cursor });
        // A history link keeps its thread reachable even beyond the first page.
        if (focusedObservationId && !data.results.some((item) => item.public_id === focusedObservationId)) {
          await get().fetchFocused(focusedObservationId);
        }
        if (stillCurrent(generation)) set({ isLoading: false });
      } catch (err) {
        if (stillCurrent(generation)) set({
          isLoading: false, error: messageOf(err), loadError: messageOf(err), failedLoad: 'first',
        });
      } finally {
        requests.delete(controller);
      }
    },

    loadMore: async () => {
      const { versionId, statusFilter, generation, nextCursor, isLoading } = get();
      if (!versionId || !nextCursor || isLoading) return;
      const controller = controllerForRequest();
      set({ isLoading: true, error: null, loadError: null, failedLoad: null });
      try {
        const { data } = await api.get<ObservationPage<ObservationRow>>(`versions/${versionId}/observations/`, {
          params: { status: statusFilter, cursor: nextCursor },
          signal: controller.signal,
        });
        if (stillCurrent(generation)) set((state) => ({
          items: mergeRows(state.items, data.results.map((item) => state.updatedSummaries[item.public_id] ?? item), (item) => item.public_id)
            .filter((item) => belongsToFilter(item, state.statusFilter)),
          nextCursor: data.next_cursor,
          isLoading: false,
        }));
      } catch (err) {
        if (stillCurrent(generation)) set({
          isLoading: false, error: messageOf(err), loadError: messageOf(err), failedLoad: 'more',
        });
      } finally {
        requests.delete(controller);
      }
    },

    loadReplies: async (observationId) => loadChildPage(
      `observations/${observationId}/replies/`,
      get().replies[observationId] ?? emptyPage<ObservationReplyRow>(),
      (page) => set((state) => ({ replies: { ...state.replies, [observationId]: page } })),
      (row) => row.public_id,
      () => get().replies[observationId]
    ),

    loadAnchors: async (observationId) => loadChildPage(
      `observations/${observationId}/anchors/`,
      get().anchors[observationId] ?? emptyPage<ObservationAnchorRow>(),
      (page) => set((state) => ({ anchors: { ...state.anchors, [observationId]: page } })),
      (row) => row.version_number,
      () => get().anchors[observationId]
    ),

    loadContent: async (url) => {
      const { generation, versionId } = get();
      const content = get().contents[url] ?? emptyContent();
      if (!versionId || content.isLoading || content.eof) return;
      const offset = content.nextOffset ?? 0;
      const save = (value: LoadedObservationContent) => set((state) => ({
        contents: { ...state.contents, [url]: value },
      }));
      const controller = controllerForRequest();
      save({ ...content, isLoading: true, error: null });
      try {
        const { data } = await api.get<ObservationContentChunk>(contentPath(url), {
          params: { offset }, signal: controller.signal,
        });
        if (stillCurrent(generation)) {
          if (data.offset !== offset || (!data.eof && (data.next_offset === null || data.next_offset <= offset))) {
            throw new Error('No se pudo continuar la carga del contenido.');
          }
          save({
            content: content.content + data.content,
            nextOffset: data.next_offset,
            eof: data.eof,
            isLoaded: true,
            isLoading: false,
            error: null,
          });
        }
      } catch (err) {
        if (stillCurrent(generation)) save({ ...content, isLoading: false, error: messageOf(err) });
      } finally {
        requests.delete(controller);
      }
    },

    create: async (versionId, { body, sectionKey }) => {
      const { generation, isSubmitting } = get();
      if (get().versionId !== versionId || isSubmitting) return false;
      const controller = controllerForRequest();
      set({ isSubmitting: true, error: null });
      try {
        const { data } = await api.post<ObservationRow>(`versions/${versionId}/observations/`, {
          body, section_key: sectionKey ?? '',
        }, { signal: controller.signal });
        if (!stillCurrent(generation)) return false;
        set((state) => ({
          items: belongsToFilter(data, state.statusFilter)
            ? mergeRows([data], state.items, (item) => item.public_id)
            : state.items,
          isSubmitting: false,
        }));
        return true;
      } catch (err) {
        if (stillCurrent(generation)) set({ isSubmitting: false, error: messageOf(err) });
        return false;
      } finally {
        requests.delete(controller);
      }
    },

    reply: async (versionId, observationId, body) => {
      const { generation } = get();
      if (get().versionId !== versionId || get().mutations[observationId]) return false;
      const controller = controllerForRequest();
      set((state) => ({ mutations: { ...state.mutations, [observationId]: true }, error: null }));
      try {
        const { data } = await api.post<{ reply: ObservationReplyRow; status: ObservationStatus }>(
          `observations/${observationId}/replies/`, { body }, { signal: controller.signal }
        );
        if (!stillCurrent(generation)) return false;
        set((state) => {
          const page = state.replies[observationId] ?? emptyPage<ObservationReplyRow>();
          const previous = state.items.find((item) => item.public_id === observationId);
          const summary = previous ? { ...previous, status: data.status, reply_count: previous.reply_count + 1 } : undefined;
          return {
            items: state.items.map((item) => item.public_id === observationId
              ? summary ?? item
              : item).filter((item) => belongsToFilter(item, state.statusFilter)),
            updatedSummaries: summary ? { ...state.updatedSummaries, [observationId]: summary } : state.updatedSummaries,
            replies: {
              ...state.replies,
              [observationId]: { ...page, items: mergeRows([data.reply], page.items, (row) => row.public_id) },
            },
            mutations: { ...state.mutations, [observationId]: false },
          };
        });
        return true;
      } catch (err) {
        if (stillCurrent(generation)) set((state) => ({
          error: messageOf(err), mutations: { ...state.mutations, [observationId]: false },
        }));
        return false;
      } finally {
        requests.delete(controller);
      }
    },

    setStatus: async (versionId, observationId, status) => {
      const { generation } = get();
      if (get().versionId !== versionId || get().mutations[observationId]) return false;
      const controller = controllerForRequest();
      set((state) => ({ mutations: { ...state.mutations, [observationId]: true }, error: null }));
      try {
        const { data } = await api.post<ObservationRow>(
          `observations/${observationId}/status/`, { status },
          { params: { version: versionId }, signal: controller.signal }
        );
        if (!stillCurrent(generation)) return false;
        updateSummary(data);
        set((state) => ({ mutations: { ...state.mutations, [observationId]: false } }));
        return true;
      } catch (err) {
        if (stillCurrent(generation)) set((state) => ({
          error: messageOf(err), mutations: { ...state.mutations, [observationId]: false },
        }));
        return false;
      } finally {
        requests.delete(controller);
      }
    },
  };
});
