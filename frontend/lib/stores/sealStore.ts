'use client';

import { create } from 'zustand';

import { api } from '@/lib/services/http';

export interface SealSummary {
  public_id: string;
  reviewer_email: string;
  version_number: number;
  covers_all: boolean;
  covered_keys: string[];
  key_id: string;
  is_active: boolean;
  revoked_at: string | null;
  created_at: string;
}

export interface ValidityRecord {
  seal: SealSummary;
  to_version: number;
  decision: 'preserved' | 'invalidated' | 'pending_confirmation' | 'superseded';
  proposed_decision: string;
  reason_code: string;
  evidence: {
    verified?: Array<{ stable_key: string }>;
    changed?: Array<{ stable_key: string; change_type: string }>;
    still_intact?: Array<{ stable_key: string }>;
  };
  decided_mode: string;
  decided_by_email: string | null;
  decided_at: string | null;
}

export interface VerifyResult {
  signature_valid: boolean;
  binds_version_sha256: boolean;
  key_id: string;
  public_key: string;
  algorithm: string;
}

interface SealState {
  versionId: string | null;
  seals: SealSummary[];
  validityRecords: ValidityRecord[];
  pendingPlan: ValidityRecord[];
  isLoading: boolean;
  isSubmitting: boolean;
  error: string | null;
  fetchSeals: (versionId: string) => Promise<void>;
  createSeal: (
    versionId: string,
    options: { coversAll: boolean; sectionKeys?: string[] }
  ) => Promise<boolean>;
  revokeSeal: (versionId: string, sealId: string) => Promise<boolean>;
  verifySeal: (versionId: string, sealId: string) => Promise<VerifyResult | null>;
  fetchPlan: (versionId: string) => Promise<void>;
  confirmPlan: (versionId: string, decisions: Record<string, string>) => Promise<boolean>;
}

function messageOf(err: unknown): string {
  return (
    (err as { response?: { data?: { error?: string } } })?.response?.data?.error ??
    (err as Error)?.message ??
    'Algo salió mal'
  );
}

export const useSealStore = create<SealState>((set, get) => {
  let navigationGeneration = 0;
  let sealsGeneration = 0;
  let planGeneration = 0;
  let submissionGeneration = 0;

  // A new visit owns all three datasets; per-resource generations also prevent
  // an older refresh of the same UUID from replacing a newer response.
  const enterVersion = (versionId: string) => {
    if (get().versionId !== versionId) {
      navigationGeneration += 1;
      sealsGeneration += 1;
      planGeneration += 1;
      submissionGeneration += 1;
      set({
        versionId, seals: [], validityRecords: [], pendingPlan: [],
        isLoading: false, isSubmitting: false, error: null,
      });
    }
    const generation = navigationGeneration;
    return () => generation === navigationGeneration && get().versionId === versionId;
  };

  return {
    versionId: null,
    seals: [],
    validityRecords: [],
    pendingPlan: [],
    isLoading: false,
    isSubmitting: false,
    error: null,

    fetchSeals: async (versionId) => {
      const isCurrentVersion = enterVersion(versionId);
      const generation = ++sealsGeneration;
      const isCurrent = () => isCurrentVersion() && generation === sealsGeneration;
      set({ isLoading: true, error: null });
      try {
        const { data } = await api.get(`versions/${versionId}/seals/`);
        if (isCurrent()) {
          set({ seals: data.seals, validityRecords: data.validity_records, isLoading: false });
        }
      } catch (err) {
        if (isCurrent()) set({ isLoading: false, error: messageOf(err) });
      }
    },

    createSeal: async (versionId, { coversAll, sectionKeys = [] }) => {
      const isCurrentVersion = enterVersion(versionId);
      const generation = ++submissionGeneration;
      const isCurrent = () => isCurrentVersion() && generation === submissionGeneration;
      set({ isSubmitting: true, error: null });
      try {
        await api.post(`versions/${versionId}/seals/`, {
          covers_all: coversAll,
          section_keys: sectionKeys,
        });
        if (isCurrent()) {
          set({ isSubmitting: false });
          await get().fetchSeals(versionId);
        }
        return true;
      } catch (err) {
        if (isCurrent()) set({ isSubmitting: false, error: messageOf(err) });
        return false;
      }
    },

    revokeSeal: async (versionId, sealId) => {
      const isCurrent = enterVersion(versionId);
      try {
        await api.post(`versions/${versionId}/seals/${sealId}/revoke/`);
        if (isCurrent()) await get().fetchSeals(versionId);
        return true;
      } catch (err) {
        if (isCurrent()) set({ error: messageOf(err) });
        return false;
      }
    },

    verifySeal: async (versionId, sealId) => {
      const isCurrent = enterVersion(versionId);
      try {
        const { data } = await api.get(`versions/${versionId}/seals/${sealId}/verify/`);
        return data as VerifyResult;
      } catch (err) {
        if (isCurrent()) set({ error: messageOf(err) });
        return null;
      }
    },

    fetchPlan: async (versionId) => {
      const isCurrentVersion = enterVersion(versionId);
      const generation = ++planGeneration;
      const isCurrent = () => isCurrentVersion() && generation === planGeneration;
      try {
        const { data } = await api.get(`versions/${versionId}/seal_plan/`);
        if (isCurrent()) set({ pendingPlan: data.pending });
      } catch (err) {
        if (isCurrent()) set({ error: messageOf(err) });
      }
    },

    confirmPlan: async (versionId, decisions) => {
      const isCurrentVersion = enterVersion(versionId);
      const generation = ++submissionGeneration;
      const isCurrent = () => isCurrentVersion() && generation === submissionGeneration;
      set({ isSubmitting: true, error: null });
      try {
        await api.post(`versions/${versionId}/seal_plan/`, { decisions });
        if (isCurrent()) {
          // An in-flight GET must not resurrect the plan just confirmed.
          planGeneration += 1;
          set({ isSubmitting: false, pendingPlan: [] });
          await get().fetchSeals(versionId);
        }
        return true;
      } catch (err) {
        if (isCurrent()) set({ isSubmitting: false, error: messageOf(err) });
        return false;
      }
    },
  };
});
