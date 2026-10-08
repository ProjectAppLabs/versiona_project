import type { Locator, Page, TestInfo } from '@playwright/test';
import { expect, test } from '../../test-with-coverage';
import { AUTH } from '../../helpers/versiona';
import { viewportUse, type ViewportAlias } from '../../helpers/viewports';

const AUTHENTICATED_NAVIGATION = ['@flow:layout-authenticated-navigation', '@module:org', '@priority:P2'];
const MEMBER_LINKS = ['Ayuda', 'Panel', 'Plan y uso', 'Configuración'];
const OWNER_LINKS = ['Ayuda', 'Panel', 'Plan y uso', 'Papelera', 'Configuración'];
const NOTIFICATION_ID = '00000000-0000-4000-8000-000000000123';
const NOTIFICATION_TITLE = 'Uso de Acme E2E actualizado';

async function openCompactNavigation(page: Page) {
  const toggle = page.getByTestId('app-nav-toggle');
  await expect(toggle).toBeVisible();
  const box = (await toggle.boundingBox())!;
  expect(box.width).toBeGreaterThanOrEqual(44);
  expect(box.height).toBeGreaterThanOrEqual(44);
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
}

async function useDesktopNavigation(page: Page) {
  await expect(page.getByTestId('app-nav-toggle')).toBeHidden();
}

const VARIANTS: Array<{ alias: ViewportAlias; openNavigation: (page: Page) => Promise<void> }> = [
  { alias: 'compact', openNavigation: openCompactNavigation },
  { alias: 'portrait', openNavigation: openCompactNavigation },
  { alias: 'landscape', openNavigation: useDesktopNavigation },
  { alias: 'desktop', openNavigation: useDesktopNavigation },
  { alias: 'wide', openNavigation: useDesktopNavigation },
];

async function enterProjects(page: Page) {
  const orgsLoaded = page.waitForResponse((response) => new URL(response.url()).pathname === '/api/orgs/' && response.status() === 200);
  await page.goto('/projects');
  const response = await orgsLoaded;
  expect((await response.json()).results).toEqual(expect.arrayContaining([expect.objectContaining({ name: 'Acme E2E' })]));
  await expect(page.getByTestId('app-header')).toBeVisible();
  await expect(page.getByTestId('projects-grid').getByRole('link', { name: /Torre E2E/ })).toHaveCount(1);
}

async function assertControlGeometry(page: Page, controls: Locator, testInfo: TestInfo) {
  const viewport = page.viewportSize()!;
  const boxes = await controls.evaluateAll((elements) => elements.map((element) => {
    const box = element.getBoundingClientRect();
    return { label: element.getAttribute('aria-label') ?? element.textContent?.trim(),
      width: box.width, height: box.height, left: box.left, right: box.right, top: box.top, bottom: box.bottom };
  }));
  for (const box of boxes) {
    expect(box.width, `${box.label}: touch width`).toBeGreaterThanOrEqual(44);
    expect(box.height, `${box.label}: touch height`).toBeGreaterThanOrEqual(44);
    expect(box.left, `${box.label}: left edge`).toBeGreaterThanOrEqual(0);
    expect(box.right, `${box.label}: right edge`).toBeLessThanOrEqual(viewport.width);
  }
  for (let index = 1; index < boxes.length; index += 1) {
    const previous = boxes[index - 1];
    const next = boxes[index];
    expect(Math.max(next.left - previous.right, next.top - previous.bottom), 'touch spacing').toBeGreaterThanOrEqual(8);
  }
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth).toBeLessThanOrEqual(viewport.width);
  await testInfo.attach('navigation-geometry', {
    body: Buffer.from(JSON.stringify({ viewport, scrollWidth, boxes }, null, 2)), contentType: 'application/json',
  });
}

