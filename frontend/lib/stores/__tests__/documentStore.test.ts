import axios from 'axios';

import { api } from '../../services/http';
import { useDocumentStore } from '../documentStore';

jest.mock('../../services/http', () => ({
  api: { post: jest.fn() },
}));
jest.mock('axios', () => ({
  __esModule: true,
  default: { put: jest.fn() },
}));

const mockApiPost = api.post as jest.Mock;
const mockAxiosPut = axios.put as jest.Mock;

describe('documentStore upload orchestration', () => {
  beforeEach(() => {
    mockApiPost.mockReset();
    mockAxiosPut.mockReset();
    useDocumentStore.getState().resetUpload();
  });

  const file = new File(['%PDF-fake'], 'contrato.pdf', { type: 'application/pdf' });

  it('walks intent → PUT → complete and lands on analyzing with a job id', async () => {
    mockApiPost
      .mockResolvedValueOnce({ data: { upload_id: 'u1', url: 'http://minio/put', max_bytes: 1 } })
      .mockResolvedValueOnce({ data: { job_id: 'job-9', version: { number: 1 } } });
    mockAxiosPut.mockResolvedValueOnce({});

    const result = await useDocumentStore.getState().uploadVersion('doc-1', file, 'primera');

    expect(result.phase).toBe('analyzing');
    expect(result.jobId).toBe('job-9');
    expect(mockAxiosPut).toHaveBeenCalledWith(
      'http://minio/put',
      file,
      expect.objectContaining({ headers: { 'Content-Type': 'application/pdf' } })
    );
    expect(mockApiPost).toHaveBeenLastCalledWith('documents/doc-1/versions/complete/', {
      upload_id: 'u1',
      message: 'primera',
    });
  });

  it('surfaces the backend rejection message on complete failure', async () => {
    mockApiPost
      .mockResolvedValueOnce({ data: { upload_id: 'u2', url: 'http://minio/put', max_bytes: 1 } })
      .mockRejectedValueOnce({
        response: { data: { error: 'El archivo es idéntico a la versión v1.' } },
      });
    mockAxiosPut.mockResolvedValueOnce({});

    const result = await useDocumentStore.getState().uploadVersion('doc-1', file, 'dup');

    expect(result.phase).toBe('error');
    expect(result.error).toContain('idéntico');
  });

  // Fails if a throttled upload starts object storage or loses the retry delay shown to the user.
  it('reports the upload limit delay from a DRF throttling response', async () => {
    mockApiPost.mockRejectedValueOnce({
      response: {
        status: 429,
        data: { detail: 'Request was throttled. Expected available in 60 seconds.' },
        headers: { 'retry-after': '60' },
      },
    });

    const result = await useDocumentStore.getState().uploadVersion('doc-1', file, 'primera');

    expect(result).toEqual({
      phase: 'error',
      progress: 0,
      error: 'Alcanzaste el límite de subidas. Espera 60 segundos y vuelve a intentarlo.',
      jobId: null,
      version: null,
    });
    expect(mockApiPost).toHaveBeenCalledWith('documents/doc-1/versions/upload_intent/');
    expect(mockApiPost).toHaveBeenCalledTimes(1);
    expect(mockAxiosPut).not.toHaveBeenCalled();
  });

  // Fails if an unusable retry header exposes a raw throttling error instead of the safe fallback.
  it.each([
    ['missing', {}],
    ['malformed', { 'retry-after': 'later' }],
  ])('reports the generic upload limit message with a %s Retry-After header', async (_kind, headers) => {
    mockApiPost.mockRejectedValueOnce({
      response: {
        status: 429,
        data: { detail: 'Request was throttled. Expected available in 60 seconds.' },
        headers,
      },
    });

    const result = await useDocumentStore.getState().uploadVersion('doc-1', file, 'primera');

    expect(result).toEqual({
      phase: 'error',
      progress: 0,
      error: 'Alcanzaste el límite de subidas. Vuelve a intentarlo más tarde.',
      jobId: null,
      version: null,
    });
    expect(mockApiPost).toHaveBeenCalledWith('documents/doc-1/versions/upload_intent/');
    expect(mockApiPost).toHaveBeenCalledTimes(1);
    expect(mockAxiosPut).not.toHaveBeenCalled();
  });

  it('createDocument posts the title and returns the summary', async () => {
    mockApiPost.mockResolvedValueOnce({ data: { public_id: 'd1', title: 'Contrato' } });

    const doc = await useDocumentStore.getState().createDocument('proj-1', 'Contrato');

    expect(doc.public_id).toBe('d1');
    expect(mockApiPost).toHaveBeenCalledWith('projects/proj-1/documents/', { title: 'Contrato' });
  });
});
