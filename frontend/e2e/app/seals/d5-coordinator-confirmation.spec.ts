import { expect, test } from '../../test-with-coverage';
import { D5_SELECTIVE_INVALIDATION } from '../../helpers/flow-tags';
import { assertNoEmailFor, purgeMailbox, waitForEmail } from '../../helpers/mailpit';
import { AUTH, openSeededProject, uniqueName, uploadPdf } from '../../helpers/versiona';

test.describe('D5 — Confirmación coordinada de una entrega degradada', () => {
  test.slow();

  test(
    'D5-A04 — el coordinador confirma la invalidación de una entrega degradada',
    { tag: [...D5_SELECTIVE_INVALIDATION, '@scenario:d5-a04', '@outcome:success'] },
    async ({ browser }) => {
      // Catches: losing the degraded checkpoint flag before D5, notifying the
      // reviewer before a human decision, or confirming without persisting it.
      const editorContext = await browser.newContext({ storageState: AUTH.editor });
      const reviewerContext = await browser.newContext({ storageState: AUTH.reviewer });
      const adminContext = await browser.newContext({ storageState: AUTH.admin });

      try {
        const editorPage = await editorContext.newPage();
        const reviewerPage = await reviewerContext.newPage();
        const adminPage = await adminContext.newPage();
        const title = uniqueName('D5 coordinador degradado');

        // A coordinator configuration would hide a broken degraded adapter.
        // Inspect the shared project without changing its pinned configuration.
        await openSeededProject(adminPage);
        await adminPage.getByTestId('project-settings-link').click();
        await adminPage.waitForURL(/\/settings$/);
        await expect(adminPage.getByTestId('project-config')).toBeVisible();
        await expect(adminPage.getByTestId('config-d5-mode')).toHaveValue('auto');

        await openSeededProject(editorPage);
        await uploadPdf(editorPage, 'contrato_v1.pdf', { title, message: 'v1 reconocida' });
        const documentLink = editorPage.getByTestId('documents-list').getByRole('link', { name: title });
        await expect(documentLink).toBeVisible({ timeout: 90_000 });
        await documentLink.click();
        await expect(editorPage.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });
        const timelineUrl = editorPage.url();
        await editorPage.getByTestId('version-item-1').getByRole('link', { name: 'Ver documento' }).click();
        await editorPage.waitForURL(/versions\//);

        // Share the document URL with another authenticated member, as in D5.
        await reviewerPage.goto(editorPage.url());
        await expect(reviewerPage.getByTestId('seal-action-bar')).toBeVisible();
        await reviewerPage.getByTestId('seal-sections-open').click();
        await reviewerPage.getByTestId('pick-obligaciones-del-contratista').check();
        await reviewerPage.getByTestId('seal-picked').click();
        await expect(reviewerPage.getByTestId('seal-reviewer@versiona.test')).toBeVisible();
        await purgeMailbox();

        await editorPage.goto(timelineUrl);
        await uploadPdf(editorPage, 'sin_encabezados.pdf', { message: 'Entrega sin estructura reconocida' });
        await expect(editorPage.getByTestId('version-item-2')).toBeVisible({ timeout: 90_000 });
        await editorPage.getByTestId('version-item-2').getByRole('link', { name: 'Ver documento' }).click();
        await editorPage.waitForURL(/versions\//);
        await expect(editorPage.getByTestId('validity-reviewer@versiona.test')).toHaveAttribute(
          'data-decision', 'pending_confirmation'
        );

        // Positive delivery proves Mailpit is reachable before the absence check.
        const pendingEmail = await waitForEmail({ to: 'admin@versiona.test', subjectContains: title });
        expect(pendingEmail.Subject).toContain('Plan de invalidación por confirmar');
        await assertNoEmailFor('reviewer@versiona.test');
        const pendingInboxRead = reviewerPage.waitForResponse((response) =>
          new URL(response.url()).pathname === '/api/me/notifications/' && response.status() === 200
        );
        await reviewerPage.goto('/inbox');
        await (await pendingInboxRead).finished();
        const reviewerNotice = reviewerPage.getByTestId('inbox-item-seal.invalidated').filter({ hasText: title });
        await expect(reviewerNotice).toHaveCount(0);

        await adminPage.goto('/inbox');
        const pendingNotice = adminPage.getByTestId('inbox-item-seal_plan.pending').filter({ hasText: title });
        await expect(pendingNotice).toHaveCount(1);
        await pendingNotice.click();
        await expect(adminPage.getByTestId('version-item-2')).toBeVisible();
        await adminPage.getByTestId('version-item-2').getByRole('link', { name: 'Ver documento' }).click();
        await adminPage.waitForURL(/versions\//);

        const plan = adminPage.getByTestId('invalidation-review-card');
        await expect(plan).toBeVisible();
        const reviewerPlan = plan.getByTestId('plan-item-reviewer@versiona.test');
        await expect(reviewerPlan).toContainText('obligaciones-del-contratista');
        await expect(reviewerPlan.getByTestId(/^plan-invalidated-/)).toBeChecked();
        await plan.getByTestId('confirm-plan').click();
        await expect(plan).toHaveCount(0);
        const confirmedRecord = adminPage.getByTestId('validity-reviewer@versiona.test');
        await expect(confirmedRecord).toHaveAttribute('data-decision', 'invalidated');
        await expect(confirmedRecord).toContainText('Requiere re-revisión');
        await expect(confirmedRecord).toContainText('admin@versiona.test');

        await reviewerPage.goto('/inbox');
        await expect(reviewerNotice).toHaveCount(1);
        await expect(reviewerNotice).toContainText('re-revisión');
        const invalidatedEmail = await waitForEmail({ to: 'reviewer@versiona.test', subjectContains: title });
        expect(invalidatedEmail.Subject).toContain('requiere re-revisión');

        // The notified reviewer reads the persisted decision in another session.
        await reviewerNotice.click();
        await expect(reviewerPage.getByTestId('version-item-2')).toBeVisible();
        await reviewerPage.getByTestId('version-item-2').getByRole('link', { name: 'Ver documento' }).click();
        await reviewerPage.waitForURL(/versions\//);
        await expect(reviewerPage.getByTestId('validity-reviewer@versiona.test')).toHaveAttribute(
          'data-decision', 'invalidated'
        );
      } finally {
        await Promise.all([editorContext.close(), reviewerContext.close(), adminContext.close()]);
      }
    }
  );
});
