import path from 'node:path';

import { expect, test } from '../../test-with-coverage';
import { C1_UPLOAD_FIRST } from '../../helpers/flow-tags';
import { TESTDATA, createProject, openSeededProject, uniqueName, uploadPdf } from '../../helpers/versiona';
import { viewportUse, type ViewportAlias } from '../../helpers/viewports';

test.use({ storageState: 'e2e/.auth/editor.json' });

test.describe('C1 — Subir el primer documento', () => {
  test(
    'C1-F01 — drag&drop con preview local, análisis y v1 con secciones indexadas',
    { tag: [...C1_UPLOAD_FIRST, '@scenario:c1-f01', '@scenario:c1-a01', '@outcome:success'] },
    async ({ page }) => {
      await createProject(page, uniqueName('Contratos'));

      await uploadPdf(page, 'contrato_v1.pdf', {
        title: 'Contrato de obra',
        message: 'primera entrega',
      });

      // El job termina, el preview se cierra y la lista muestra el documento
      await expect(page.getByTestId('documents-list')).toBeVisible({ timeout: 90_000 });
      const documentLink = page
        .getByTestId('documents-list')
        .getByRole('link', { name: /Contrato de obra/ });
      await expect(documentLink).toBeVisible();

      // Abrir el timeline: v1 lista con su semáforo de análisis
      await documentLink.click();
      await expect(page.getByTestId('version-item-1')).toBeVisible({ timeout: 15_000 });
      await expect(page.getByText('Versión lista')).toBeVisible();

      // Abrir el visor: las secciones del contrato están indexadas
      await page.getByRole('link', { name: 'Ver documento' }).click();
      await expect(page.getByTestId('sections-list')).toBeVisible({ timeout: 20_000 });
      await expect(page.getByText('1. OBJETO DEL CONTRATO')).toBeVisible();
      await expect(page.getByText('8. RESOLUCION DE CONTROVERSIAS')).toBeVisible();
    }
  );

  test(
    'C1-E01 — un PDF protegido se rechaza con mensaje accionable antes de subir',
    { tag: [...C1_UPLOAD_FIRST, '@scenario:c1-e01', '@outcome:error'] },
    async ({ page }) => {
      await createProject(page, uniqueName('Protegidos'));

      await page
        .getByTestId('upload-input')
        .setInputFiles(path.join(TESTDATA, 'protegido.pdf'));

      // El preview local lo rechaza sin gastar red (kit 1); el backend lo
      // rechaza igual (cubierto en integración: test_version_service).
      await expect(page.getByTestId('pdf-error')).toContainText('contraseña', {
        timeout: 30_000,
      });
      await page.getByRole('button', { name: 'Cancelar' }).click();
      await expect(page.getByTestId('upload-dropzone')).toBeVisible();
    }
  );

  test(
    'C1-F02 — una cuota agotada conserva el borrador y no inicia el análisis',
    { tag: [...C1_UPLOAD_FIRST, '@scenario:c1-f02', '@outcome:failure'] },
    async ({ page }) => {
      // Catches: rendering a 429 as a successful upload, losing the title or
      // message, or starting analysis despite the server issuing no intent.
      await createProject(page, uniqueName('Cuota C1'));
      const title = 'Borrador sin cuota';
      const message = 'Mantener este mensaje para reintentar';
      const intentRoute = async (route: import('@playwright/test').Route) => {
        const url = new URL(route.request().url());
        if (/\/api\/documents\/[^/]+\/versions\/upload_intent\/$/.test(url.pathname)) {
          await route.fulfill({
            status: 429,
            contentType: 'application/json',
            headers: { 'Retry-After': '60' },
            body: JSON.stringify({ detail: 'Request was throttled. Expected available in 60 seconds.' }),
          });
          return;
        }
        await route.fallback();
      };
      await page.route('**/api/documents/*/versions/upload_intent/**', intentRoute);
      await page.getByTestId('upload-input').setInputFiles(path.join(TESTDATA, 'contrato_v1.pdf'));
      await page.getByTestId('upload-title').fill(title);
      await page.getByTestId('upload-message').fill(message);
      await page.getByTestId('upload-confirm').click();
      await expect(page.getByTestId('upload-error')).toHaveText(
        'Alcanzaste el límite de subidas. Espera 60 segundos y vuelve a intentarlo.'
      );
      await expect(page.getByTestId('upload-title')).toHaveValue(title);
      await expect(page.getByTestId('upload-message')).toHaveValue(message);
      await expect(page.getByTestId('upload-analyzing')).toHaveCount(0);
      await page.unroute('**/api/documents/*/versions/upload_intent/**', intentRoute);
    }
  );
});

for (const alias of ['compact', 'portrait', 'landscape', 'desktop', 'wide'] as ViewportAlias[]) {
  test.describe(`C1 PDF @viewport:${alias}`, () => {
    test.use(viewportUse(alias));
    test.slow(); // Real upload analysis and cold compilation of the version viewer.

    test('la vista previa conserva la página completa al subir un contrato',
      { tag: [...C1_UPLOAD_FIRST, '@outcome:success'] }, async ({ page }, testInfo) => {
        // quality: allow-duplicate (per-viewport contract: c1-upload-first-document PDF fit at the five standard viewports)
        // Bug: el canvas fijo de 420/760 px supera el contenido del modal/visor a 412 px (LAY-1/MED-1).
        const title = uniqueName(`Contrato responsive ${alias}`);
        await openSeededProject(page);
        await page.getByTestId('upload-input').setInputFiles(path.join(TESTDATA, 'contrato_v1.pdf'));
        const preview = page.getByRole('dialog').getByTestId('pdf-viewer');
        await expect(preview.locator('canvas').first()).toBeVisible({ timeout: 30_000 });
        const previewGeometry = await preview.evaluate((viewer) => ({
          availableWidth: viewer.getBoundingClientRect().width,
          renderedWidth: viewer.querySelector('canvas')!.getBoundingClientRect().width,
        }));
        await testInfo.attach('pdf-preview-geometry', {
          body: Buffer.from(JSON.stringify({ viewport: page.viewportSize(), ...previewGeometry })),
          contentType: 'application/json',
        });
        await expect.poll(() => preview.evaluate((viewer) => {
          const bounds = viewer.getBoundingClientRect();
          const canvas = viewer.querySelector('canvas')!.getBoundingClientRect();
          return canvas.left >= bounds.left && canvas.right <= bounds.right && canvas.width <= 420;
        })).toBe(true);
        await page.getByTestId('upload-title').fill(title);
        await page.getByTestId('upload-confirm').click();
        await expect(page.getByRole('dialog')).toBeHidden({ timeout: 90_000 });
        await page.getByTestId('documents-list').getByRole('link', { name: new RegExp(title) }).click();
        await page.getByRole('link', { name: 'Ver documento' }).click();
        await expect(page.getByTestId('sections-list')).toContainText('1. OBJETO DEL CONTRATO');
        const viewer = page.getByTestId('pdf-viewer');
        await expect(viewer.locator('canvas').first()).toBeVisible({ timeout: 30_000 });
        await expect.poll(() => viewer.evaluate((element) => {
          const bounds = element.getBoundingClientRect();
          const canvas = element.querySelector('canvas')!.getBoundingClientRect();
          return canvas.left >= bounds.left && canvas.right <= bounds.right && canvas.width <= 760;
        })).toBe(true);
      });
  });
}
