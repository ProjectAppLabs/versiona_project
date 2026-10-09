import path from 'node:path';

import type { Locator } from '@playwright/test';

import { expect, test } from '../../test-with-coverage';
import { C2_UPLOAD_VERSION } from '../../helpers/flow-tags';
import { viewportUse } from '../../helpers/viewports';
import { createProject, TESTDATA, uniqueName, uploadPdf } from '../../helpers/versiona';

test.use({ storageState: 'e2e/.auth/editor.json' });

/** Expected geometry of every touch control (RESPONSIVE_STANDARDS FORM-2). */
const TOUCH_TARGET_OK = { tallEnough: true, wideEnough: true, insideViewport: true };

async function touchTarget(control: Locator) {
  return control.evaluate((element) => {
    const box = element.getBoundingClientRect();
    return {
      tallEnough: box.height >= 44,
      wideEnough: box.width >= 44,
      insideViewport: box.left >= 0 && box.right <= window.innerWidth,
    };
  });
}

/** A version message shown whole, never cut by truncate/ellipsis (TIP-2). */
const TEXT_UNCLIPPED = { horizontallyClipped: false, hasEllipsis: false, hasNoWrap: false };

async function textClipping(text: Locator) {
  return text.evaluate((element) => {
    const style = window.getComputedStyle(element);
    return {
      horizontallyClipped: element.scrollWidth > element.clientWidth,
      hasEllipsis: style.textOverflow === 'ellipsis',
      hasNoWrap: style.whiteSpace === 'nowrap',
    };
  });
}

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

  test.describe('línea de tiempo @ 412 (celular)', () => {
    test.use(viewportUse('compact'));

    test(
      'C2-R01 — a 412 px el editor corrige el mensaje largo de su borrador',
      { tag: [...C2_UPLOAD_VERSION, '@scenario:c2-r01', '@outcome:success', '@viewport:compact'] },
      async ({ page }) => {
        // quality: allow-duplicate (per-viewport contract: c2-upload-version @ 412)
        // Bug que atrapa (R-documents-01): el párrafo `truncate` del mensaje recortaba
        // «Editar mensaje» fuera de la línea a 412 px, la única forma de editarlo (I2b).
        const title = uniqueName('Contrato compacto');
        const message = 'atiende observaciones del revisor jurídico';
        const corrected = 'corrige la cláusula de penalidades';
        await createProject(page, uniqueName('Reentregas compactas'));
        await uploadPdf(page, 'contrato_v1.pdf', { title, message: 'v1' });
        const documentLink = page.getByTestId('documents-list').getByRole('link', { name: title });
        await expect(documentLink).toBeVisible({ timeout: 90_000 });
        await documentLink.click();
        await expect(page.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });
        await uploadPdf(page, 'contrato_v2.pdf', { message });
        await expect(page.getByTestId('version-item-2')).toContainText(message, { timeout: 90_000 });

        const editButton = page.getByTestId('edit-message-2');
        expect(await touchTarget(editButton)).toEqual(TOUCH_TARGET_OK);
        await editButton.tap();
        const editInput = page.getByTestId('edit-message-input');
        await expect(editInput).toHaveCSS('font-size', '16px');
        await editInput.fill(corrected);
        await page.getByRole('button', { name: 'Guardar' }).tap();

        await expect(page.getByTestId('version-item-2')).toContainText(corrected, { timeout: 15_000 });
        expect(await textClipping(page.getByTestId('version-item-2').getByText(corrected))).toEqual(TEXT_UNCLIPPED);
        await expect
          .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
          .toBe(true);
      }
    );

    test(
      'C2-R02 — a 412 px la re-entrega se compara con la versión anterior desde la línea de tiempo',
      { tag: [...C2_UPLOAD_VERSION, '@scenario:c2-r02', '@outcome:success', '@viewport:compact'] },
      async ({ page }) => {
        // quality: allow-duplicate (per-viewport contract: c2-upload-version @ 412)
        // Bug que atrapa (R-documents-02): campos de 14 px (zoom de iOS), botones de
        // 36 px y casillas de 13 px al subir la re-entrega y elegirla para comparar.
        const title = uniqueName('Contrato táctil');
        await createProject(page, uniqueName('Comparación compacta'));
        await uploadPdf(page, 'contrato_v1.pdf', { title, message: 'v1' });
        const documentLink = page.getByTestId('documents-list').getByRole('link', { name: title });
        await expect(documentLink).toBeVisible({ timeout: 90_000 });
        await documentLink.click();
        await expect(page.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });

        await page.getByTestId('upload-input').setInputFiles(path.join(TESTDATA, 'contrato_v2.pdf'));
        const messageInput = page.getByTestId('upload-message');
        await expect(messageInput).toHaveCSS('font-size', '16px');
        await messageInput.fill('segunda entrega');
        const confirmUpload = page.getByTestId('upload-confirm');
        expect(await touchTarget(confirmUpload)).toEqual(TOUCH_TARGET_OK);
        await confirmUpload.tap();
        await expect(page.getByRole('dialog')).toBeHidden({ timeout: 90_000 });

        const selectFirst = page.getByTestId('select-version-1');
        const selectSecond = page.getByTestId('select-version-2');
        expect(await touchTarget(selectFirst.locator('..'))).toEqual(TOUCH_TARGET_OK);
        await selectFirst.locator('..').tap();
        await selectSecond.locator('..').tap();
        await expect(selectSecond).toBeChecked();
        const compareButton = page.getByTestId('compare-selected');
        expect(await touchTarget(compareButton)).toEqual(TOUCH_TARGET_OK);
        await compareButton.tap();

        await expect(page).toHaveURL(/\/compare\/[^/]+\/[^/]+/);
        await expect(page.getByText('2 modificadas, 1 eliminada, 1 agregada')).toBeVisible({ timeout: 30_000 });
      }
    );
  });
});
