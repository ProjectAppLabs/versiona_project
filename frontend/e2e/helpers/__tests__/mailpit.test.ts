import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, jest } from '@jest/globals';
import { runInThisContext } from 'node:vm';

let assertNoEmailFor: typeof import('../mailpit').assertNoEmailFor;
let purgeMailbox: typeof import('../mailpit').purgeMailbox;

// Playwright's Node transport requires native Web APIs when imported in jsdom.
const webApiNames = [
  'Request', 'Response', 'Headers', 'TransformStream', 'ReadableStream', 'WritableStream',
  'TextEncoder', 'TextDecoder',
] as const;
const originalWebApis = webApiNames.map((name) => Object.getOwnPropertyDescriptor(globalThis, name));

const originalFetch = Object.getOwnPropertyDescriptor(globalThis, 'fetch');
const fetchMock = jest.fn<typeof fetch>();

beforeAll(async () => {
  const nativeWebApis = runInThisContext(
    '({ Request, Response, Headers, TransformStream, ReadableStream, WritableStream, TextEncoder, TextDecoder })'
  ) as Record<string, unknown>;
  webApiNames.forEach((name) => {
    Object.defineProperty(globalThis, name, { configurable: true, value: nativeWebApis[name] });
  });
  ({ assertNoEmailFor, purgeMailbox } = await import('../mailpit'));
});

afterAll(() => {
  webApiNames.forEach((name, index) => {
    const descriptor = originalWebApis[index];
    if (descriptor) Object.defineProperty(globalThis, name, descriptor);
    else Reflect.deleteProperty(globalThis, name);
  });
});

function response(status: number, messages: unknown = []): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => ({ messages }),
  } as Response;
}

beforeEach(() => {
  fetchMock.mockReset();
  Object.defineProperty(globalThis, 'fetch', { configurable: true, value: fetchMock });
});

afterEach(() => {
  if (originalFetch) {
    Object.defineProperty(globalThis, 'fetch', originalFetch);
  } else {
    Reflect.deleteProperty(globalThis, 'fetch');
  }
});

describe('Mailpit absence checks', () => {
  it('rejects a failed search response instead of proving absence', async () => {
    fetchMock.mockResolvedValueOnce(response(503));

    await expect(assertNoEmailFor('reviewer@versiona.test')).rejects.toThrow(
      'Mailpit search failed with HTTP 503'
    );
  });

  it('rejects absence when the recipient has a message', async () => {
    fetchMock.mockResolvedValueOnce(response(200, [{
      ID: 'message-1', To: [{ Address: 'reviewer@versiona.test' }], Subject: 'Revisión',
    }]));

    await expect(assertNoEmailFor('reviewer@versiona.test')).rejects.toThrow(
      'no debía haber correo para reviewer@versiona.test'
    );
  });

  it('accepts absence after a successful empty search', async () => {
    fetchMock.mockResolvedValueOnce(response(200));

    await expect(assertNoEmailFor('reviewer@versiona.test')).resolves.toBeUndefined();
  });

  it('rejects absence when the messages payload is invalid', async () => {
    fetchMock.mockResolvedValueOnce(response(200, null));

    await expect(assertNoEmailFor('reviewer@versiona.test')).rejects.toThrow(
      'Mailpit search returned an invalid messages payload'
    );
  });
});

describe('Mailpit mailbox preparation', () => {
  it('rejects a failed purge response', async () => {
    fetchMock.mockResolvedValueOnce(response(503));

    await expect(purgeMailbox()).rejects.toThrow('Mailpit purge failed with HTTP 503');
  });

  it('accepts a successful purge response', async () => {
    fetchMock.mockResolvedValueOnce(response(200));

    await expect(purgeMailbox()).resolves.toBeUndefined();
  });
});
