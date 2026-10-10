/**
 * Mailpit REST helpers (harness gap H03 — docs/plan/06 §5.4).
 * Pattern: positive-before-negative — call `waitForEmail` for the expected
 * recipient BEFORE asserting `assertNoEmailFor` on another one.
 */

import { expect } from '@playwright/test';

const MAILPIT_API = process.env.MAILPIT_API ?? 'http://127.0.0.1:8025';

interface MailpitMessage {
  ID: string;
  To: Array<{ Address: string }>;
  Subject: string;
}

async function search(query: string): Promise<MailpitMessage[]> {
  const response = await fetch(
    `${MAILPIT_API}/api/v1/search?query=${encodeURIComponent(query)}`
  );
  if (!response.ok) {
    throw new Error(`Mailpit search failed with HTTP ${response.status}`);
  }
  const data = (await response.json()) as { messages?: MailpitMessage[] };
  if (!Array.isArray(data.messages)) {
    throw new Error('Mailpit search returned an invalid messages payload');
  }
  return data.messages;
}

export async function waitForEmail(
  { to, subjectContains }: { to: string; subjectContains?: string },
  timeoutMs = 30_000
): Promise<MailpitMessage> {
  let found: MailpitMessage | undefined;
  await expect
    .poll(
      async () => {
        const messages = await search(`to:${to}`);
        found = subjectContains
          ? messages.find((m) => m.Subject.includes(subjectContains))
          : messages[0];
        return Boolean(found);
      },
      { timeout: timeoutMs, message: `email para ${to} no llegó` }
    )
    .toBe(true);
  return found as MailpitMessage;
}

export async function assertNoEmailFor(address: string): Promise<void> {
  const messages = await search(`to:${address}`);
  expect(messages, `no debía haber correo para ${address}`).toHaveLength(0);
}

export async function purgeMailbox(): Promise<void> {
  const response = await fetch(`${MAILPIT_API}/api/v1/messages`, { method: 'DELETE' });
  if (!response.ok) {
    throw new Error(`Mailpit purge failed with HTTP ${response.status}`);
  }
}
