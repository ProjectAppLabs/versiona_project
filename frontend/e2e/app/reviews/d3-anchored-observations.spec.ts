import type { Locator } from '@playwright/test';

import { expect, test } from '../../test-with-coverage';
import { D3_ANCHORED_OBSERVATIONS } from '../../helpers/flow-tags';
import { viewportUse } from '../../helpers/viewports';
import { openSeededProject, uniqueName, uploadPdf } from '../../helpers/versiona';

const BACKEND_API = `http://127.0.0.1:${process.env.E2E_BACKEND_PORT ?? 8000}`;

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

async function openDocumentVersionFromBoard(
  page: import('@playwright/test').Page,
  title: string
) {
  await openSeededProject(page);
  const documentLink = page
    .getByTestId('documents-list')
    .getByRole('link', { name: title });
  await expect(documentLink).toBeVisible({ timeout: 90_000 });
  await documentLink.click();
  await expect(page.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });
  await page.getByRole('link', { name: 'Ver documento' }).click();
  await page.waitForURL(/versions\//);
}

async function createObservationFixture(
  page: import('@playwright/test').Page,
  versionId: string,
  body: string
) {
  // quality: allow-api-setup (the 26 records are fixture setup; the asserted
  // pagination journey below enters and drives the version viewer through UI).
  const access = (await page.context().cookies()).find(
    (cookie) => cookie.name === 'access_token'
  )?.value;
  if (!access) throw new Error('Reviewer fixture has no access token.');
  const response = await page.request.post(
    `${BACKEND_API}/api/versions/${versionId}/observations/`,
    { data: { body }, headers: { Authorization: `Bearer ${access}` } }
  );
  expect(response.status()).toBe(201);
  return (await response.json() as { public_id: string }).public_id;
}

async function postObservationFixture(
  page: import('@playwright/test').Page,
  path: string,
  data: Record<string, string>
) {
  const access = (await page.context().cookies()).find(
    (cookie) => cookie.name === 'access_token'
  )?.value;
  if (!access) throw new Error('Fixture has no access token.');
  return page.request.post(`${BACKEND_API}/api/${path}`, {
    data,
    headers: { Authorization: `Bearer ${access}` },
  });
}

async function observationIdFrom(thread: import('@playwright/test').Locator) {
  const observationId = (await thread.getAttribute('data-testid'))?.replace('observation-', '');
  if (!observationId) throw new Error('Created observation did not expose a public id.');
  return observationId;
}

async function createObservationFixtures(
  page: import('@playwright/test').Page,
  versionId: string,
  prefix: string,
  count: number
) {
  const bodies = Array.from({ length: count }, (_, index) => `${prefix}-${index}`);
  for (const body of bodies) await createObservationFixture(page, versionId, body);
  return bodies;
}

