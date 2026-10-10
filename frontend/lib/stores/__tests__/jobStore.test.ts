import { act } from '@testing-library/react';

import { api } from '../../services/http';
import { useJobStore } from '../jobStore';

jest.mock('../../services/http', () => ({
  api: { get: jest.fn() },
}));

const mockGet = api.get as jest.Mock;

describe('jobStore', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    mockGet.mockReset();
    useJobStore.setState({ jobs: {} });
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('polls until the job reaches done and notifies once', async () => {
    mockGet
      .mockResolvedValueOnce({ data: { public_id: 'j1', status: 'running' } })
      .mockResolvedValueOnce({ data: { public_id: 'j1', status: 'done', result: { ok: 1 } } });
    const onFinish = jest.fn();

    useJobStore.getState().track('j1', onFinish);

    await act(async () => {
      await jest.advanceTimersByTimeAsync(0); // first poll
      await jest.advanceTimersByTimeAsync(2000); // second poll (done)
    });

    expect(onFinish).toHaveBeenCalledTimes(1);
    expect(useJobStore.getState().jobs.j1.status).toBe('done');
  });

  it('stops polling when the job fails', async () => {
    mockGet.mockResolvedValue({ data: { public_id: 'j2', status: 'failed', error: 'boom' } });
    const onFinish = jest.fn();

    useJobStore.getState().track('j2', onFinish);

    await act(async () => {
      await jest.advanceTimersByTimeAsync(0);
      await jest.advanceTimersByTimeAsync(30000);
    });

    expect(onFinish).toHaveBeenCalledTimes(1);
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it('records a terminal timeout without a successful response', async () => {
    mockGet.mockRejectedValue(new Error('Network unavailable'));
    const startedAt = Date.now();
    useJobStore.getState().track('no-response-state');

    await act(async () => {
      await jest.advanceTimersByTimeAsync(310_000);
    });

    expect(useJobStore.getState().jobs['no-response-state']).toEqual({
      public_id: 'no-response-state',
      job_type: '',
      status: 'failed',
      attempts: 0,
      error: 'timeout',
      result: null,
      version_id: null,
      startedAt,
    });
  });

  it('notifies timeout once without a successful response', async () => {
    mockGet.mockRejectedValue(new Error('Network unavailable'));
    const onFinish = jest.fn();
    useJobStore.getState().track('no-response-callback', onFinish);

    await act(async () => {
      await jest.advanceTimersByTimeAsync(370_000);
    });

    expect(onFinish).toHaveBeenCalledTimes(1);
    expect(onFinish).toHaveBeenCalledWith(
      useJobStore.getState().jobs['no-response-callback']
    );
  });

  it('stops requests after polling errors exhaust the deadline', async () => {
    mockGet.mockRejectedValue(new Error('Network unavailable'));
    useJobStore.getState().track('no-response-requests');
    await act(async () => {
      await jest.advanceTimersByTimeAsync(310_000);
    });
    const callsAtTimeout = mockGet.mock.calls.length;

    await act(async () => {
      await jest.advanceTimersByTimeAsync(60_000);
    });

    expect(mockGet).toHaveBeenCalledTimes(callsAtTimeout);
    expect(jest.getTimerCount()).toBe(0);
  });

  it('retains the last successful snapshot on timeout', async () => {
    const snapshot = {
      public_id: 'previous-snapshot',
      job_type: 'analysis',
      status: 'running',
      attempts: 2,
      error: null,
      result: { checkpoint: 'analysis' },
      version_id: 'version-1',
    };
    mockGet
      .mockResolvedValueOnce({ data: snapshot })
      .mockRejectedValue(new Error('Network unavailable'));
    const startedAt = Date.now();
    useJobStore.getState().track('previous-snapshot');

    await act(async () => {
      await jest.advanceTimersByTimeAsync(310_000);
    });

    expect(useJobStore.getState().jobs['previous-snapshot']).toEqual({
      ...snapshot,
      status: 'failed',
      error: 'timeout',
      startedAt,
    });
  });

  it('does not double-track the same job id', async () => {
    mockGet.mockResolvedValue({ data: { public_id: 'j3', status: 'running' } });

    useJobStore.getState().track('j3');
    useJobStore.getState().track('j3');

    await act(async () => {
      await jest.advanceTimersByTimeAsync(0);
    });

    expect(mockGet).toHaveBeenCalledTimes(1);
    useJobStore.getState().clear('j3');
  });

  it('clear removes the job and its timer', async () => {
    mockGet.mockResolvedValue({ data: { public_id: 'j4', status: 'running' } });
    useJobStore.getState().track('j4');
    await act(async () => {
      await jest.advanceTimersByTimeAsync(0);
    });

    useJobStore.getState().clear('j4');

    expect(useJobStore.getState().jobs.j4).toBeUndefined();
    await act(async () => {
      await jest.advanceTimersByTimeAsync(60000);
    });
    expect(mockGet).toHaveBeenCalledTimes(1);
  });
});
