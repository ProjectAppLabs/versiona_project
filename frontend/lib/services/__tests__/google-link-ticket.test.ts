import { clearGoogleLinkTicket, getGoogleLinkTicket, saveGoogleLinkTicket } from '../google-link-ticket';

beforeEach(() => { sessionStorage.clear(); jest.useRealTimers(); });
afterEach(() => { jest.useRealTimers(); });

it('keeps recovery proof in this tab without writing authentication cookies', () => {
  saveGoogleLinkTicket('email-proof');
  expect(getGoogleLinkTicket()).toBe('email-proof');
  expect(localStorage.getItem('google_link_ticket')).toBeNull();
  expect(document.cookie).not.toContain('email-proof');
});

it('discards an expired recovery proof', () => {
  jest.useFakeTimers();
  saveGoogleLinkTicket('email-proof');
  expect(getGoogleLinkTicket()).toBe('email-proof');
  jest.advanceTimersByTime(15 * 60 * 1000);
  expect(getGoogleLinkTicket()).toBeNull();
  expect(sessionStorage.getItem('google_link_ticket')).toBeNull();
});

it.each(['broken json', JSON.stringify({ ticket: 'proof' }), JSON.stringify({ ticket: 3, expiresAt: Date.now() + 10000 })])('discards malformed recovery proof %s', (raw) => {
  sessionStorage.setItem('google_link_ticket', raw);
  expect(getGoogleLinkTicket()).toBeNull();
});

it('clears the previous recovery proof when the next reset returns no ticket', () => {
  saveGoogleLinkTicket('old-proof');
  expect(getGoogleLinkTicket()).toBe('old-proof');
  saveGoogleLinkTicket(undefined);
  expect(getGoogleLinkTicket()).toBeNull();
  clearGoogleLinkTicket();
});
