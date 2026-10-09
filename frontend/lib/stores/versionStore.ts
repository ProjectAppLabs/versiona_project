'use client';

import { create } from 'zustand';

import { api } from '@/lib/services/http';
import { maybeShowUpgradeDialog } from '@/lib/stores/upgradeDialogStore';
import type { VersionDetail } from '@/lib/types';

interface VersionState {
  detail: VersionDetail | null;
  fileUrl: string | null;
  isLoading: boolean;
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

export const useVersionStore = create<VersionState>((set) => ({
  detail: null,
  fileUrl: null,
  isLoading: false,
  error: null,

  fetchDetail: async (versionId) => {
    set({ isLoading: true, error: null });
    try {
      const { data } = await api.get<VersionDetail>(`versions/${versionId}/`);
      set({ detail: data, isLoading: false });
    } catch (err) {
      set({ isLoading: false, error: extractError(err) });
    }
  },

  fetchFileUrl: async (versionId) => {
    try {
      const { data } = await api.get(`versions/${versionId}/file/`);
      set({ fileUrl: data.url });
      return data.url as string;
    } catch (err) {
      maybeShowUpgradeDialog(err); // DP-04 history lock → upgrade path
      set({ error: extractError(err) });
      return null;
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
}));
