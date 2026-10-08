import type { Locator, Page, TestInfo } from '@playwright/test';
import { expect, test } from '../test-with-coverage';
import { viewportUse, type ViewportAlias } from '../helpers/viewports';

const PUBLIC_NAVIGATION = ['@flow:layout-public-navigation', '@module:home', '@priority:P2'];
const LINKS = ['Comparar PDFs', 'Precios', 'Manual', 'Iniciar sesión', 'Crear cuenta gratis'];

async function openCompactNavigation(page: Page) {
  const toggle = page.getByTestId('public-nav-toggle');
  await expect(toggle).toBeVisible();
  const box = (await toggle.boundingBox())!;
  expect(box.width).toBeGreaterThanOrEqual(44);
  expect(box.height).toBeGreaterThanOrEqual(44);
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
}

async function useDesktopNavigation(page: Page) {
  await expect(page.getByTestId('public-nav-toggle')).toBeHidden();
}

const VARIANTS: Array<{ alias: ViewportAlias; openNavigation: (page: Page) => Promise<void> }> = [
  { alias: 'compact', openNavigation: openCompactNavigation },
  { alias: 'portrait', openNavigation: openCompactNavigation },
  { alias: 'landscape', openNavigation: useDesktopNavigation },
  { alias: 'desktop', openNavigation: useDesktopNavigation },
  { alias: 'wide', openNavigation: useDesktopNavigation },
];

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
  test.describe(`Navegación pública @viewport:${alias}`, { tag: [...PUBLIC_NAVIGATION] }, () => {
    test.use({ ...viewportUse(alias), storageState: { cookies: [], origins: [] } });

    test('el manual se alcanza desde la navegación principal', { tag: ['@outcome:success'] }, async ({ page }, testInfo) => {
      // quality: allow-duplicate (per-viewport contract: layout-public-navigation at the five standard viewports)
      // Bug: la fila md de R-layout-01 desborda 835 px o deja el menú compacto sin destinos (NAV-1/NAV-3).
      await page.goto('/');
      await openNavigation(page);
      const header = page.getByTestId('public-header');
      const navigation = header.getByTestId('public-nav-menu');
      await expect(header.getByRole('navigation')).toHaveCount(1);
      await expect(navigation.getByRole('link')).toHaveText(LINKS);
      await assertControlGeometry(page, navigation.getByRole('link').or(navigation.getByRole('button')), testInfo);

      await navigation.getByRole('link', { name: 'Manual', exact: true }).click();

      await expect(page).toHaveURL(/\/manual$/);
      await expect(page.getByRole('heading', { level: 1 })).toContainText('Manual');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    });

    test('el tema oscuro se elige desde el encabezado', { tag: ['@outcome:display'] }, async ({ page }, testInfo) => {
      // quality: allow-duplicate (per-viewport contract: layout-public-navigation theme control at the five standard viewports)
      // Bug: R-layout-02 reduce el botón a 36 px o coloca las opciones fuera del viewport (FORM-2/TAC-4).
      await page.goto('/');
      await openNavigation(page);
      const header = page.getByTestId('public-header');
      const toggle = header.getByRole('button', { name: 'Toggle theme' });
      await toggle.click();
      const themeMenu = header.getByRole('menu', { name: 'Theme', exact: true });
      await assertControlGeometry(page, themeMenu.getByRole('menuitemradio'), testInfo);

      await themeMenu.getByRole('menuitemradio', { name: 'Dark', exact: true }).click();

      await expect(page.locator('html')).toHaveClass(/dark/);
      expect(await page.evaluate(() => localStorage.getItem('theme'))).toBe('dark');
      await expect(toggle).toBeFocused();
      await expect(header.getByTestId('public-nav-menu').getByRole('link')).toHaveText(LINKS);
    });
  });
}

for (const alias of ['compact', 'portrait'] as const) {
  test.describe(`Cierre público @viewport:${alias}`, { tag: [...PUBLIC_NAVIGATION] }, () => {
    test.use({ ...viewportUse(alias), storageState: { cookies: [], origins: [] } });

    test('el botón cierra el menú', { tag: ['@outcome:success'] }, async ({ page }) => {
      // quality: allow-duplicate (per-viewport contract: layout-public-navigation closure at compact and portrait)
      // Bug: R-layout-01 no ofrece cierre táctil o pierde el foco del botón (NAV-5).
      await page.goto('/');
      const toggle = page.getByTestId('public-nav-toggle');
      await toggle.tap();

      await toggle.tap();

      await expect(toggle).toHaveAttribute('aria-expanded', 'false');
      await expect(page.getByTestId('public-nav-menu')).toBeHidden();
      await expect(toggle).toBeFocused();
    });

    test('Escape desde un enlace cierra el menú', { tag: ['@outcome:success'] }, async ({ page }) => {
      // quality: allow-duplicate (per-viewport contract: layout-public-navigation closure at compact and portrait)
      // Bug: R-layout-01 escucha Escape sólo en el botón, no desde los enlaces (NAV-5).
      await page.goto('/');
      const toggle = page.getByTestId('public-nav-toggle');
      await toggle.click();
      const link = page.getByTestId('public-nav-menu').getByRole('link', { name: 'Manual', exact: true });
      await link.focus();

      await link.press('Escape');

      await expect(toggle).toHaveAttribute('aria-expanded', 'false');
      await expect(page.getByTestId('public-nav-menu')).toBeHidden();
      await expect(toggle).toBeFocused();
    });

    test('un toque fuera cierra el menú', { tag: ['@outcome:success'] }, async ({ page }) => {
      // quality: allow-duplicate (per-viewport contract: layout-public-navigation closure at compact and portrait)
      // Bug: R-layout-01 mantiene el menú abierto al tocar el contenido (NAV-5).
      await page.goto('/');
      const toggle = page.getByTestId('public-nav-toggle');
      await toggle.tap();

      await page.getByRole('heading', { level: 1 }).tap();

      await expect(toggle).toHaveAttribute('aria-expanded', 'false');
      await expect(page.getByTestId('public-nav-menu')).toBeHidden();
      await expect(toggle).toBeFocused();
    });
  });
}

test.describe('Idioma público @viewport:portrait', { tag: [...PUBLIC_NAVIGATION] }, () => {
  test.use({ ...viewportUse('portrait'), storageState: { cookies: [], origins: [] } });

  test('el menú traducido conserva el destino de precios', { tag: ['@outcome:success'] }, async ({ page }, testInfo) => {
    // Bug: R-layout-01 oculta el cambio de idioma en tableta o duplica los enlaces por variante (NAV-1/NAV-3).
    await page.goto('/');
    await page.getByTestId('public-nav-toggle').click();
    const navigation = page.getByTestId('public-nav-menu');

    await navigation.getByRole('button', { name: 'Switch to English' }).click();

    await expect(navigation.getByRole('link')).toHaveText(['Compare PDFs', 'Pricing', 'Manual', 'Sign in', 'Create free account']);
    await assertControlGeometry(page, navigation.getByRole('link').or(navigation.getByRole('button')), testInfo);
    await navigation.getByRole('link', { name: 'Pricing', exact: true }).click();
    await expect(page).toHaveURL(/\/precios$/);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Plans & pricing');
  });
});
