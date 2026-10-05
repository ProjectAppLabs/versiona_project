'use client';

/**
 * Document + upload orchestration (flows C1/C2 — DP-06 two-step upload):
 * create document (when needed) → upload_intent → PUT to presigned URL with
 * progress → complete → analysis job id (tracked by jobStore).
 */

import axios from 'axios';
import { create } from 'zustand';

import { api } from '@/lib/services/http';
import type { DocumentSummary, VersionSummary } from '@/lib/types';

export type UploadPhase =
  | 'idle'
  | 'uploading'
  | 'completing'
  | 'analyzing'
  | 'done'
  | 'error';

interface UploadState {
  phase: UploadPhase;
  progress: number;
  error: string | null;
  jobId: string | null;
  version: VersionSummary | null;
}

interface DocumentState {
  upload: UploadState;
  createDocument: (projectId: string, title: string) => Promise<DocumentSummary>;
  uploadVersion: (documentId: string, file: File, message: string) => Promise<UploadState>;
  resetUpload: () => void;
}

const IDLE: UploadState = { phase: 'idle', progress: 0, error: null, jobId: null, version: null };

function extractError(err: unknown): string {
  const response = (err as {
    response?: { status?: number; headers?: Record<string, unknown> };
  })?.response;
  if (response?.status === 429) {
    const retryAfter = Number(response.headers?.['retry-after']);
    const nextStep = Number.isFinite(retryAfter) && retryAfter > 0
      ? `Espera ${Math.ceil(retryAfter)} segundos y vuelve a intentarlo.`
      : 'Vuelve a intentarlo más tarde.';
    return `Alcanzaste el límite de subidas. ${nextStep}`;
  }
  return (
    (err as { response?: { data?: { error?: string } } })?.response?.data?.error ??
    (err as Error)?.message ??
    'Error de subida'
  );
}

export const useDocumentStore = create<DocumentState>((set) => ({
  upload: IDLE,

  createDocument: async (projectId, title) => {
    const { data } = await api.post<DocumentSummary>(`projects/${projectId}/documents/`, {
      title,
    });
    return data;
  },

  uploadVersion: async (documentId, file, message) => {
    set({ upload: { ...IDLE, phase: 'uploading' } });
    try {
      const { data: intent } = await api.post(`documents/${documentId}/versions/upload_intent/`);
      await axios.put(intent.url, file, {
        headers: { 'Content-Type': 'application/pdf' },
        onUploadProgress: (event) => {
          const progress = event.total ? Math.round((event.loaded / event.total) * 100) : 0;
          set((state) => ({ upload: { ...state.upload, progress } }));
        },
      });
      set((state) => ({ upload: { ...state.upload, phase: 'completing', progress: 100 } }));
      const { data } = await api.post(`documents/${documentId}/versions/complete/`, {
        upload_id: intent.upload_id,
        message,
      });
      const next: UploadState = {
        phase: 'analyzing',
        progress: 100,
        error: null,
        jobId: data.job_id,
        version: data.version,
      };
      set({ upload: next });
      return next;
    } catch (err) {
      const next: UploadState = { ...IDLE, phase: 'error', error: extractError(err) };
      set({ upload: next });
      return next;
    }
  },

  resetUpload: () => set({ upload: IDLE }),
}));
