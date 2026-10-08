import { expect, test } from '../../test-with-coverage';
import { D5_SELECTIVE_INVALIDATION } from '../../helpers/flow-tags';
import { assertNoEmailFor, purgeMailbox, waitForEmail } from '../../helpers/mailpit';
import { openSeededProject, uniqueName, uploadPdf } from '../../helpers/versiona';

/**
 * LA PRUEBA REINA (docs/plan/06 §5.2 — el diferencial del producto):
 * revisor A sella §1–2 · revisor B sella §3 · el editor sube v2 que cambia §3
 * (y otras, pero NO las de A) ⇒ el sello de A se CONSERVA con constancia, el
 * de B se INVALIDA, y SOLO B recibe el correo (S6). Multi-contexto real.
 */

test.describe('D5 — Invalidación selectiva 💎', () => {
  test.slow(); // three uploads + analysis + three browser contexts

  test(
    'D5-F01/F02/F05/F06 — conserva el sello original de A hasta v3',
    { tag: [...D5_SELECTIVE_INVALIDATION, '@scenario:d5-f01', '@scenario:d5-f02', '@scenario:d5-f05', '@scenario:d5-f06', '@outcome:success'] },
    async ({ browser }) => {
      await purgeMailbox();

      // ── Editor: proyecto + v1 ─────────────────────────────────────────
      const editorContext = await browser.newContext({ storageState: 'e2e/.auth/editor.json' });
      const editorPage = await editorContext.newPage();
      await openSeededProject(editorPage);
      const title = uniqueName('Contrato D5');
      await uploadPdf(editorPage, 'contrato_v1.pdf', { title, message: 'v1' });
      const documentLink = editorPage
        .getByTestId('documents-list')
        .getByRole('link', { name: title });
      await expect(documentLink).toBeVisible({ timeout: 90_000 });
      await documentLink.click();
      await expect(editorPage.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });
      const timelineUrl = editorPage.url();
      await editorPage.getByRole('link', { name: 'Ver documento' }).click();
      await editorPage.waitForURL(/versions\//);
      const v1Url = editorPage.url();

      // ── Revisor A sella §1 y §2 (secciones que v2 NO tocará) ──────────
      const contextA = await browser.newContext({ storageState: 'e2e/.auth/reviewer.json' });
      const pageA = await contextA.newPage();
      await pageA.goto(v1Url);
      await expect(pageA.getByTestId('seal-action-bar')).toBeVisible({ timeout: 20_000 });
      await pageA.getByTestId('seal-sections-open').click();
      await pageA.getByTestId('pick-objeto-del-contrato').check();
      await pageA.getByTestId('pick-definiciones').check();
      await pageA.getByTestId('seal-picked').click();
      await expect(pageA.getByTestId('seal-reviewer@versiona.test')).toBeVisible({
        timeout: 20_000,
      });

      // ── Revisor B (usuario admin del seed) sella §3 ───────────────────
      const contextB = await browser.newContext({ storageState: 'e2e/.auth/admin.json' });
      const pageB = await contextB.newPage();
      await pageB.goto(v1Url);
      await expect(pageB.getByTestId('seal-action-bar')).toBeVisible({ timeout: 20_000 });
      await pageB.getByTestId('seal-sections-open').click();
      await pageB.getByTestId('pick-obligaciones-del-contratista').check();
      await pageB.getByTestId('seal-picked').click();
      await expect(pageB.getByTestId('seal-admin@versiona.test')).toBeVisible({
        timeout: 20_000,
      });

      // ── Editor sube v2 (cambia §3 y §5, elimina §6, renumera 7/8) ─────
      await editorPage.goto(timelineUrl);
      await uploadPdf(editorPage, 'contrato_v2.pdf', { message: 'v2: atiende multas' });
      await expect(editorPage.getByTestId('version-item-2')).toBeVisible({ timeout: 90_000 });

      // ── El visor de v2 muestra el veredicto selectivo de D5 ───────────
      await editorPage
        .getByTestId('version-item-2')
        .getByRole('link', { name: 'Ver documento' })
        .click();
      await editorPage.waitForURL(/versions\//);

      const preservedCard = editorPage.getByTestId('validity-reviewer@versiona.test');
      await expect(preservedCard).toBeVisible({ timeout: 30_000 });
      await expect(preservedCard).toHaveAttribute('data-decision', 'preserved');
      await expect(preservedCard).toContainText('Conservado');
      await expect(preservedCard).toContainText('igualdad de hash verificada');

      const invalidatedCard = editorPage.getByTestId('validity-admin@versiona.test');
      await expect(invalidatedCard).toHaveAttribute('data-decision', 'invalidated');
      await expect(invalidatedCard).toContainText('Requiere re-revisión');
      await expect(invalidatedCard).toContainText('obligaciones-del-contratista');

      // ── B tiene la re-revisión en su campanita e inbox ────────────────
      await pageB.goto('/inbox');
      await expect(
        pageB.getByTestId('inbox-item-seal.invalidated').first()
      ).toBeVisible({ timeout: 20_000 });
      await expect(pageB.getByText(/re-revisión/).first()).toBeVisible();

      // ── S6 por correo: B recibió email; A NO recibió nada ─────────────
      await waitForEmail({ to: 'admin@versiona.test', subjectContains: 're-revisión' });
      await assertNoEmailFor('reviewer@versiona.test');

      // ── A no tiene notificación de invalidación (su sello vive) ───────
      await pageA.goto('/inbox');
      await expect(pageA.getByTestId('inbox-list')).toHaveCount(0, { timeout: 15_000 });

      // ── v3 conserva el MISMO sello de v1 sin volver a sellar v2 ───────
      await editorPage.goto(timelineUrl);
      await uploadPdf(editorPage, 'contrato_v3.pdf', { message: 'v3: notificación previa' });
      await expect(editorPage.getByTestId('version-item-3')).toBeVisible({ timeout: 90_000 });
      await editorPage
        .getByTestId('version-item-3')
        .getByRole('link', { name: 'Ver documento' })
        .click();
      await editorPage.waitForURL(/versions\//);
      const inheritedCard = editorPage.getByTestId('validity-reviewer@versiona.test');
      await expect(inheritedCard).toHaveAttribute('data-decision', 'preserved', { timeout: 30_000 });
      await expect(inheritedCard).toContainText('v1');
      await expect(inheritedCard).toContainText('igualdad de hash verificada');
      await expect(editorPage.getByTestId('validity-admin@versiona.test')).toHaveCount(0);
      await assertNoEmailFor('reviewer@versiona.test');

      await editorContext.close();
      await contextA.close();
      await contextB.close();
    }
  );
});
