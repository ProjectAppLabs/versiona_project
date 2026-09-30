import { expect, test, type Page } from '../../test-with-coverage';
import { A2_INVITE_TEAM } from '../../helpers/flow-tags';
import { waitForEmail } from '../../helpers/mailpit';
import { viewportUse } from '../../helpers/viewports';
import { openSeededProject, uniqueEmail } from '../../helpers/versiona';

const LONG_MEMBER_EMAIL = `responsable-${'departamento'.repeat(8)}@versiona.test`;
const LONG_PENDING_EMAIL = `invitado-${'departamento'.repeat(8)}@versiona.test`;
const MAILPIT_API = process.env.MAILPIT_API ?? 'http://127.0.0.1:8025';

async function mockLongEmailRows(page: Page): Promise<void> {
  await page.route('**/api/projects/*/members/', async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ results: [{ id: 1, email: LONG_MEMBER_EMAIL, role: 'admin' }] }),
    });
  });
  await page.route('**/api/projects/*/invitations/', async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        results: [{
          public_id: '00000000-0000-4000-8000-000000000001',
          email: LONG_PENDING_EMAIL,
          role: 'reviewer',
          status: 'pending',
          invited_by: LONG_MEMBER_EMAIL,
          created_at: '2026-09-30T00:00:00Z',
        }],
      }),
    });
  });
}

async function assertLongEmailLayout(page: Page, memberRow: ReturnType<Page['getByText']>, pendingRow: ReturnType<Page['getByText']>): Promise<void> {
  const viewportWidth = await page.evaluate(() => window.innerWidth);
  const controls = ['invite-email', 'invite-role', 'send-invite', `revoke-${LONG_PENDING_EMAIL}`]
    .map((testId) => page.getByTestId(testId));
  const controlMetrics = await Promise.all(controls.map(async (control) => {
    const box = await control.boundingBox();
    return box === null ? { insideViewport: false, touchTarget: false } : {
      insideViewport: box.x + box.width <= viewportWidth,
      touchTarget: box.height >= 44,
    };
  }));
  const emailMetrics = await Promise.all([memberRow, pendingRow].map((row) => row.evaluate((element) => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return {
      clipped: element.scrollWidth > element.clientWidth,
      hasEllipsis: style.textOverflow === 'ellipsis',
      hasNoWrap: style.whiteSpace === 'nowrap',
      insideViewport: rect.right <= window.innerWidth,
    };
  })));
  expect(controlMetrics.every(({ insideViewport, touchTarget }) => insideViewport && touchTarget)).toBe(true);
  expect(emailMetrics.every(({ clipped, hasEllipsis, hasNoWrap, insideViewport }) => (
    !clipped && !hasEllipsis && !hasNoWrap && insideViewport
  ))).toBe(true);
}

