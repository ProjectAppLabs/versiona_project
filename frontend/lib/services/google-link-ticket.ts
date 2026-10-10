/** Recovery proof stays in this browser tab; it never authenticates a session. */
const STORAGE_KEY = 'google_link_ticket';
const TICKET_LIFETIME_MS = 15 * 60 * 1000;

export function clearGoogleLinkTicket(): void {
  try { sessionStorage.removeItem(STORAGE_KEY); } catch { /* Storage may be unavailable. */ }
}

export function saveGoogleLinkTicket(ticket: unknown): void {
  clearGoogleLinkTicket();
  if (typeof ticket !== 'string' || !ticket.trim()) return;
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ ticket, expiresAt: Date.now() + TICKET_LIFETIME_MS }));
  } catch { /* Recovery still succeeds without browser storage. */ }
}

export function getGoogleLinkTicket(): string | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const proof = JSON.parse(raw);
    if (typeof proof.ticket === 'string' && proof.ticket.trim() &&
        typeof proof.expiresAt === 'number' && proof.expiresAt > Date.now()) return proof.ticket;
  } catch { /* Discard corrupt or unavailable storage. */ }
  clearGoogleLinkTicket();
  return null;
}
