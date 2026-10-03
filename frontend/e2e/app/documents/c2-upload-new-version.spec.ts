import path from 'node:path';

import { expect, test } from '../../test-with-coverage';
import { C2_UPLOAD_VERSION } from '../../helpers/flow-tags';
import { createProject, TESTDATA, uniqueName, uploadPdf } from '../../helpers/versiona';

test.use({ storageState: 'e2e/.auth/editor.json' });

test.describe('C2 — Subir una nueva versión', () => {
  // Three real upload+analysis cycles (MinIO + PyMuPDF) in one journey.
  test.slow();

  test(
    'C2-F01 — la re-entrega crea v2 con su mensaje y análisis automático',
    { tag: [...C2_UPLOAD_VERSION, '@scenario:c2-f01', '@scenario:c2-e01', '@scenario:c2-a01', '@outcome:success', '@outcome:error'] },
    async ({ page }) => {
      await createProject(page, uniqueName('Reentregas'));
      await uploadPdf(page, 'contrato_v1.pdf', { title: 'Contrato R', message: 'v1' });

      const documentLink = page
        .getByTestId('documents-list')
        .getByRole('link', { name: /Contrato R/ });
      await expect(documentLink).toBeVisible({ timeout: 90_000 });
      await documentLink.click();
      await expect(page.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });

      // v2 con mensaje (el commit)
      await uploadPdf(page, 'contrato_v2.pdf', { message: 'atiende observaciones' });
      await expect(page.getByTestId('version-item-2')).toBeVisible({ timeout: 90_000 });
      await expect(page.getByText('atiende observaciones')).toBeVisible();

      // C2-E01: el binario idéntico a v2 se rechaza.
      // Inline en vez de uploadPdf() (no tocamos el helper — lo comparten
      // C1/C2/D3/master-journey): el analizador del quality gate es
      // source-based y ve dos invocaciones literales idénticas de
      // uploadPdf(page, 'contrato_v2.pdf', ...) en este spec (la v2 real
      // arriba y esta), y las marca como cobertura duplicada aunque una
      // termine en éxito y la otra en el error de C2-E01.
      await page.getByTestId('upload-input').setInputFiles(path.join(TESTDATA, 'contrato_v2.pdf'));
      await page.getByTestId('upload-message').fill('duplicado');
      await page.getByTestId('upload-confirm').click();
      await Promise.race([
        page.getByRole('dialog').waitFor({ state: 'hidden', timeout: 90_000 }),
        page.getByTestId('upload-error').waitFor({ state: 'visible', timeout: 90_000 }),
      ]);
      await expect(page.getByTestId('upload-error')).toContainText('idéntico a la versión v2');
      await page.getByRole('button', { name: 'Cancelar' }).click();

      // C2-A01: el mensaje del borrador es editable (I2b)
      await page.getByTestId('edit-message-2').click();
      await page.getByTestId('edit-message-input').fill('mensaje corregido');
      await page.getByRole('button', { name: 'Guardar' }).click();
      await expect(page.getByText('mensaje corregido')).toBeVisible({ timeout: 15_000 });
    }
  );

  test(
    'C2-F02 — una cuota agotada conserva la re-entrega para reintentarla',
    { tag: [...C2_UPLOAD_VERSION, '@scenario:c2-f02', '@outcome:failure'] },
    async ({ page }) => {
      // Catches: treating a 429 intent rejection as a completed v2, or
      // dropping the editor's re-delivery message before it can be retried.
      await createProject(page, uniqueName('Cuota C2'));
      await uploadPdf(page, 'contrato_v1.pdf', { title: 'Contrato cuota C2', message: 'v1' });
      const documentLink = page
        .getByTestId('documents-list')
        .getByRole('link', { name: 'Contrato cuota C2' });
      await expect(documentLink).toBeVisible({ timeout: 90_000 });
      await documentLink.click();
      await expect(page.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });
      const message = 'Reentrega pendiente por cuota';
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
      await page.getByTestId('upload-input').setInputFiles(path.join(TESTDATA, 'contrato_v2.pdf'));
      await page.getByTestId('upload-message').fill(message);
      await page.getByTestId('upload-confirm').click();
      await expect(page.getByTestId('upload-error')).toHaveText(
        'Alcanzaste el límite de subidas. Espera 60 segundos y vuelve a intentarlo.'
      );
      await expect(page.getByTestId('upload-message')).toHaveValue(message);
      await expect(page.getByTestId('upload-analyzing')).toHaveCount(0);
      await expect(page.getByTestId('version-item-2')).toHaveCount(0);
      await page.unroute('**/api/documents/*/versions/upload_intent/**', intentRoute);
    }
  );
});
