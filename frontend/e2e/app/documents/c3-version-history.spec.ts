import { expect, test } from '../../test-with-coverage';
import { C3_HISTORY } from '../../helpers/flow-tags';
import { createProject, uniqueName, uploadPdf } from '../../helpers/versiona';
import type { Page } from '@playwright/test';

test.use({ storageState: 'e2e/.auth/editor.json' });

test.describe('C3 — Navegar el historial', () => {
  test(
    'C3-F01/F02 — timeline con autor, mensaje y miniatura; descarga por URL firmada',
    { tag: [...C3_HISTORY, '@scenario:c3-f01', '@scenario:c3-f02', '@outcome:display'] },
    async ({ page }) => {
      await createProject(page, uniqueName('Historial'));
      await uploadPdf(page, 'contrato_v1.pdf', { title: 'Contrato H', message: 'v1 inicial' });
      await expect(page.getByText('Contrato H')).toBeVisible({ timeout: 60_000 });
      await page.getByText('Contrato H').click();
      await expect(page.getByTestId('version-item-1')).toBeVisible({ timeout: 15_000 });

      await uploadPdf(page, 'contrato_v2.pdf', { message: 'segunda entrega' });
      await expect(page.getByTestId('version-item-2')).toBeVisible({ timeout: 60_000 });

      // Autor y mensajes visibles por versión (C3-F01)
      await expect(page.getByText('editor@versiona.test').first()).toBeVisible();
      await expect(page.getByText('v1 inicial')).toBeVisible();
      await expect(page.getByText('segunda entrega')).toBeVisible();

      // Descarga: el endpoint entrega una URL firmada (C3-F02)
      const downloadResponse = page.waitForResponse(
        (response) => response.url().includes('/download/') && response.status() === 200
      );
      await page
        .getByTestId('version-item-2')
        .getByRole('button', { name: 'Descargar' })
        .click();
      const response = await downloadResponse;
      const body = await response.json();

      // Backend-agnostic, mirroring backend/documents/tests/views/
      // test_document_endpoints.py: what matters is that the URL is a *signed
      // capability* — it works as handed over and stops working once tampered
      // with. Asserting 'X-Amz-Signature' pinned the storage vendor rather than
      // the behaviour, so it went stale the moment the guarantee came from our
      // own signer instead of S3.
      // Status codes only, never the body: with OBJECT_STORAGE_SENDFILE_ROOT
      // set, delivery is handed to nginx via X-Accel-Redirect and Django
      // answers 200 with an empty body — asserting bytes would pass in CI and
      // fail on every host configured like staging.
      expect((await page.request.get(body.url)).status()).toBe(200);
      expect(
        (await page.request.get(body.url.replace('/api/objects/', '/api/objects/x'))).status()
      ).toBe(403);
    }
  );

  test(
    'C3 — el visor presenta el PDF de la versión elegida desde el historial',
    { tag: [...C3_HISTORY, '@outcome:display'] },
    async ({ page }) => {
      test.slow(); // Two real PDF uploads and analysis cycles precede navigation.
      await openFirstVersionPdf(page);
      await page.goBack();
      await page.getByTestId('version-item-2').getByRole('link', { name: 'Ver documento' }).click();

      const viewer = page.getByTestId('pdf-viewer');
      await expect(page.getByRole('heading', { name: 'Versión v2', exact: true })).toBeVisible();
      await expect(viewer.getByTestId('pdf-page-1').locator('canvas')).toBeVisible({ timeout: 30_000 });
      await expect(viewer.getByText('8. PROTECCION DE DATOS PERSONALES', { exact: true }))
        .toBeVisible({ timeout: 30_000 });
      await expect(viewer.getByText('6. PLAZO DE EJECUCION', { exact: true })).toHaveCount(0);
    }
  );

  test(
    'C3 — un archivo no disponible retira el PDF de la versión anterior',
    { tag: [...C3_HISTORY, '@outcome:failure'] },
    async ({ page }) => {
      test.slow(); // Load a real earlier PDF before exercising a transport failure.
      await openFailedSecondVersion(page);

      await expect(page.getByRole('heading', { name: 'Versión v2', exact: true })).toBeVisible();
      await expect(page.getByTestId('async-error')).toHaveText(/PDF temporalmente no disponible/);
      await expect(page.getByRole('button', { name: 'Reintentar' })).toBeVisible();
      await expect(page.getByTestId('pdf-viewer')).toHaveCount(0);
    }
  );

  test(
    'C3 — reintentar recupera el PDF real de la versión elegida',
    { tag: [...C3_HISTORY, '@outcome:success'] },
    async ({ page }) => {
      test.slow(); // Retry uses the real file endpoint after one synthetic 503.
      await openFailedSecondVersion(page);
      await expect(page.getByTestId('async-error')).toHaveText(/PDF temporalmente no disponible/);
      await expect(page.getByTestId('pdf-viewer')).toHaveCount(0);
      const fileResponse = page.waitForResponse(
        (response) => response.url().endsWith('/file/') && response.status() === 200
      );

      await page.getByRole('button', { name: 'Reintentar' }).click();

      expect((await fileResponse).status()).toBe(200);
      const viewer = page.getByTestId('pdf-viewer');
      await expect(viewer.getByTestId('pdf-page-1').locator('canvas')).toBeVisible({ timeout: 30_000 });
      await expect(viewer.getByText('8. PROTECCION DE DATOS PERSONALES', { exact: true }))
        .toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId('async-error')).toHaveCount(0);
      await expect(viewer.getByText('6. PLAZO DE EJECUCION', { exact: true })).toHaveCount(0);
    }
  );
});

/** Enter through the timeline and load distinguishable fixture content. */
async function openFirstVersionPdf(page: Page) {
  const title = uniqueName('Contrato visor');
  await createProject(page, uniqueName('Historial visor'));
  await uploadPdf(page, 'contrato_v1.pdf', { title, message: 'v1 inicial' });
  const documentLink = page.getByTestId('documents-list').getByRole('link', { name: new RegExp(title) });
  await expect(documentLink).toBeVisible({ timeout: 90_000 });
  await documentLink.click();
  await expect(page.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });
  await uploadPdf(page, 'contrato_v2.pdf', { message: 'segunda entrega' });
  await expect(page.getByTestId('version-item-2')).toBeVisible({ timeout: 90_000 });
  await page.getByTestId('version-item-1').getByRole('link', { name: 'Ver documento' }).click();
  const viewer = page.getByTestId('pdf-viewer');
  await expect(viewer.getByTestId('pdf-page-1').locator('canvas')).toBeVisible({ timeout: 30_000 });
  await expect(viewer.getByText('6. PLAZO DE EJECUCION', { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(viewer.getByText('8. PROTECCION DE DATOS PERSONALES', { exact: true })).toHaveCount(0);
}

/** Fail only the next file transport; every metadata/PDF retry remains real. */
async function openFailedSecondVersion(page: Page) {
  await openFirstVersionPdf(page);
  await page.goBack();
  await page.route('**/versions/*/file/', (route) => route.fulfill({
    status: 503,
    contentType: 'application/json',
    body: JSON.stringify({ error: 'PDF temporalmente no disponible' }),
  }), { times: 1 });
  await page.getByTestId('version-item-2').getByRole('link', { name: 'Ver documento' }).click();
  await expect(page.getByTestId('async-error')).toHaveText(/PDF temporalmente no disponible/);
}
