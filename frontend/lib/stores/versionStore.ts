'use client';

import { create } from 'zustand';

import { api } from '@/lib/services/http';
import { maybeShowUpgradeDialog } from '@/lib/stores/upgradeDialogStore';
import type { VersionDetail } from '@/lib/types';

interface VersionState {
  detail: VersionDetail | null;
  fileUrl: string | null;
  detailVersionId: string | null;
  fileVersionId: string | null;
  isLoading: boolean;
  isFileLoading: boolean;
  detailError: string | null;
  fileError: string | null;
  error: string | null;
  fetchDetail: (versionId: string) => Promise<void>;
  fetchFileUrl: (versionId: string) => Promise<string | null>;
  downloadUrl: (versionId: string) => Promise<string | null>;
  editMessage: (versionId: string, message: string) => Promise<boolean>;
  trashVersion: (versionId: string) => Promise<boolean>;
  restoreVersion: (versionId: string) => Promise<boolean>;
}

function extractError(err: unknown): string {
  return (
    (err as { response?: { data?: { error?: string } } })?.response?.data?.error ??
    (err as Error)?.message ??
    'Error'
  );
}

export const useVersionStore = create<VersionState>((set, get) => {
  let detailGeneration = 0;
  let fileGeneration = 0;
  let navigationGeneration = 0;
  // Only pending request identities, never cached remote data. Two comparison
  // sides keep independent results even though the viewer holds one active PDF.
  const latestFileAttemptByVersion = new Map<string, symbol>();

  return {
    detail: null,
    fileUrl: null,
    detailVersionId: null,
    fileVersionId: null,
    isLoading: false,
    isFileLoading: false,
    detailError: null,
    fileError: null,
    error: null,

    fetchDetail: async (versionId) => {
      const generation = ++detailGeneration;
      if (get().detailVersionId !== versionId) {
        navigationGeneration += 1;
        fileGeneration += 1;
        latestFileAttemptByVersion.clear();
        set({
          detailVersionId: versionId, detail: null, detailError: null,
          fileVersionId: null, fileUrl: null, fileError: null,
          isLoading: true, isFileLoading: false, error: null,
        });
      } else {
        set({ isLoading: true, detailError: null, error: null });
      }
      const navigation = navigationGeneration;
      try {
        const { data } = await api.get<VersionDetail>(`versions/${versionId}/`);
        if (generation !== detailGeneration || navigation !== navigationGeneration) return;
        set({ detail: data, isLoading: false });
      } catch (err) {
        if (generation !== detailGeneration || navigation !== navigationGeneration) return;
        // Metadata failure removes the authority to display its pending PDF.
        fileGeneration += 1;
        latestFileAttemptByVersion.delete(versionId);
        const message = extractError(err);
        set({
          detail: null, detailError: message, isLoading: false, error: message,
          fileVersionId: null, fileUrl: null, fileError: null, isFileLoading: false,
        });
      }
    },

    fetchFileUrl: async (versionId) => {
      const generation = ++fileGeneration;
      const navigation = navigationGeneration;
      const attempt = Symbol();
      latestFileAttemptByVersion.set(versionId, attempt);
      set({
        fileVersionId: versionId, fileUrl: null, fileError: null,
        isFileLoading: true, error: null,
      });
      try {
        const { data } = await api.get(`versions/${versionId}/file/`);
        if (generation === fileGeneration && navigation === navigationGeneration
          && latestFileAttemptByVersion.get(versionId) === attempt) {
          set({ fileUrl: data.url, isFileLoading: false });
        }
        // CompareView consumes each promise's URL, not the shared viewer state.
        return data.url as string;
      } catch (err) {
        const currentAttempt = latestFileAttemptByVersion.get(versionId) === attempt
          && navigation === navigationGeneration;
        if (currentAttempt && generation === fileGeneration) {
          const message = extractError(err);
          set({ fileUrl: null, fileError: message, isFileLoading: false, error: message });
        }
        if (currentAttempt) maybeShowUpgradeDialog(err); // Both comparison sides retain DP-04.
        return null;
      } finally {
        if (latestFileAttemptByVersion.get(versionId) === attempt) {
          latestFileAttemptByVersion.delete(versionId);
        }
      }
    },

    downloadUrl: async (versionId) => {
      try {
        const { data } = await api.get(`versions/${versionId}/download/`);
        return data.url as string;
      } catch (err) {
        maybeShowUpgradeDialog(err); // DP-04 history lock → upgrade path
        set({ error: extractError(err) });
        return null;
      }
    },

    editMessage: async (versionId, message) => {
      try {
        const { data } = await api.patch(`versions/${versionId}/`, { message });
        set((state) => ({
          detail: state.detail ? { ...state.detail, message: data.message } : state.detail,
        }));
        return true;
      } catch (err) {
        set({ error: extractError(err) });
        return false;
      }
    },

    trashVersion: async (versionId) => {
      try {
        await api.delete(`versions/${versionId}/`);
        return true;
      } catch (err) {
        set({ error: extractError(err) });
        return false;
      }
    },

    restoreVersion: async (versionId) => {
      try {
        await api.post(`versions/${versionId}/restore/`);
        return true;
      } catch (err) {
        set({ error: extractError(err) });
        return false;
      }
    },
  };
});
