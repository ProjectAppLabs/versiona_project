import { expect, test } from '../../test-with-coverage';
import { A3_ACCOUNT_SECURITY } from '../../helpers/flow-tags';
import { totpNow } from '../../helpers/totp';
import { uniqueEmail } from '../../helpers/versiona';

/** A3 — TOTP end to end: enrol from settings, re-login demands the code.
 * Uses a FRESH account so the seeded users keep 2FA off for other specs. */

test.describe('A3 — Seguridad de la cuenta', () => {
  test.slow();

  test(
    'A3-F01/F03 — activar 2FA y entrar con el código',
    { tag: [...A3_ACCOUNT_SECURITY, '@scenario:a3-f01', '@scenario:a3-f03', '@outcome:success', '@outcome:error'] },
    async ({ page }) => {
      // Catches a first-factor login that creates a usable browser session before TOTP succeeds.
      const email = uniqueEmail('sec');

      // Cuenta nueva por UI
      await page.goto('/sign-up');
      await page.getByPlaceholder('Email').fill(email);
      await page.getByPlaceholder('Password', { exact: true }).fill('secreta123');
      await page.getByPlaceholder('Confirm password').fill('secreta123');
      await page.getByRole('button', { name: 'Crear cuenta' }).click();
      await page.waitForURL(/onboarding/, { timeout: 30_000 });

      // Enrolamiento en settings
      await page.goto('/settings');
      await expect(page.getByTestId('security-section')).toBeVisible({ timeout: 20_000 });
      await page.getByTestId('start-2fa').click();
      await expect(page.getByTestId('twofa-qr')).toBeVisible({ timeout: 15_000 });
      const secret = (await page.getByTestId('twofa-secret').textContent())?.trim() ?? '';
      expect(secret.length).toBeGreaterThan(10);

      await page.getByTestId('enable-code').fill(totpNow(secret));
      await page.getByTestId('enable-2fa').click();

      // Códigos de respaldo: se muestran UNA vez
      await expect(page.getByTestId('backup-codes')).toBeVisible({ timeout: 15_000 });
      await page.getByTestId('backup-saved').click();
      await expect(
        page.getByTestId('security-section').getByTestId('status-badge').first()
      ).toHaveText('Activa');

      // Re-login: la contraseña ya no basta (A3-F03)
      await page.getByRole('button', { name: 'Salir' }).click();
      const signInLink = page.getByTestId('public-header').getByRole('link', { name: 'Iniciar sesión' });
      await expect(signInLink).toHaveAttribute('href', '/sign-in');
      await signInLink.click();
      await page.waitForURL(/sign-in/, { timeout: 15_000 });
      await page.getByPlaceholder('Email').fill(email);
      await page.getByPlaceholder('Password').fill('secreta123');
      await page.getByRole('button', { name: 'Entrar' }).click();

      const twoFactorStep = page.getByTestId('twofa-step');
      await expect(twoFactorStep).toContainText('Verificación en dos pasos', { timeout: 15_000 });

      const pendingCookies = await page.context().cookies();
      expect(pendingCookies.some((cookie) => cookie.name === 'access_token' && cookie.value)).toBe(false);
      expect(pendingCookies.some((cookie) => cookie.name === 'refresh_token' && cookie.value)).toBe(false);

      // Un código malo se rechaza
      await page.getByTestId('twofa-code').fill('000000');
      await page.getByTestId('twofa-verify').click();
      await expect(twoFactorStep.getByRole('alert')).toHaveText('Código incorrecto.', { timeout: 10_000 });
      await expect(twoFactorStep).toContainText('Verificación en dos pasos');
      await expect(page.getByTestId('twofa-code')).toHaveValue('000000');

      // El código correcto entra
      await page.getByTestId('twofa-code').fill(totpNow(secret));
      await page.getByTestId('twofa-verify').click();
      await page.waitForURL(/\/(projects|dashboard|onboarding)/, { timeout: 20_000 });
      await expect(page.getByRole('button', { name: 'Salir' })).toBeVisible();
    }
  );
});
