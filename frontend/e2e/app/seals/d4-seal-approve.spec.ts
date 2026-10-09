import type { Locator } from '@playwright/test';

import { expect, test } from '../../test-with-coverage';
import { D4_SEAL_APPROVE } from '../../helpers/flow-tags';
import { viewportUse } from '../../helpers/viewports';
import { AUTH, openSeededProject, uniqueName, uploadPdf } from '../../helpers/versiona';

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

test.describe('D4 — Aprobar con sello', () => {
  test.slow(); // real upload + analysis before sealing

  test(
    'D4-F01/F02 — el revisor sella el documento completo, la firma verifica y la versión queda aprobada',
    { tag: [...D4_SEAL_APPROVE, '@scenario:d4-f01', '@scenario:d4-f02', '@outcome:success'] },
    async ({ browser }) => {
      // Editor prepares the document
      const editorContext = await browser.newContext({ storageState: 'e2e/.auth/editor.json' });
      const editorPage = await editorContext.newPage();
      await openSeededProject(editorPage);
      const title = uniqueName('Contrato D4');
      await uploadPdf(editorPage, 'contrato_v1.pdf', { title, message: 'v1' });
      const documentLink = editorPage
        .getByTestId('documents-list')
        .getByRole('link', { name: title });
      await expect(documentLink).toBeVisible({ timeout: 90_000 });
      await documentLink.click();
      await expect(editorPage.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });
      await editorPage.getByRole('link', { name: 'Ver documento' }).click();
      await editorPage.waitForURL(/versions\//);
      const versionUrl = editorPage.url();

      // El editor NO ve la barra de sellado (oculto por rol)
      await expect(editorPage.getByTestId('seals-panel')).toBeVisible({ timeout: 20_000 });
      await expect(editorPage.getByTestId('seal-action-bar')).toHaveCount(0);

      // Reviewer seals the whole document
      const reviewerContext = await browser.newContext({
        storageState: 'e2e/.auth/reviewer.json',
      });
      const reviewerPage = await reviewerContext.newPage();
      await reviewerPage.goto(versionUrl);
      await expect(reviewerPage.getByTestId('seal-action-bar')).toBeVisible({ timeout: 20_000 });
      await reviewerPage.getByTestId('seal-all').click();

      // El sello aparece con su titular y la versión queda aprobada (I10)
      await expect(
        reviewerPage.getByTestId('seal-reviewer@versiona.test')
      ).toBeVisible({ timeout: 20_000 });
      await expect(
        reviewerPage.getByTestId('status-badge').filter({ hasText: 'Aprobada' })
      ).toBeVisible({ timeout: 15_000 });

      // D4-F02: la firma Ed25519 verifica desde la UI
      await reviewerPage.getByTestId(/verify-/).click();
      await expect(
        reviewerPage.getByText(/Firma Ed25519 válida/)
      ).toBeVisible({ timeout: 15_000 });

      await editorContext.close();
      await reviewerContext.close();
    }
  );

  test(
    'D4-E01 — retirar un sello de una versión ya aprobada es rechazado (I5)',
    { tag: [...D4_SEAL_APPROVE, '@scenario:d4-e01', '@outcome:error'] },
    async ({ browser }) => {
      // Crown-jewel invariant I5 ("Immutability is the product"): catches a
      // regression where `revoke_seal`'s post-approval guard is weakened,
      // letting an approved version's supporting seal be pulled after the fact.
      const editorContext = await browser.newContext({ storageState: 'e2e/.auth/editor.json' });
      const editorPage = await editorContext.newPage();
      await openSeededProject(editorPage);
      const title = uniqueName('Contrato D4 Retiro');
      await uploadPdf(editorPage, 'contrato_v1.pdf', { title, message: 'v1' });
      const documentLink = editorPage
        .getByTestId('documents-list')
        .getByRole('link', { name: title });
      await expect(documentLink).toBeVisible({ timeout: 90_000 });
      await documentLink.click();
      await expect(editorPage.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });
      await editorPage.getByRole('link', { name: 'Ver documento' }).click();
      await editorPage.waitForURL(/versions\//);
      const versionUrl = editorPage.url();

      // Reviewer seals the whole document, reaching full approval
      const reviewerContext = await browser.newContext({
        storageState: 'e2e/.auth/reviewer.json',
      });
      const reviewerPage = await reviewerContext.newPage();
      await reviewerPage.goto(versionUrl);
      await expect(reviewerPage.getByTestId('seal-action-bar')).toBeVisible({ timeout: 20_000 });
      await reviewerPage.getByTestId('seal-all').click();
      await expect(
        reviewerPage.getByTestId('seal-reviewer@versiona.test')
      ).toBeVisible({ timeout: 20_000 });
      await expect(
        reviewerPage.getByTestId('status-badge').filter({ hasText: 'Aprobada' })
      ).toBeVisible({ timeout: 15_000 });

      // Intenta retirar el sello que sostiene esa aprobación
      await reviewerPage.getByTestId('withdraw-seal').click();
      await reviewerPage.getByTestId('type-to-confirm-input').fill('v1');
      await reviewerPage.getByTestId('type-to-confirm-submit').click();

      await expect(reviewerPage.getByTestId('toaster')).toContainText(
        'La versión ya está aprobada: los sellos que la sustentan son inmutables (I5).',
        { timeout: 15_000 }
      );

      // El sello sigue vivo — no fue revocado
      await reviewerPage.reload();
      await expect(
        reviewerPage.getByTestId('seal-reviewer@versiona.test')
      ).toBeVisible({ timeout: 20_000 });

      await editorContext.close();
      await reviewerContext.close();
    }
  );

  test.describe('sellado @ 835 (tableta vertical)', () => {
    test.use(viewportUse('portrait'));

    test(
      'D4-R01 — a 835 px el revisor sella una sección desde el selector táctil',
      { tag: [...D4_SEAL_APPROVE, '@scenario:d4-r01', '@outcome:success', '@viewport:portrait'] },
      async ({ browser }) => {
        // quality: allow-duplicate (per-viewport contract: d4-seal-approve @ 835)
        // Bug que atrapa (R-review-01): en tableta vertical las filas del selector medían
        // 32 px, los botones de sellado 36–38 px y «Retirar mi sello» 16 px.
        const editorContext = await browser.newContext({ storageState: AUTH.editor });
        const reviewerContext = await browser.newContext({ storageState: AUTH.reviewer });
        try {
          const editorPage = await editorContext.newPage();
          await openSeededProject(editorPage);
          const title = uniqueName('Contrato D4 tableta');
          await uploadPdf(editorPage, 'contrato_v1.pdf', { title, message: 'v1' });
          await expect(
            editorPage.getByTestId('documents-list').getByRole('link', { name: title })
          ).toBeVisible({ timeout: 90_000 });

          const reviewerPage = await reviewerContext.newPage();
          await openSeededProject(reviewerPage);
          await reviewerPage.getByTestId('documents-list').getByRole('link', { name: title }).tap();
          await expect(reviewerPage.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });
          await reviewerPage.getByTestId('version-item-1').getByRole('link', { name: 'Ver documento' }).tap();
          await reviewerPage.waitForURL(/versions\//);

          const openPicker = reviewerPage.getByTestId('seal-sections-open');
          await expect(openPicker).toBeVisible({ timeout: 20_000 });
          expect(await touchTarget(openPicker)).toEqual(TOUCH_TARGET_OK);
          await openPicker.tap();
          const sectionRow = reviewerPage.getByTestId('pick-obligaciones-del-contratista').locator('..');
          expect(await touchTarget(sectionRow)).toEqual(TOUCH_TARGET_OK);
          await sectionRow.tap();
          const sealPicked = reviewerPage.getByTestId('seal-picked');
          expect(await touchTarget(sealPicked)).toEqual(TOUCH_TARGET_OK);
          await sealPicked.tap();

          const seal = reviewerPage.getByTestId('seal-reviewer@versiona.test');
          await expect(seal).toContainText('1 secciones: obligaciones-del-contratista', { timeout: 20_000 });
          expect(await touchTarget(seal.getByTestId('withdraw-seal'))).toEqual(TOUCH_TARGET_OK);
        } finally {
          await Promise.all([editorContext.close(), reviewerContext.close()]);
        }
      }
    );
  });
});
