import { test, expect } from '../test-with-coverage';
import type { APIRequestContext } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { waitForPageLoad } from '../fixtures';
import { googleCredential, installGoogleBoundary } from '../helpers/google-boundary';
import { waitForEmail } from '../helpers/mailpit';
import { AUTH_SIGN_IN_FORM, AUTH_SIGN_UP_FORM, AUTH_LOGIN_INVALID, AUTH_PROTECTED_REDIRECT, AUTH_FORGOT_PASSWORD_FORM } from '../helpers/flow-tags';

async function createRecoveryAccount(request: APIRequestContext): Promise<string> {
  const email = `password-policy-${randomUUID()}@versiona.test`;
  const response = await request.post('/api/sign_up/', {
    data: { email, password: 'Violet-River!83', first_name: 'Recovery', last_name: 'Visitor' },
  });
  expect(response.status()).toBe(201);
  return email;
}

async function readRecoveryCode(request: APIRequestContext, email: string): Promise<string> {
  const mailpitApi = process.env.MAILPIT_API;
  if (!mailpitApi) throw new Error('MAILPIT_API must name the private E2E mailbox.');
  const message = await waitForEmail({ to: email, subjectContains: 'Password Reset Code' });
  const response = await request.get(`${mailpitApi}/api/v1/message/${message.ID}`);
  expect(response.status()).toBe(200);
  const body = (await response.json()).Text as string;
  const code = body.match(/\b\d{6}\b/)?.[0];
  expect(code).toMatch(/^\d{6}$/);
  return code as string;
}

