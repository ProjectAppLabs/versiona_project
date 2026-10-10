'use client';

import { create } from 'zustand';

import { api } from '@/lib/services/http';
import { maybeShowUpgradeDialog } from '@/lib/stores/upgradeDialogStore';
import type { NormalizedBBox } from '@/lib/pdf/coords';
import type { SectionChange } from '@/lib/compare/sync';

export interface ComparisonDetail {
  public_id: string;
  status: string;
  summary: { counts?: Record<string, number>; text?: string; from?: number; to?: number };
  has_changes: boolean;
  from_version: string;
  to_version: string;
  from_number: number;
  to_number: number;
  section_changes: SectionChange[];
}

export interface SectionDiffDetail extends SectionChange {
  word_diff: Array<{ op: 'equal' | 'insert' | 'delete'; text: string }>;
  bboxes_from: NormalizedBBox[];
  bboxes_to: NormalizedBBox[];
}

interface CompareState {
  requestKey: string | null;
  comparison: ComparisonDetail | null;
  diffs: Record<string, SectionDiffDetail>;
  activeSection: string | null;
  isLoading: boolean;
  error: string | null;
  compare: (documentId: string, fromVersion: string, toVersion: string) => Promise<void>;
  fetchSectionDiff: (sectionKey: string) => Promise<SectionDiffDetail | null>;
  setActiveSection: (key: string | null) => void;
  reset: () => void;
}

function extractError(err: unknown): string {
  return (
    (err as { response?: { data?: { error?: string } } })?.response?.data?.error ??
    (err as Error)?.message ??
    'No se pudo comparar'
  );
}

export const useCompareStore = create<CompareState>((set, get) => {
  let requestGeneration = 0;
  return {
    requestKey: null,
    comparison: null,
    diffs: {},
    activeSection: null,
    isLoading: false,
    error: null,

    compare: async (documentId, fromVersion, toVersion) => {
      const generation = ++requestGeneration;
      set({
        requestKey: JSON.stringify([documentId, fromVersion, toVersion]),
        isLoading: true, error: null, comparison: null, diffs: {}, activeSection: null,
      });
      try {
        const { data } = await api.post<ComparisonDetail>(
          `documents/${documentId}/comparisons/`,
          { from_version: fromVersion, to_version: toVersion }
        );
        if (generation !== requestGeneration) return;
        set({ comparison: data, isLoading: false });
      } catch (err) {
        if (generation !== requestGeneration) return;
        maybeShowUpgradeDialog(err); // DP-04 history lock → upgrade path
        set({ isLoading: false, error: extractError(err) });
      }
    },

    fetchSectionDiff: async (sectionKey) => {
      const { comparison, diffs } = get();
      if (!comparison) return null;
      if (diffs[sectionKey]) return diffs[sectionKey];
      const generation = requestGeneration;
      const isCurrent = () => generation === requestGeneration
        && get().comparison?.public_id === comparison.public_id;
      try {
        const { data } = await api.get<SectionDiffDetail>(
          `comparisons/${comparison.public_id}/sections/${sectionKey}/diff/`
        );
        if (!isCurrent()) return null;
        set((state) => ({ diffs: { ...state.diffs, [sectionKey]: data } }));
        return data;
      } catch (err) {
        if (isCurrent()) set({ error: extractError(err) });
        return null;
      }
    },

    setActiveSection: (key) => set({ activeSection: key }),
    reset: () => {
      requestGeneration += 1;
      set({ requestKey: null, comparison: null, diffs: {}, activeSection: null, error: null, isLoading: false });
    },
  };
});