test.describe('A2 — Invitar al equipo', () => {
  test.slow();

  test(
    'A2-F01/F02 — invitación por email, registro y aterrizaje directo en el proyecto',
    { tag: [...A2_INVITE_TEAM, '@scenario:a2-f01', '@scenario:a2-f02', '@outcome:success'] },
    async ({ browser }) => {
      const invitee = uniqueEmail('inv');

      // Admin invita desde la configuración del proyecto
      const adminContext = await browser.newContext({ storageState: 'e2e/.auth/admin.json' });
      const adminPage = await adminContext.newPage();
      await openSeededProject(adminPage);
      await adminPage.getByTestId('project-settings-link').click();
      await adminPage.waitForURL(/\/settings$/);
      await expect(adminPage.getByTestId('members-section')).toBeVisible({ timeout: 20_000 });
      await adminPage.getByTestId('invite-email').fill(invitee);
      await adminPage.getByTestId('invite-role').selectOption('reviewer');
      await adminPage.getByTestId('send-invite').click();
      await expect(
        adminPage.getByTestId('invitations-list').getByText(invitee)
      ).toBeVisible({ timeout: 15_000 });

      // El email llega con el enlace del token
      const email = await waitForEmail({ to: invitee, subjectContains: 'invitó' });
      expect(email.Subject).toContain('Torre E2E');

      // La invitada abre el enlace SIN sesión: la landing pública la guía
      const inviteeContext = await browser.newContext();
      const inviteePage = await inviteeContext.newPage();
      // El token viaja en el cuerpo del email; lo recuperamos vía API pública
      const adminApi = await adminContext.request.get(
        `${MAILPIT_API}/api/v1/search?query=${encodeURIComponent(`to:${invitee}`)}`
      );
      const messages = (await adminApi.json()).messages;
      const detail = await adminContext.request.get(
        `${MAILPIT_API}/api/v1/message/${messages[0].ID}`
      );
      const body = (await detail.json()).Text as string;
      const token = body.match(/\/invite\/([\w-]+)/)?.[1];
      expect(token).toMatch(/^[\w-]{20,64}$/);

      await inviteePage.goto(`/invite/${token}`);
      await expect(inviteePage.getByTestId('invite-landing')).toBeVisible({ timeout: 20_000 });
      await expect(inviteePage.getByText(/reviewer/)).toBeVisible();

      // Crea su cuenta con el email invitado y vuelve a aceptar
      await inviteePage
        .getByTestId('invite-landing')
        .getByRole('link', { name: 'Crear cuenta' })
        .click();
      await inviteePage.waitForURL(/sign-up/);
      await inviteePage.getByPlaceholder('Email').fill(invitee);
      await inviteePage.getByPlaceholder('Password', { exact: true }).fill('secreta123');
      await inviteePage.getByPlaceholder('Confirm password').fill('secreta123');
      await inviteePage.getByRole('button', { name: 'Crear cuenta' }).click();
      await inviteePage.waitForURL(/onboarding/, { timeout: 30_000 });

      await inviteePage.goto(`/invite/${token}`);
      await inviteePage.getByTestId('accept-invitation').click();

      // Aterriza directo en el proyecto (A2-F02)
      await inviteePage.waitForURL(/\/projects\/[0-9a-f-]+$/, { timeout: 20_000 });
      await expect(inviteePage.getByTestId('upload-dropzone')).toBeVisible({ timeout: 15_000 });

      await adminContext.close();
      await inviteeContext.close();
    }
  );

  // `storageState` scoped to this block only: a describe-level `test.use` also
  // becomes the default for every bare `browser.newContext()` in its scope,
  // which would silently authenticate F01's supposedly anonymous invitee.
  test.describe('con sesión de admin', () => {
    test.use({ storageState: 'e2e/.auth/admin.json' });

    test(
      'A2-E01 — invitar dos veces al mismo email no crea una invitación duplicada',
      { tag: [...A2_INVITE_TEAM, '@scenario:a2-e01', '@outcome:error'] },
      async ({ page }) => {
        // Catches: a regression that drops/weakens the duplicate-pending check
        // in `create_invitation`, or a frontend that stops surfacing
        // `err.response.data.error` and silently swallows the 409.
        const invitee = uniqueEmail('dup');

        await openSeededProject(page);
        await page.getByTestId('project-settings-link').click();
        await page.waitForURL(/\/settings$/);
        await expect(page.getByTestId('members-section')).toBeVisible({ timeout: 20_000 });

        await page.getByTestId('invite-email').fill(invitee);
        await page.getByTestId('send-invite').click();
        await expect(
          page.getByTestId('invitations-list').getByText(invitee)
        ).toBeVisible({ timeout: 15_000 });

        // Segundo envío al MISMO email: el backend rechaza el duplicado.
        await page.getByTestId('invite-email').fill(invitee);
        await page.getByTestId('send-invite').click();

        await expect(page.getByTestId('toaster')).toContainText(
          `Ya hay una invitación pendiente para ${invitee}.`,
          { timeout: 15_000 }
        );
        await expect(
          page.getByTestId('invitations-list').locator('li', { hasText: invitee })
        ).toHaveCount(1);
      }
    );
  });

  test.describe('miembros responsivos', () => {
    test.use({ ...viewportUse('portrait'), storageState: 'e2e/.auth/admin.json' });

    test(
      'A2-R01 — a 835 px los correos largos conservan lectura y acciones de invitación',
      {
        tag: [
          ...A2_INVITE_TEAM,
          '@scenario:a2-r01',
          '@outcome:display',
          '@viewport:portrait',
        ],
      },
      async ({ page }) => {
        // quality: allow-duplicate (per-viewport contract: a2-invite-team @ 835)
        // Catches: a long member or pending-invitation email that truncates,
        // pushes its revoke action outside the tablet viewport, or shrinks the
        // invitation controls below a touch target.
        await mockLongEmailRows(page);
        await openSeededProject(page);
        await page.getByTestId('project-settings-link').click();
        await page.waitForURL(/\/settings$/);
        const memberRow = page.getByTestId('members-section').getByText(LONG_MEMBER_EMAIL, { exact: true });
        await expect(memberRow).toHaveCount(1);

        const invitee = uniqueEmail('portrait-invite');
        await page.getByTestId('invite-email').fill(invitee);
        await page.getByTestId('invite-role').selectOption('reviewer');
        await expect(page.getByTestId('invite-email')).toHaveValue(invitee);
        const pendingRow = page.getByTestId('invitations-list').getByText(LONG_PENDING_EMAIL, { exact: false });
        await expect(pendingRow).toHaveCount(1);
        await assertLongEmailLayout(page, memberRow, pendingRow);
        await expect
          .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
          .toBe(true);
      }
    );
  });
});
