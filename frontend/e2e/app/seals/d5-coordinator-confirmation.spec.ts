import type { Locator, Page } from '@playwright/test';

import { expect, test } from '../../test-with-coverage';
import { D5_SELECTIVE_INVALIDATION } from '../../helpers/flow-tags';
import { assertNoEmailFor, purgeMailbox, waitForEmail } from '../../helpers/mailpit';
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

function checkpoint() {
  let resolve!: () => void;
  const promise = new Promise<void>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

async function pendingDocument(editorPage: Page, reviewerPage: Page, title: string) {
  await openSeededProject(editorPage);
  await uploadPdf(editorPage, 'contrato_v1.pdf', { title, message: 'Entrega reconocida' });
  await editorPage.getByTestId('documents-list').getByRole('link', { name: title }).click();
  await expect(editorPage.getByTestId('version-item-1')).toBeVisible();
  const timelineUrl = editorPage.url();
  await editorPage.getByTestId('version-item-1').getByRole('link', { name: 'Ver documento' }).click();
  await editorPage.waitForURL(/versions\//);
  await reviewerPage.goto(editorPage.url());
  await expect(reviewerPage.getByTestId('seal-action-bar')).toBeVisible();
  await reviewerPage.getByTestId('seal-sections-open').click();
  await reviewerPage.getByTestId('pick-obligaciones-del-contratista').check();
  await reviewerPage.getByTestId('seal-picked').click();
  await expect(reviewerPage.getByTestId('seal-reviewer@versiona.test')).toBeVisible();
  await editorPage.goto(timelineUrl);
  await uploadPdf(editorPage, 'sin_encabezados.pdf', { message: 'Entrega degradada pendiente' });
  const latest = editorPage.getByTestId('version-item-2');
  await expect(latest).toBeVisible({ timeout: 90_000 });
  const viewerPath = await latest.getByRole('link', { name: 'Ver documento' }).getAttribute('href');
  expect(viewerPath).toMatch(/\/versions\/[^/]+$/);
  return { viewerPath: viewerPath!, versionId: viewerPath!.split('/').at(-1)! };
}

test.describe('D5 — Confirmación coordinada de una entrega degradada', () => {
  test.slow();

  test(
    'D5-A04 — confirma la propuesta del documento vigente después de una respuesta anterior',
    { tag: [...D5_SELECTIVE_INVALIDATION, '@scenario:d5-a04-current-version', '@outcome:success'] },
    async ({ browser }) => {
      // Bug: late A data or A's initial radio choices can replace B's pending
      // plan. Navigation unmounts this card; retained-instance behavior belongs
      // to SealsPanel's real-store component regression, not this browser test.
      const editorContext = await browser.newContext({ storageState: AUTH.editor });
      const reviewerContext = await browser.newContext({ storageState: AUTH.reviewer });
      const adminContext = await browser.newContext({ storageState: AUTH.admin });
      const persistedContext = await browser.newContext({ storageState: AUTH.admin });
      const releaseOlder = checkpoint();

      try {
        const editorPage = await editorContext.newPage();
        const reviewerPage = await reviewerContext.newPage();
        const adminPage = await adminContext.newPage();
        const persistedPage = await persistedContext.newPage();
        const titleA = uniqueName('D5 plan anterior A');
        const titleB = uniqueName('D5 plan vigente B');
        const documentA = await pendingDocument(editorPage, reviewerPage, titleA);
        const documentB = await pendingDocument(editorPage, reviewerPage, titleB);
        const sealsHeld = checkpoint();
        const planHeld = checkpoint();
        const sealsReleased = adminPage.waitForResponse((response) =>
          new URL(response.url()).pathname === `/api/versions/${documentA.versionId}/seals/`
        );
        const planReleased = adminPage.waitForResponse((response) =>
          new URL(response.url()).pathname === `/api/versions/${documentA.versionId}/seal_plan/`
        );
        let sealA = '';

        await adminPage.route(`**/api/versions/${documentA.versionId}/seals/`, async (route) => {
          const response = await route.fetch();
          sealsHeld.resolve();
          await releaseOlder.promise;
          await route.fulfill({ response });
        });
        await adminPage.route(`**/api/versions/${documentA.versionId}/seal_plan/`, async (route) => {
          const response = await route.fetch();
          const data = await response.json();
          expect(data.pending).toHaveLength(1);
          sealA = data.pending[0].seal.public_id;
          planHeld.resolve();
          await releaseOlder.promise;
          await route.fulfill({ response });
        });

        await openSeededProject(adminPage);
        const timeOrigin = await adminPage.evaluate(() => performance.timeOrigin);
        await adminPage.getByTestId('documents-list').getByRole('link', { name: titleA }).click();
        await adminPage.getByTestId('version-item-2').getByRole('link', { name: 'Ver documento' }).click();
        await adminPage.waitForURL(new RegExp(`/versions/${documentA.versionId}$`));
        await Promise.all([sealsHeld.promise, planHeld.promise]);
        await expect(adminPage.getByTestId('seals-loading')).toBeVisible();

        // These clicks preserve the application's singleton stores across A→B.
        await adminPage.getByRole('link', { name: 'Panel', exact: true }).click();
        await adminPage.waitForURL(/\/projects$/);
        await adminPage.getByTestId('board-search').fill('Torre E2E');
        await adminPage.getByTestId('projects-grid').getByRole('link', { name: /Torre E2E/ }).first().click();
        await adminPage.getByTestId('documents-list').getByRole('link', { name: titleB }).click();
        const planBResponse = adminPage.waitForResponse((response) =>
          new URL(response.url()).pathname === `/api/versions/${documentB.versionId}/seal_plan/`
          && response.status() === 200
        );
        await adminPage.getByTestId('version-item-2').getByRole('link', { name: 'Ver documento' }).click();
        await adminPage.waitForURL(new RegExp(`/versions/${documentB.versionId}$`));
        const planB = await (await planBResponse).json();
        expect(planB.pending).toHaveLength(1);
        const sealB: string = planB.pending[0].seal.public_id;
        const proposalB = adminPage.getByTestId(`plan-invalidated-${sealB}`);
        await expect(proposalB).toBeChecked();
        await expect(adminPage.getByTestId('pdf-page-1').locator('canvas')).toBeVisible();
        expect(await adminPage.evaluate(() => performance.timeOrigin)).toBe(timeOrigin);
        expect(sealB).not.toBe(sealA);

        releaseOlder.resolve();
        await Promise.all([(await sealsReleased).finished(), (await planReleased).finished()]);
        await adminPage.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
        await expect(proposalB).toBeChecked();
        await expect(adminPage.getByTestId(`plan-invalidated-${sealA}`)).toHaveCount(0);
        const confirmation = adminPage.waitForResponse((response) =>
          response.request().method() === 'POST'
          && new URL(response.url()).pathname === `/api/versions/${documentB.versionId}/seal_plan/`
        );
        await adminPage.getByTestId('confirm-plan').click();
        const confirmed = await confirmation;
        expect(confirmed.status()).toBe(200);
        expect(confirmed.request().postDataJSON()).toEqual({ decisions: { [sealB]: 'invalidated' } });
        await expect(adminPage.getByTestId('validity-reviewer@versiona.test')).toHaveAttribute('data-decision', 'invalidated');

        // Independent context reads persisted backend decisions, not A/B's store.
        const persistedB = persistedPage.waitForResponse((response) =>
          new URL(response.url()).pathname === `/api/versions/${documentB.versionId}/seals/`
          && response.status() === 200
        );
        await persistedPage.goto(documentB.viewerPath);
        await (await persistedB).finished();
        await expect(persistedPage.getByTestId('validity-reviewer@versiona.test')).toHaveAttribute('data-decision', 'invalidated');
        await expect(persistedPage.getByTestId('invalidation-review-card')).toHaveCount(0);
        await persistedPage.goto(documentA.viewerPath);
        await expect(persistedPage.getByTestId(`plan-invalidated-${sealA}`)).toBeChecked();
        await expect(persistedPage.getByTestId('validity-reviewer@versiona.test')).toHaveAttribute('data-decision', 'pending_confirmation');
      } finally {
        releaseOlder.resolve();
        await Promise.all([editorContext.close(), reviewerContext.close(), adminContext.close(), persistedContext.close()]);
      }
    }
  );

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

  test.describe('plan del coordinador @ 835 (tableta vertical)', () => {
    test.use(viewportUse('portrait'));

    test(
      'D5-R01 — a 835 px el coordinador decide cada sello desde opciones táctiles',
      { tag: [...D5_SELECTIVE_INVALIDATION, '@scenario:d5-r01', '@outcome:success', '@viewport:portrait'] },
      async ({ browser }) => {
        // quality: allow-duplicate (per-viewport contract: d5-selective-invalidation @ 835)
        // Bug que atrapa (R-review-01): las opciones Conservar/Invalidar medían 20 px de
        // alto y «Confirmar plan» 36 px en la decisión más delicada de D5.
        const editorContext = await browser.newContext({ storageState: AUTH.editor });
        const reviewerContext = await browser.newContext({ storageState: AUTH.reviewer });
        const adminContext = await browser.newContext({ storageState: AUTH.admin });

        try {
          const editorPage = await editorContext.newPage();
          const reviewerPage = await reviewerContext.newPage();
          const adminPage = await adminContext.newPage();
          const title = uniqueName('D5 coordinador tableta');

          await openSeededProject(editorPage);
          await uploadPdf(editorPage, 'contrato_v1.pdf', { title, message: 'v1 reconocida' });
          const documentLink = editorPage.getByTestId('documents-list').getByRole('link', { name: title });
          await expect(documentLink).toBeVisible({ timeout: 90_000 });
          await documentLink.click();
          await expect(editorPage.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });
          const timelineUrl = editorPage.url();
          await editorPage.getByTestId('version-item-1').getByRole('link', { name: 'Ver documento' }).click();
          await editorPage.waitForURL(/versions\//);

          await reviewerPage.goto(editorPage.url());
          await expect(reviewerPage.getByTestId('seal-action-bar')).toBeVisible();
          await reviewerPage.getByTestId('seal-sections-open').click();
          await reviewerPage.getByTestId('pick-obligaciones-del-contratista').check();
          await reviewerPage.getByTestId('seal-picked').click();
          await expect(reviewerPage.getByTestId('seal-reviewer@versiona.test')).toBeVisible();

          await editorPage.goto(timelineUrl);
          await uploadPdf(editorPage, 'sin_encabezados.pdf', { message: 'Entrega sin estructura reconocida' });
          await expect(editorPage.getByTestId('version-item-2')).toBeVisible({ timeout: 90_000 });

          await openSeededProject(adminPage);
          await adminPage.getByTestId('documents-list').getByRole('link', { name: title }).tap();
          await expect(adminPage.getByTestId('version-item-2')).toBeVisible({ timeout: 20_000 });
          await adminPage.getByTestId('version-item-2').getByRole('link', { name: 'Ver documento' }).tap();
          await adminPage.waitForURL(/versions\//);

          const reviewerPlan = adminPage
            .getByTestId('invalidation-review-card')
            .getByTestId('plan-item-reviewer@versiona.test');
          await expect(reviewerPlan).toContainText('obligaciones-del-contratista', { timeout: 20_000 });
          const keepOption = reviewerPlan.getByTestId(/^plan-preserved-/);
          const invalidateOption = reviewerPlan.getByTestId(/^plan-invalidated-/);
          const optionTargets = await Promise.all(
            [keepOption.locator('..'), invalidateOption.locator('..')].map((option) => touchTarget(option))
          );
          expect(optionTargets).toEqual([TOUCH_TARGET_OK, TOUCH_TARGET_OK]);
          await keepOption.locator('..').tap();
          await expect(keepOption).toBeChecked();
          await invalidateOption.locator('..').tap();
          await expect(invalidateOption).toBeChecked();
          const confirmPlan = adminPage.getByTestId('confirm-plan');
          expect(await touchTarget(confirmPlan)).toEqual(TOUCH_TARGET_OK);
          await confirmPlan.tap();

          await expect(adminPage.getByTestId('invalidation-review-card')).toHaveCount(0);
          await expect(adminPage.getByTestId('validity-reviewer@versiona.test')).toHaveAttribute(
            'data-decision', 'invalidated'
          );
        } finally {
          await Promise.all([editorContext.close(), reviewerContext.close(), adminContext.close()]);
        }
      }
    );
  });
});