test.describe('Authentication', () => {
  test('should show validation on empty form submission', { tag: [...AUTH_SIGN_IN_FORM, '@outcome:display'] }, async ({ page }) => {
    await page.goto('/sign-in');
    await waitForPageLoad(page);
    
    // Try to submit empty form
    const submitBtn = page.locator('button[type="submit"]');
    await submitBtn.click();
    
    // Should still be on sign-in page
    await expect(page).toHaveURL(/.*sign-in/);
  });

  test('should accept input in form fields', { tag: [...AUTH_SIGN_IN_FORM, '@outcome:display'] }, async ({ page }) => {
    await page.goto('/sign-in');
    await waitForPageLoad(page);
    
    // Fill email (using placeholder)
    const emailInput = page.getByPlaceholder('Email');
    await emailInput.fill('test@example.com');
    await expect(emailInput).toHaveValue('test@example.com');
    
    // Fill password
    const passwordInput = page.locator('input[type="password"]');
    await passwordInput.fill('password123');
    await expect(passwordInput).toHaveValue('password123');
  });

  test('should handle invalid credentials gracefully', { tag: [...AUTH_LOGIN_INVALID, '@outcome:error'] }, async ({ page }) => {
    await page.goto('/sign-in');
    await waitForPageLoad(page);
    
    // Fill with invalid credentials (using placeholder)
    const emailInput = page.getByPlaceholder('Email');
    await emailInput.fill('invalid@example.com');
    
    const passwordInput = page.locator('input[type="password"]');
    await passwordInput.fill('wrongpassword');
    
    // Submit
    const submitBtn = page.locator('button[type="submit"]');
    await submitBtn.click();
    
    // Should show error or stay on sign-in page
    await expect(page).toHaveURL(/.*sign-in/);
  });

  test('should redirect anonymous users away from the dashboard', { tag: [...AUTH_PROTECTED_REDIRECT, '@outcome:success'] }, async ({ page }) => {
    // quality: allow-no-interaction (authorization gate fires on navigation itself — redirect guard; no user action exists to drive)
    await page.goto('/dashboard');
    await waitForPageLoad(page);

    // Anonymous context (no storageState): /dashboard hard-redirects to
    // /projects (app/dashboard/page.tsx), and the useRequireAuth guard that
    // gates /projects then bounces the unauthenticated visitor to /sign-in
    // before projects-grid ever mounts.
    await expect(page).toHaveURL(/\/sign-in/);
    await expect(page.getByTestId('projects-grid')).toHaveCount(0);
  });

  test('should validate password mismatch on sign-up', { tag: [...AUTH_SIGN_UP_FORM, '@outcome:error'] }, async ({ page }) => {
    await page.goto('/sign-up');
    await waitForPageLoad(page);

    // Fill form with mismatched passwords
    await page.getByPlaceholder('First Name').fill('Test');
    await page.getByPlaceholder('Last Name').fill('User');
    await page.getByPlaceholder('Email').fill('test@example.com');
    await page.getByPlaceholder('Password', { exact: true }).fill('password123');
    await page.getByPlaceholder('Confirm Password').fill('different456');

    await page.getByRole('button', { name: 'Crear cuenta' }).click();

    // Should show password mismatch error and stay on sign-up page
    await expect(page.getByText('Las contraseñas no coinciden')).toBeVisible();
    await expect(page).toHaveURL(/.*sign-up/);
  });

  // Fails if sign-up discards the real server's common-password rejection or enters onboarding after a 400.
  test('should display the server rejection for a common sign-up password', {
    tag: [...AUTH_SIGN_UP_FORM, '@outcome:error'],
  }, async ({ page }) => {
    await page.goto('/sign-up');
    await page.getByPlaceholder('First Name').fill('Policy');
    await page.getByPlaceholder('Last Name').fill('Visitor');
    await page.getByPlaceholder('Email').fill(`signup-policy-${randomUUID()}@versiona.test`);
    await page.getByPlaceholder('Password', { exact: true }).fill('password123');
    await page.getByPlaceholder('Confirm Password').fill('password123');
    await page.getByRole('button', { name: 'Crear cuenta' }).click();
    await expect(page.getByText('This password is too common.', { exact: true })).toHaveText('This password is too common.');
    await expect(page).toHaveURL(/\/sign-up$/);
  });

  // Fails if a password-policy rejection consumes the recovery code or the valid retry cannot authenticate.
  test('should preserve the recovery code after rejecting a numeric password', {
    tag: [...AUTH_FORGOT_PASSWORD_FORM, '@outcome:error'],
  }, async ({ page, request }) => {
    const email = await createRecoveryAccount(request);
    await page.goto('/forgot-password');
    await page.getByPlaceholder('Email').fill(email);
    await page.getByRole('button', { name: 'Send verification code', exact: true }).click();
    const code = await readRecoveryCode(request, email);
    await page.getByPlaceholder('000000').fill(code);
    await page.getByPlaceholder('New Password', { exact: true }).fill('739152864039');
    await page.getByPlaceholder('Confirm New Password').fill('739152864039');
    await page.getByRole('button', { name: 'Reset password', exact: true }).click();
    await expect(page.getByText('This password is entirely numeric.', { exact: true })).toHaveText('This password is entirely numeric.');
    await expect(page).toHaveURL(/\/forgot-password$/);
    await page.getByPlaceholder('000000').fill(code);
    await page.getByPlaceholder('New Password', { exact: true }).fill('NewPass!2026');
    await page.getByPlaceholder('Confirm New Password').fill('NewPass!2026');
    await page.getByRole('button', { name: 'Reset password', exact: true }).click();
    await expect(page).toHaveURL(/\/sign-in\?next=\/settings$/);
    await page.getByPlaceholder('Email').fill(email);
    await page.getByPlaceholder('Password', { exact: true }).fill('NewPass!2026');
    await page.getByRole('button', { name: 'Entrar', exact: true }).click();
    await expect(page).toHaveURL(/\/settings$/);
  });

  test('should navigate from sign-in to forgot password', { tag: [...AUTH_FORGOT_PASSWORD_FORM, '@outcome:display'] }, async ({ page }) => {
    await page.goto('/sign-in');
    await waitForPageLoad(page);

    // Click forgot password link
    const forgotLink = page.getByRole('link', { name: '¿Olvidaste tu contraseña?' });
    await expect(forgotLink).toBeVisible();
    await forgotLink.click();
    await page.waitForURL(/.*forgot-password/, { timeout: 10_000 });

    await expect(page).toHaveURL(/.*forgot-password/);
    await expect(page.getByRole('heading', { name: 'Reset Password' })).toBeVisible();
  });
});


for (const { route, tags } of [
  { route: '/sign-in', tags: AUTH_SIGN_IN_FORM },
  { route: '/sign-up', tags: AUTH_SIGN_UP_FORM },
]) {
  test(`Google on ${route} requires recovery for an existing email`, {
    tag: [...tags, '@outcome:error'],
  }, async ({ page, request }) => {
    const email = await createRecoveryAccount(request);
    await installGoogleBoundary(page, googleCredential(email));
    await page.goto(route);
    await page.getByTestId('google-boundary-button').click();
    await expect(page.getByTestId('google-link-required')).toBeVisible();
    const cookies = await page.context().cookies();
    expect(cookies.some((cookie) => cookie.name === 'access_token' && cookie.value)).toBe(false);
    await page.getByTestId('google-link-required').getByRole('link').click();
    await expect(page).toHaveURL(/\/forgot-password$/);
  });
}

test('new Google identity enters onboarding through the real API', {
  tag: [...AUTH_SIGN_UP_FORM, '@outcome:success'],
}, async ({ page }) => {
  const email = `google-new-${randomUUID()}@versiona.test`;
  await installGoogleBoundary(page, googleCredential(email));
  await page.goto('/sign-up');
  await page.getByTestId('google-boundary-button').click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(page.getByRole('button', { name: 'Salir' })).toBeVisible();
});
