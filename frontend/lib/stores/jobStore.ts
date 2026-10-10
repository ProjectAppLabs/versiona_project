'use client';

/**
 * Generic engine-job tracker (docs/plan/04 §4): polling 2 s → ×1.5 backoff
 * capped at 10 s, stops on done/failed or after 5 minutes (StagingGate
 * pattern; SSE is V2).
 */

import { create } from 'zustand';

import { api } from '@/lib/services/http';
import type { EngineJobStatus } from '@/lib/types';

const INITIAL_INTERVAL_MS = 2_000;
const MAX_INTERVAL_MS = 10_000;
const TIMEOUT_MS = 5 * 60_000;

interface TrackedJob extends EngineJobStatus {
  startedAt: number;
}

interface JobState {
  jobs: Record<string, TrackedJob>;
  track: (jobId: string, onFinish?: (job: EngineJobStatus) => void) => void;
  clear: (jobId: string) => void;
}

const timers = new Map<string, ReturnType<typeof setTimeout>>();

export const useJobStore = create<JobState>((set, get) => ({
  jobs: {},

  track: (jobId, onFinish) => {
    if (timers.has(jobId)) return;
    const startedAt = Date.now();

    const poll = async (interval: number) => {
      try {
        const { data } = await api.get<EngineJobStatus>(`jobs/${jobId}/`);
        set((state) => ({ jobs: { ...state.jobs, [jobId]: { ...data, startedAt } } }));
        if (data.status === 'done' || data.status === 'failed') {
          timers.delete(jobId);
          onFinish?.(data);
          return;
        }
      } catch {
        // transient polling error: keep trying until the timeout
      }
      if (Date.now() - startedAt > TIMEOUT_MS) {
        timers.delete(jobId);
        const current = get().jobs[jobId];
        const timedOut: TrackedJob = {
          public_id: jobId,
          job_type: '',
          attempts: 0,
          result: null,
          version_id: null,
          startedAt,
          ...current,
          status: 'failed',
          error: 'timeout',
        };
        set((state) => ({ jobs: { ...state.jobs, [jobId]: timedOut } }));
        onFinish?.(timedOut);
        return;
      }
      const nextInterval = Math.min(interval * 1.5, MAX_INTERVAL_MS);
      timers.set(jobId, setTimeout(() => void poll(nextInterval), interval));
    };

    timers.set(jobId, setTimeout(() => void poll(INITIAL_INTERVAL_MS), 0));
  },

  clear: (jobId) => {
    const timer = timers.get(jobId);
    if (timer) clearTimeout(timer);
    timers.delete(jobId);
    set((state) => {
      const jobs = { ...state.jobs };
      delete jobs[jobId];
      return { jobs };
    });
  },
}));