for (const { alias, openNavigation } of VARIANTS) {
  test.describe(`Navegación del miembro @viewport:${alias}`, { tag: [...AUTHENTICATED_NAVIGATION] }, () => {
    test.use({ ...viewportUse(alias), storageState: AUTH.viewer });

    test('el miembro abre plan y uso desde el menú', { tag: ['@outcome:success'] }, async ({ page }, testInfo) => {
      // quality: allow-duplicate (per-viewport contract: layout-authenticated-navigation member at the five standard viewports)
      // Bug: R-layout-01 desborda la fila autenticada o expone Papelera a un miembro (NAV-1/NAV-3, I12).
      await enterProjects(page);
      await openNavigation(page);
      const header = page.getByTestId('app-header');
      const navigation = header.getByTestId('app-nav-menu');
      await expect(header.getByRole('navigation')).toHaveCount(1);
      await expect(navigation.getByRole('link')).toHaveText(MEMBER_LINKS);
      await expect(navigation.getByRole('link', { name: 'Papelera', exact: true })).toHaveCount(0);
      await assertControlGeometry(page, navigation.getByRole('link').or(navigation.getByRole('button')), testInfo);

      await navigation.getByRole('link', { name: 'Plan y uso', exact: true }).click();

      await expect(page).toHaveURL(/\/org\/usage$/);
      await expect(page.getByTestId('usage-panel')).toContainText('Enterprise');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    });
  });

  test.describe(`Navegación del propietario @viewport:${alias}`, { tag: [...AUTHENTICATED_NAVIGATION] }, () => {
    test.use({ ...viewportUse(alias), storageState: AUTH.owner });

    test('el propietario abre la papelera desde el menú', { tag: ['@outcome:success'] }, async ({ page }, testInfo) => {
      // quality: allow-duplicate (per-viewport contract: layout-authenticated-navigation owner at the five standard viewports)
      // Bug: R-layout-01 esconde Papelera al adaptar la navegación o duplica destinos (NAV-1/NAV-3).
      await enterProjects(page);
      await openNavigation(page);
      const header = page.getByTestId('app-header');
      const navigation = header.getByTestId('app-nav-menu');
      await expect(header.getByRole('navigation')).toHaveCount(1);
      await expect(navigation.getByRole('link')).toHaveText(OWNER_LINKS);
      await assertControlGeometry(page, navigation.getByRole('link').or(navigation.getByRole('button')), testInfo);

      await navigation.getByRole('link', { name: 'Papelera', exact: true }).click();

      await expect(page).toHaveURL(/\/org\/trash$/);
      await expect(page.getByRole('heading', { level: 1 })).toHaveText('Papelera');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    });
  });

  test.describe(`Notificaciones del encabezado @viewport:${alias}`, { tag: [...AUTHENTICATED_NAVIGATION] }, () => {
    test.use({ ...viewportUse(alias), storageState: AUTH.viewer });

    test('la campana permite abrir una notificación', { tag: ['@outcome:display'] }, async ({ page }, testInfo) => {
      // quality: allow-duplicate (per-viewport contract: layout-authenticated-navigation bell at the five standard viewports)
      // Bug: R-layout-02 deja la campana en 36 px o el dropdown de 320 px fuera del viewport (FORM-2/LAY-1).
      await page.route('**/api/me/notifications/', (route) => route.fulfill({
        json: { unread: 1, results: [{ public_id: NOTIFICATION_ID, event_key: 'trial.started',
          title: NOTIFICATION_TITLE, body: 'Revisa el plan y uso de tu organización.', link: '/org/usage',
          payload: {}, read_at: null, created_at: '2026-10-08T00:00:00Z' }] },
      }));
      await page.route(`**/api/me/notifications/${NOTIFICATION_ID}/read/`, (route) => route.fulfill({ status: 204 }));
      await enterProjects(page);
      await openNavigation(page);
      const header = page.getByTestId('app-header');
      await expect(header.getByTestId('notification-badge')).toHaveText('1');
      await header.getByTestId('notification-bell').click();
      const dropdown = header.getByTestId('notification-dropdown');
      await expect(dropdown.getByRole('link').first()).toContainText(NOTIFICATION_TITLE);
      await assertControlGeometry(page, dropdown.getByRole('link'), testInfo);
      const read = page.waitForRequest((request) => request.url().endsWith(`/api/me/notifications/${NOTIFICATION_ID}/read/`) && request.method() === 'POST');

      await dropdown.getByRole('link', { name: new RegExp(NOTIFICATION_TITLE) }).click();

      expect((await read).method()).toBe('POST');
      await expect(page).toHaveURL(/\/org\/usage$/);
      await expect(page.getByTestId('usage-panel')).toContainText('Enterprise');
      await expect(dropdown).toBeHidden();
      await expect(header.getByTestId('notification-badge')).toHaveCount(0);
    });
  });
}

test.describe('Cierre autenticado @viewport:portrait', { tag: [...AUTHENTICATED_NAVIGATION] }, () => {
  test.use({ ...viewportUse('portrait'), storageState: AUTH.owner });

  test('Escape desde un enlace cierra el menú', { tag: ['@outcome:success'] }, async ({ page }) => {
    // Bug: R-layout-01 mantiene el menú autenticado abierto cuando el foco salió del botón (NAV-5).
    await enterProjects(page);
    const toggle = page.getByTestId('app-nav-toggle');
    await toggle.click();
    const link = page.getByTestId('app-nav-menu').getByRole('link', { name: 'Plan y uso', exact: true });
    await link.focus();

    await link.press('Escape');

    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByTestId('app-nav-menu')).toBeHidden();
    await expect(toggle).toBeFocused();
  });

  test('un toque fuera cierra el menú', { tag: ['@outcome:success'] }, async ({ page }) => {
    // Bug: R-layout-01 deja el menú autenticado abierto al tocar el tablero (NAV-5).
    await enterProjects(page);
    const toggle = page.getByTestId('app-nav-toggle');
    await toggle.tap();

    await page.getByRole('heading', { level: 1, name: 'Proyectos', exact: true }).tap();

    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByTestId('app-nav-menu')).toBeHidden();
    await expect(toggle).toBeFocused();
  });
});

test.describe('Salida autenticada @viewport:compact', { tag: [...AUTHENTICATED_NAVIGATION] }, () => {
  test.use({ ...viewportUse('compact'), storageState: AUTH.viewer });

  test('Salir termina la sesión desde el menú compacto', { tag: ['@outcome:success'] }, async ({ page }) => {
    // Bug: R-layout-01 quita Salir de la navegación compacta o deja la sesión activa.
    await enterProjects(page);
    await page.getByTestId('app-nav-toggle').click();

    await page.getByTestId('app-nav-menu').getByRole('button', { name: 'Salir', exact: true }).tap();

    await expect(page).toHaveURL(/\/sign-in$/);
    await expect(page.getByTestId('public-header')).toBeVisible();
    await expect(page.getByTestId('app-header')).toHaveCount(0);
    expect((await page.context().cookies()).map((cookie) => cookie.name)).not.toContain('access_token');
  });
});