test.describe('D3 — Observaciones ancladas', () => {
  test.slow();

  test(
    'D3-F01/F02/F04 — ancla, hilo, re-anclaje en v2 y resolución (I14)',
    { tag: [...D3_ANCHORED_OBSERVATIONS, '@scenario:d3-f01', '@scenario:d3-f02', '@scenario:d3-f04', '@outcome:success'] },
    async ({ browser }) => {
      // Catches: replacing D3's compact summaries with pages must not break
      // its original create → reply → re-anchor → resolve journey.
      // Editor sube v1
      const editorContext = await browser.newContext({ storageState: 'e2e/.auth/editor.json' });
      const editorPage = await editorContext.newPage();
      await openSeededProject(editorPage);
      const title = uniqueName('Contrato D3');
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

      // Revisor ancla una observación a §3 (D3-F01)
      const reviewerContext = await browser.newContext({
        storageState: 'e2e/.auth/reviewer.json',
      });
      const reviewerPage = await reviewerContext.newPage();
      await reviewerPage.goto(v1Url);
      await expect(reviewerPage.getByTestId('observations-panel')).toBeVisible({
        timeout: 20_000,
      });
      await reviewerPage.getByTestId('add-observation').click();
      await reviewerPage
        .getByTestId('observation-section')
        .selectOption({ label: '3. OBLIGACIONES DEL CONTRATISTA' });
      await reviewerPage
        .getByTestId('observation-body')
        .fill('La multa del 2% parece baja para la cuantía del contrato.');
      await reviewerPage.getByTestId('observation-submit').click();
      await expect(reviewerPage.getByText('Abierta')).toBeVisible({ timeout: 20_000 });
      await expect(reviewerPage.getByText(/Ancla exacta/)).toBeVisible();

      // El editor responde: open → answered (D3-F02, I14)
      await editorPage.reload();
      const replyInput = editorPage.locator('[data-testid^="reply-input-"]');
      await expect(replyInput).toBeVisible({ timeout: 20_000 });
      await replyInput.fill('Subimos la multa al 5% en la siguiente entrega.');
      await editorPage.locator('[data-testid^="reply-send-"]').click();
      await expect(editorPage.getByText('Respondida')).toBeVisible({ timeout: 20_000 });

      // Editor sube v2 (cambia §3) — el ancla se re-ancla (D3-F04)
      await editorPage.goto(timelineUrl);
      await uploadPdf(editorPage, 'contrato_v2.pdf', { message: 'v2 sube multa a 5%' });
      await expect(editorPage.getByTestId('version-item-2')).toBeVisible({ timeout: 90_000 });
      await editorPage
        .getByTestId('version-item-2')
        .getByRole('link', { name: 'Ver documento' })
        .click();
      await editorPage.waitForURL(/versions\//);
      const v2Url = editorPage.url();
      await expect(editorPage.getByText(/Re-anclada/)).toBeVisible({ timeout: 20_000 });

      // El revisor verifica la subsanación en v2 y resuelve (answered → resolved)
      await reviewerPage.goto(v2Url);
      await expect(reviewerPage.getByTestId('observations-panel')).toBeVisible({
        timeout: 20_000,
      });
      await reviewerPage.locator('[data-testid^="resolve-"]').click();
      // El hilo resuelto se oculta del listado por defecto: el filtro lo revela
      await reviewerPage.getByTestId('show-resolved').check();
      await expect(reviewerPage.getByText(/resuelta en v2/)).toBeVisible({ timeout: 20_000 });
      await expect(reviewerPage.getByText('Resuelta', { exact: true })).toBeVisible();

      await editorContext.close();
      await reviewerContext.close();
    }
  );

  test(
    'D3-E01 — responder sin texto no mueve el hilo de Abierta a Respondida',
    { tag: [...D3_ANCHORED_OBSERVATIONS, '@scenario:d3-e01', '@outcome:error'] },
    async ({ browser }) => {
      // Catches: assuming the reply button has a client-side empty-text
      // guard (it doesn't — `ObservationsPanel.tsx`'s `reply-send-` carries
      // no `disabled`), or the backend 400 validation being dropped, which
      // would silently flip a thread to "answered" with no reply content.
      const editorContext = await browser.newContext({ storageState: 'e2e/.auth/editor.json' });
      const editorPage = await editorContext.newPage();
      await openSeededProject(editorPage);
      const title = uniqueName('Contrato D3 Vacío');
      await uploadPdf(editorPage, 'contrato_v1.pdf', { title, message: 'v1' });
      const documentLink = editorPage
        .getByTestId('documents-list')
        .getByRole('link', { name: title });
      await expect(documentLink).toBeVisible({ timeout: 90_000 });
      await documentLink.click();
      await expect(editorPage.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });
      await editorPage.getByRole('link', { name: 'Ver documento' }).click();
      await editorPage.waitForURL(/versions\//);
      const v1Url = editorPage.url();

      // Revisor crea una observación abierta
      const reviewerContext = await browser.newContext({
        storageState: 'e2e/.auth/reviewer.json',
      });
      const reviewerPage = await reviewerContext.newPage();
      await reviewerPage.goto(v1Url);
      await expect(reviewerPage.getByTestId('observations-panel')).toBeVisible({
        timeout: 20_000,
      });
      await reviewerPage.getByTestId('add-observation').click();
      await reviewerPage
        .getByTestId('observation-section')
        .selectOption({ label: '3. OBLIGACIONES DEL CONTRATISTA' });
      await reviewerPage
        .getByTestId('observation-body')
        .fill('Revisar el plazo de entrega del contratista.');
      await reviewerPage.getByTestId('observation-submit').click();
      await expect(reviewerPage.getByText('Abierta')).toBeVisible({ timeout: 20_000 });

      // El editor recarga y responde SIN escribir texto
      await editorPage.reload();
      const replyInput = editorPage.locator('[data-testid^="reply-input-"]');
      await expect(replyInput).toBeVisible({ timeout: 20_000 });
      await expect(replyInput).toHaveValue('');
      await editorPage.locator('[data-testid^="reply-send-"]').click();

      await expect(editorPage.getByTestId('toaster')).toContainText(
        'La respuesta necesita un texto.',
        { timeout: 15_000 }
      );
      await expect(editorPage.getByText('Abierta')).toBeVisible();
      await expect(editorPage.getByText('Respondida')).toHaveCount(0);

      await editorContext.close();
      await reviewerContext.close();
    }
  );

  test(
    'D3-D01 — leer un texto largo, respuestas e historial conserva el hilo al abrir su versión',
    { tag: [...D3_ANCHORED_OBSERVATIONS, '@scenario:d3-d01', '@outcome:display'] },
    async ({ browser }) => {
      // Catches: a summary-only migration that eagerly downloads the body,
      // hides child collections, or loses an off-page thread on its history link.
      const editorContext = await browser.newContext({ storageState: 'e2e/.auth/editor.json' });
      const editorPage = await editorContext.newPage();
      await openSeededProject(editorPage);
      const title = uniqueName('Contrato D3 lectura');
      await uploadPdf(editorPage, 'contrato_v1.pdf', { title, message: 'v1 con lectura progresiva' });
      const documentLink = editorPage.getByTestId('documents-list').getByRole('link', { name: title });
      await expect(documentLink).toBeVisible({ timeout: 90_000 });
      await documentLink.click();
      await expect(editorPage.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });
      const timelineUrl = editorPage.url();
      await editorPage.getByRole('link', { name: 'Ver documento' }).click();
      await editorPage.waitForURL(/versions\//);
      const v1Url = editorPage.url();
      const v1Id = v1Url.split('/versions/')[1].split(/[/?#]/)[0];

      const reviewerContext = await browser.newContext({ storageState: 'e2e/.auth/reviewer.json' });
      const reviewerPage = await reviewerContext.newPage();
      // The display flow reaches the document through the board and timeline,
      // rather than treating the viewer URL as the behavior under test.
      await openDocumentVersionFromBoard(reviewerPage, title);
      const longBody = `LECTURA-D3-${Date.now()}-${'contenido-'.repeat(1_200)}`;
      await reviewerPage.getByTestId('add-observation').click();
      await reviewerPage
        .getByTestId('observation-section')
        .selectOption({ label: '3. OBLIGACIONES DEL CONTRATISTA' });
      await reviewerPage.getByTestId('observation-body').fill(longBody);
      await reviewerPage.getByTestId('observation-submit').click();

      const thread = reviewerPage
        .getByText(longBody.slice(0, 500), { exact: true })
        .locator('xpath=ancestor::li[@data-status]');
      await expect(thread).toHaveCount(1, { timeout: 20_000 });
      const threadId = await observationIdFrom(thread);
      const text = reviewerPage.getByTestId(`observation-text-${threadId}`);
      await expect(text).toHaveText(longBody.slice(0, 500));
      await reviewerPage.getByTestId(`observation-text-${threadId}-more`).click();
      await expect(text).toHaveText(longBody.slice(0, 8192));
      await reviewerPage.getByTestId(`observation-text-${threadId}-more`).click();
      await expect(text).toHaveText(longBody);
      await expect(reviewerPage.getByTestId(`observation-text-${threadId}-more`)).toHaveCount(0);

      await editorPage.goto(v1Url);
      const reply = `RESPUESTA-D3-${Date.now()}`;
      await editorPage.getByTestId(`reply-input-${threadId}`).fill(reply);
      await editorPage.getByTestId(`reply-send-${threadId}`).click();
      await expect(editorPage.getByText('Respondida', { exact: true })).toBeVisible({ timeout: 20_000 });

      await editorPage.goto(timelineUrl);
      await uploadPdf(editorPage, 'contrato_v2.pdf', { message: 'v2 conserva el historial D3' });
      await expect(editorPage.getByTestId('version-item-2')).toBeVisible({ timeout: 90_000 });
      await editorPage.getByTestId('version-item-2').getByRole('link', { name: 'Ver documento' }).click();
      await editorPage.waitForURL(/versions\//);
      const v2Url = editorPage.url();

      // Fixture-only: make the original conversation fall beyond page one so
      // the history-link focus path is exercised against the live cursor API.
      const v2Id = v2Url.split('/versions/')[1].split(/[/?#]/)[0];
      await createObservationFixtures(reviewerPage, v2Id, `POSTERIOR-D3-${Date.now()}`, 26);
      await reviewerPage.goto(v2Url);
      await expect(reviewerPage.getByTestId('observations-more')).toBeVisible();
      await expect(reviewerPage.getByTestId(`observation-${threadId}`)).toHaveCount(0);
      await reviewerPage.getByTestId('observations-more').click();
      await expect(reviewerPage.getByTestId(`observation-${threadId}`)).toContainText('Respondida');
      await reviewerPage.getByTestId(`observation-replies-${threadId}`).click();
      await expect(reviewerPage.getByText(reply, { exact: true })).toHaveCount(1);
      await reviewerPage.getByTestId(`observation-history-${threadId}`).click();
      const historicLink = reviewerPage.getByTestId(`observation-history-version-${threadId}-1`);
      await expect(historicLink).toHaveText('Ver en versión 1');
      const historicObservations = reviewerPage.waitForResponse((response) => {
        const url = new URL(response.url());
        return response.status() === 200
          && url.pathname === `/api/versions/${v1Id}/observations/`
          && url.searchParams.get('status') === 'all';
      });
      await historicLink.click();
      await expect(reviewerPage).toHaveURL(new RegExp(`\\?observation=${threadId}#observation-${threadId}$`));
      await historicObservations;
      await expect(reviewerPage.getByTestId(`observation-${threadId}`)).toContainText(longBody.slice(0, 500));

      await editorContext.close();
      await reviewerContext.close();
    }
  );

  test(
    'D3-F05 — un retry tras 500 recupera la primera página real de observaciones',
    { tag: [...D3_ANCHORED_OBSERVATIONS, '@scenario:d3-f05', '@outcome:failure'] },
    async ({ browser }) => {
      // Catches: a transient list failure that leaves the panel permanently
      // blank, or a retry which reads mocked data instead of calling Django.
      const editorContext = await browser.newContext({ storageState: 'e2e/.auth/editor.json' });
      const editorPage = await editorContext.newPage();
      await openSeededProject(editorPage);
      const title = uniqueName('Contrato D3 retry');
      await uploadPdf(editorPage, 'contrato_v1.pdf', { title, message: 'v1 retry' });
      const documentLink = editorPage.getByTestId('documents-list').getByRole('link', { name: title });
      await expect(documentLink).toBeVisible({ timeout: 90_000 });
      await documentLink.click();
      await expect(editorPage.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });
      await editorPage.getByRole('link', { name: 'Ver documento' }).click();
      await editorPage.waitForURL(/versions\//);
      const versionId = editorPage.url().split('/versions/')[1].split(/[/?#]/)[0];

      const reviewerContext = await browser.newContext({ storageState: 'e2e/.auth/reviewer.json' });
      const fixturePage = await reviewerContext.newPage();
      const fixtureText = `RECUPERADA-D3-${Date.now()}`;
      await createObservationFixture(fixturePage, versionId, fixtureText);
      const reviewerPage = await reviewerContext.newPage();
      let intercepted = false;
      const listRoute = async (route: import('@playwright/test').Route) => {
        const url = new URL(route.request().url());
        if (!intercepted && /\/api\/versions\/[^/]+\/observations\/$/.test(url.pathname) && url.searchParams.get('status') === 'active') {
          intercepted = true;
          await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'La lista no está disponible temporalmente.' }) });
          return;
        }
        await route.fallback();
      };
      await reviewerPage.route('**/api/versions/*/observations/**', listRoute);
      await openDocumentVersionFromBoard(reviewerPage, title);
      await expect(
        reviewerPage.getByTestId('observations-panel').getByRole('alert')
      ).toHaveText('La lista no está disponible temporalmente.');
      await expect(reviewerPage.getByTestId('observations-retry')).toHaveText('Reintentar');
      await reviewerPage.unroute('**/api/versions/*/observations/**', listRoute);
      await reviewerPage.getByTestId('observations-retry').click();
      await expect(reviewerPage.getByText(fixtureText)).toHaveCount(1);
      expect(intercepted).toBe(true);

      await editorContext.close();
      await reviewerContext.close();
    }
  );

  test(
    'D3-D02 — cargar más conserva la primera página y agrega el hilo 26 con el filtro activo',
    { tag: [...D3_ANCHORED_OBSERVATIONS, '@scenario:d3-d02', '@outcome:display'] },
    async ({ browser }) => {
      // Catches: replacing page one when loading page two, duplicating a thread,
      // or dropping the active filter while following a real signed cursor.
      const editorContext = await browser.newContext({ storageState: 'e2e/.auth/editor.json' });
      const editorPage = await editorContext.newPage();
      await openSeededProject(editorPage);
      const title = uniqueName('Contrato D3 pagina');
      await uploadPdf(editorPage, 'contrato_v1.pdf', { title, message: 'v1 pagina real' });
      const documentLink = editorPage.getByTestId('documents-list').getByRole('link', { name: title });
      await expect(documentLink).toBeVisible({ timeout: 90_000 });
      await documentLink.click();
      await editorPage.getByRole('link', { name: 'Ver documento' }).click();
      await editorPage.waitForURL(/versions\//);
      const versionId = editorPage.url().split('/versions/')[1].split(/[/?#]/)[0];

      const reviewerContext = await browser.newContext({ storageState: 'e2e/.auth/reviewer.json' });
      const fixturePage = await reviewerContext.newPage();
      const resolvedBody = `RESUELTA-D3-${Date.now()}`;
      const resolvedId = await createObservationFixture(fixturePage, versionId, resolvedBody);
      const replied = await postObservationFixture(editorPage, `observations/${resolvedId}/replies/`, {
        body: 'RESPUESTA-RESUELTA-D3',
      });
      expect(replied.status()).toBe(201);
      const resolved = await postObservationFixture(
        fixturePage,
        `observations/${resolvedId}/status/?version=${versionId}`,
        { status: 'resolved' }
      );
      expect(resolved.status()).toBe(200);
      const bodies = await createObservationFixtures(
        fixturePage, versionId, `PAGINA-REAL-D3-${Date.now()}`, 26
      );

      const reviewerPage = await reviewerContext.newPage();
      await openDocumentVersionFromBoard(reviewerPage, title);
      await expect(reviewerPage.getByText(bodies[25])).toHaveCount(1);
      await expect(reviewerPage.getByText(resolvedBody)).toHaveCount(0);
      await expect(reviewerPage.getByTestId('observations-more')).toHaveText('Cargar más observaciones');
      const secondPage = reviewerPage.waitForResponse((response) => {
        const url = new URL(response.url());
        return response.status() === 200 && /\/api\/versions\/[^/]+\/observations\/$/.test(url.pathname)
          && url.searchParams.get('status') === 'active' && url.searchParams.has('cursor');
      });
      await reviewerPage.getByTestId('observations-more').click();
      await secondPage;
      await expect(reviewerPage.getByText(bodies[25])).toHaveCount(1);
      await expect(reviewerPage.getByText(bodies[0])).toHaveCount(1);

      await reviewerPage.getByTestId('show-resolved').check();
      await expect(reviewerPage.getByText(resolvedBody)).toHaveCount(0);
      await reviewerPage.getByTestId('observations-more').click();
      await expect(reviewerPage.getByText(resolvedBody)).toHaveCount(1);
      await expect(reviewerPage.getByText('Resuelta', { exact: true })).toHaveCount(1);

      await editorContext.close();
      await reviewerContext.close();
    }
  );

  test.describe('hilo @ 412 (celular)', () => {
    test.use(viewportUse('compact'));

    test(
      'D3-R01 — a 412 px una observación nueva recibe respuesta desde el hilo',
      { tag: [...D3_ANCHORED_OBSERVATIONS, '@scenario:d3-r01', '@outcome:success', '@viewport:compact'] },
      async ({ browser }) => {
        // quality: allow-duplicate (per-viewport contract: d3-anchored-observations @ 412)
        // Bug que atrapa (R-review-02): campos de 14 px (zoom de iOS) y acciones de
        // 28–34 px en el formulario de la observación y en el hilo a 412 px.
        const editorContext = await browser.newContext({ storageState: 'e2e/.auth/editor.json' });
        const reviewerContext = await browser.newContext({ storageState: 'e2e/.auth/reviewer.json' });
        try {
          const editorPage = await editorContext.newPage();
          await openSeededProject(editorPage);
          const title = uniqueName('Contrato D3 celular');
          await uploadPdf(editorPage, 'contrato_v1.pdf', { title, message: 'v1' });
          await expect(
            editorPage.getByTestId('documents-list').getByRole('link', { name: title })
          ).toBeVisible({ timeout: 90_000 });

          const reviewerPage = await reviewerContext.newPage();
          await openDocumentVersionFromBoard(reviewerPage, title);
          const addObservation = reviewerPage.getByTestId('add-observation');
          expect(await touchTarget(addObservation)).toEqual(TOUCH_TARGET_OK);
          await addObservation.tap();
          const sectionSelect = reviewerPage.getByTestId('observation-section');
          const bodyInput = reviewerPage.getByTestId('observation-body');
          await expect(sectionSelect).toHaveCSS('font-size', '16px');
          await expect(bodyInput).toHaveCSS('font-size', '16px');
          await sectionSelect.selectOption({ label: '3. OBLIGACIONES DEL CONTRATISTA' });
          await bodyInput.fill('La multa del contratista necesita un tope explícito.');
          await reviewerPage.getByTestId('observation-submit').tap();
          await expect(reviewerPage.getByText('Abierta')).toBeVisible({ timeout: 20_000 });

          await openDocumentVersionFromBoard(editorPage, title);
          const replyInput = editorPage.locator('[data-testid^="reply-input-"]');
          await expect(replyInput).toHaveCSS('font-size', '16px');
          expect(await touchTarget(replyInput)).toEqual(TOUCH_TARGET_OK);
          await replyInput.fill('Agregamos un tope del 20 % en la siguiente entrega.');
          const replySend = editorPage.locator('[data-testid^="reply-send-"]');
          expect(await touchTarget(replySend)).toEqual(TOUCH_TARGET_OK);
          await replySend.tap();

          await expect(editorPage.getByText('Respondida')).toBeVisible({ timeout: 20_000 });
        } finally {
          await Promise.all([editorContext.close(), reviewerContext.close()]);
        }
      }
    );
  });
});
