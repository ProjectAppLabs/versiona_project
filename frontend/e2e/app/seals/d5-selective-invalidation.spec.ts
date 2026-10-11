import type { Page } from '@playwright/test';

import { expect, test } from '../../test-with-coverage';
import { D5_SELECTIVE_INVALIDATION } from '../../helpers/flow-tags';
import { assertNoEmailFor, purgeMailbox, waitForEmail } from '../../helpers/mailpit';
import { openSeededProject, uniqueName, uploadPdf } from '../../helpers/versiona';
import type { NotificationItem } from '../../../lib/stores/notificationStore';

async function readInbox(page: Page): Promise<NotificationItem[]> {
  // Absence is meaningful only after a successful read has rendered. A loading
  // skeleton or an HTTP error also hides inbox-list, so neither proves silence.
  const read = page.waitForResponse((response) =>
    response.request().method() === 'GET'
      && new URL(response.url()).pathname === '/api/me/notifications/'
  );
  await page.goto('/inbox');
  const response = await read;
  expect(response.status(), 'el inbox debe responder correctamente').toBe(200);
  expect(await response.finished(), 'la lectura del inbox debe terminar').toBeNull();
  const data = await response.json() as { results: NotificationItem[] };
  expect(data.results, 'el inbox debe devolver una lista de avisos').toEqual(expect.any(Array));

  const main = page.getByRole('main');
  const finalState = data.results.length > 0
    ? main.getByTestId('inbox-list')
    : main.getByTestId('empty-state').filter({ hasText: 'No tienes notificaciones' });
  await expect(finalState).toBeVisible();
  await expect(main.getByTestId('async-loading')).toHaveCount(0);
  await expect(main.getByTestId('async-error')).toHaveCount(0);
  return data.results;
}

interface InvalidationTarget {
  seal: string;
  title: string;
  link: string;
}

async function expectInvalidationNotice(
  page: Page, items: NotificationItem[], target: InvalidationTarget
): Promise<void> {
  const matches = items.filter((item) => item.event_key === 'seal.invalidated'
    && item.payload.seal === target.seal && item.payload.to_version === 2);
  expect(matches, 'debe llegar el aviso de este sello y esta entrega').toHaveLength(1);
  expect(matches[0]).toMatchObject({
    title: target.title,
    link: target.link,
    payload: { sections: ['obligaciones-del-contratista'] },
  });
  const notice = page.getByRole('main').getByTestId('inbox-item-seal.invalidated')
    .filter({ hasText: target.title });
  await expect(notice).toHaveCount(1);
  await expect(notice).toHaveAttribute('href', target.link);
  await expect(notice).toContainText('obligaciones-del-contratista');
}

async function expectNoInvalidationNotice(
  page: Page, items: NotificationItem[], target: InvalidationTarget
): Promise<void> {
  // Other documents may have legitimate notifications. None may identify this
  // preserved seal's delivery through its payload, title or destination.
  expect(items.filter((item) => item.event_key === 'seal.invalidated'
    && (item.link === target.link || item.title === target.title
      || (item.payload.seal === target.seal && item.payload.to_version === 2))
  ), 'el sello conservado no debe recibir este aviso').toHaveLength(0);
  await expect(page.getByRole('main').getByTestId('inbox-item-seal.invalidated')
    .filter({ hasText: target.title })).toHaveCount(0);
}

/**
 * LA PRUEBA REINA (docs/plan/06 §5.2 — el diferencial del producto):
 * revisor A sella §1–2 · revisor B sella §3 · el editor sube v2 que cambia §3
 * (y otras, pero NO las de A) ⇒ el sello de A se CONSERVA con constancia, el
 * de B se INVALIDA, y SOLO B recibe el correo (S6). Multi-contexto real.
 * Atrapa: aceptar carga/error como ausencia, o un aviso de otro documento como
 * prueba de que la invalidación de esta entrega llegó al revisor correcto.
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
      const placedA = pageA.waitForResponse((response) =>
        response.request().method() === 'POST'
          && new URL(response.url()).pathname.endsWith('/seals/')
      );
      await pageA.getByTestId('seal-picked').click();
      const sealAResponse = await placedA;
      expect(sealAResponse.status()).toBe(201);
      const sealA = (await sealAResponse.json()).public_id as string;
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
      const placedB = pageB.waitForResponse((response) =>
        response.request().method() === 'POST'
          && new URL(response.url()).pathname.endsWith('/seals/')
      );
      await pageB.getByTestId('seal-picked').click();
      const sealBResponse = await placedB;
      expect(sealBResponse.status()).toBe(201);
      const sealB = (await sealBResponse.json()).public_id as string;
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

      const v1Id = new URL(v1Url).pathname.split('/versions/')[1];
      const v2Id = new URL(editorPage.url()).pathname.split('/versions/')[1];
      const invalidationLink = `${new URL(timelineUrl).pathname}/compare/${v1Id}/${v2Id}`;
      const invalidationTitle = `Tu sello en "${title}" requiere re-revisión (v2)`;

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
      const inboxB = await readInbox(pageB);
      await expectInvalidationNotice(pageB, inboxB, {
        seal: sealB, title: invalidationTitle, link: invalidationLink,
      });

      // ── S6 por correo: B recibió email; A NO recibió nada ─────────────
      await waitForEmail({ to: 'admin@versiona.test', subjectContains: 're-revisión' });
      await assertNoEmailFor('reviewer@versiona.test');

      // ── A no tiene notificación de invalidación (su sello vive) ───────
      const inboxA = await readInbox(pageA);
      await expectNoInvalidationNotice(pageA, inboxA, {
        seal: sealA, title: invalidationTitle, link: invalidationLink,
      });

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
