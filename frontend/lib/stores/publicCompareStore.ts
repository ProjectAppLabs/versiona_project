'use client';

import { create } from 'zustand';

import type { ChangeType, SectionChange } from '@/lib/compare/sync';
import { publicApi } from '@/lib/services/http';

// Client-side mirrors of the backend caps (PUBLIC_COMPARE_* settings).
export const PUBLIC_COMPARE_MAX_MB = 10;
export const PUBLIC_COMPARE_MAX_PAGES = 100;
export const PUBLIC_COMPARE_TTL_HOURS = 24;

// jobStore polling constants (docs/plan/04 §4): 2 s → ×1.5 backoff, cap 10 s.
const INITIAL_INTERVAL_MS = 2000;
const MAX_INTERVAL_MS = 10000;
const TIMEOUT_MS = 5 * 60 * 1000;

export type PublicCompareErrorKey =
  | 'missingFiles'
  | 'notPdf'
  | 'tooBig'
  | 'tooManyPages'
  | 'scannedNeedsOcr'
  | 'encrypted'
  | 'invalid'
  | 'rateLimited'
  | 'genericFailed'
  | 'expired';

const ERROR_CODE_TO_KEY: Record<string, PublicCompareErrorKey> = {
  missing_files: 'missingFiles',
  not_pdf: 'notPdf',
  too_big: 'tooBig',
  too_many_pages: 'tooManyPages',
  ocr_required: 'scannedNeedsOcr',
  encrypted_pdf: 'encrypted',
  invalid_pdf: 'invalid',
  processing_failed: 'genericFailed',
  expired: 'expired',
};

export interface PublicCompareSection extends SectionChange {
  word_diff?: Array<{ op: 'equal' | 'insert' | 'delete'; text: string }>;
}

export interface PublicCompareResultPayload {
  counts: Record<ChangeType, number>;
  summary_text: string;
  sections: PublicCompareSection[];
  meta: { page_count_a: number; page_count_b: number };
}

export interface PublicComparisonDetail {
  public_id: string;
  status: 'pending' | 'processing' | 'done' | 'failed';
  error_code: string;
  file_a_name: string;
  file_b_name: string;
  created_at: string;
  expires_at: string;
  result: PublicCompareResultPayload | null;
}

type Phase = 'idle' | 'uploading' | 'processing' | 'done' | 'error';

interface PublicCompareState {
  slotA: File | null;
  slotB: File | null;
  phase: Phase;
  progress: number;
  detail: PublicComparisonDetail | null;
  errorKey: PublicCompareErrorKey | null;
  setSlot: (slot: 'a' | 'b', file: File | null) => void;
  swap: () => void;
  clientValidate: (file: File) => PublicCompareErrorKey | null;
  submit: () => Promise<string | null>;
  load: (publicId: string, signal?: AbortSignal) => Promise<void>;
  reset: () => void;
}

function mapAxiosError(err: unknown): PublicCompareErrorKey {
  const response = (err as {
    response?: { status?: number; data?: { error_code?: string } };
  })?.response;
  if (response?.status === 429) return 'rateLimited';
  const code = response?.data?.error_code;
  return (code && ERROR_CODE_TO_KEY[code]) || 'genericFailed';
}

function waitForPoll(interval: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const finish = () => {
      clearTimeout(timer);
      signal.removeEventListener('abort', finish);
      resolve();
    };
    const timer = setTimeout(finish, interval);
    signal.addEventListener('abort', finish, { once: true });
    if (signal.aborted) finish();
  });
}

let activeLoad: AbortController | null = null;

export const usePublicCompareStore = create<PublicCompareState>((set, get) => ({
  slotA: null,
  slotB: null,
  phase: 'idle',
  progress: 0,
  detail: null,
  errorKey: null,

  setSlot: (slot, file) =>
    set(slot === 'a' ? { slotA: file, errorKey: null } : { slotB: file, errorKey: null }),

  swap: () => set((state) => ({ slotA: state.slotB, slotB: state.slotA })),

  clientValidate: (file) => {
    const isPdf =
      file.name.toLowerCase().endsWith('.pdf') || file.type === 'application/pdf';
    if (!isPdf) return 'notPdf';
    if (file.size > PUBLIC_COMPARE_MAX_MB * 1024 * 1024) return 'tooBig';
    return null;
  },

  submit: async () => {
    const { slotA, slotB, clientValidate } = get();
    if (!slotA || !slotB) {
      set({ phase: 'error', errorKey: 'missingFiles' });
      return null;
    }
    const invalid = clientValidate(slotA) ?? clientValidate(slotB);
    if (invalid) {
      set({ phase: 'error', errorKey: invalid });
      return null;
    }

    set({ phase: 'uploading', progress: 0, errorKey: null });
    const form = new FormData();
    form.append('file_a', slotA);
    form.append('file_b', slotB);
    try {
      const { data } = await publicApi.post('public/comparisons/', form, {
        onUploadProgress: (event) => {
          const total = event.total ?? slotA.size + slotB.size;
          set({ progress: Math.min(99, Math.round((event.loaded / total) * 100)) });
        },
      });
      set({ phase: 'processing', progress: 100 });
      return data.public_id as string;
    } catch (err) {
      set({ phase: 'error', errorKey: mapAxiosError(err) });
      return null;
    }
  },

  load: async (publicId, signal) => {
    activeLoad?.abort();
    const controller = new AbortController();
    activeLoad = controller;
    const cancel = () => controller.abort();
    signal?.addEventListener('abort', cancel, { once: true });
    if (signal?.aborted) cancel();
    const isCurrent = () => activeLoad === controller && !controller.signal.aborted;
    const startedAt = Date.now();
    let interval = INITIAL_INTERVAL_MS;

    try {
      if (!isCurrent()) return;
      set({ detail: null, phase: 'processing', errorKey: null });
      while (isCurrent()) {
        const { data } = await publicApi.get<PublicComparisonDetail>(
          `public/comparisons/${publicId}/`,
          { signal: controller.signal }
        );
        // Aborted transports can still settle. An older load never owns the
        // visible result or another polling request after it is superseded.
        if (!isCurrent()) return;
        if (data.status === 'done') {
          set({ detail: data, phase: 'done', errorKey: null });
          return;
        }
        if (data.status === 'failed') {
          set({
            detail: data,
            phase: 'error',
            errorKey: ERROR_CODE_TO_KEY[data.error_code] ?? 'genericFailed',
          });
          return;
        }
        if (Date.now() - startedAt > TIMEOUT_MS) {
          set({ phase: 'error', errorKey: 'genericFailed' });
          return;
        }
        set({ detail: data, phase: 'processing' });
        await waitForPoll(interval, controller.signal);
        interval = Math.min(interval * 1.5, MAX_INTERVAL_MS);
      }
    } catch (err) {
      if (isCurrent()) set({ phase: 'error', errorKey: mapAxiosError(err) });
    } finally {
      signal?.removeEventListener('abort', cancel);
      if (activeLoad === controller) activeLoad = null;
    }
  },

  reset: () => {
    activeLoad?.abort();
    activeLoad = null;
    set({
      slotA: null,
      slotB: null,
      phase: 'idle',
      progress: 0,
      detail: null,
      errorKey: null,
    });
  },
}));
