/** Google script is the browser boundary; all Django endpoints remain real. */
import type { Page } from '@playwright/test';

export function googleCredential(email: string, subject = `e2e-google:${email}`): string {
  const payload = {
    email, sub: subject, email_verified: true,
    aud: process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID,
    iss: 'https://accounts.google.com', exp: Math.floor(Date.now() / 1000) + 3600,
  };
  return `VERSIONA_E2E.${Buffer.from(JSON.stringify(payload)).toString('base64url')}`;
}

export async function installGoogleBoundary(page: Page, credential: string): Promise<void> {
  await page.route('https://accounts.google.com/gsi/client', async (route) => {
    await route.fulfill({
      contentType: 'application/javascript',
      body: `(() => {
        let callback;
        window.google = { accounts: { id: {
          initialize: (options) => { callback = options.callback; },
          renderButton: (container) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = 'Continuar con Google';
            button.setAttribute('data-testid', 'google-boundary-button');
            button.addEventListener('click', () => callback({ credential: ${JSON.stringify(credential)} }));
            container.replaceChildren(button);
          },
          cancel: () => {}, disableAutoSelect: () => {}, prompt: () => {},
        } } };
      })();`,
    });
  });
}
