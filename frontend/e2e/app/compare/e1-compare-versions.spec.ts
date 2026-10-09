import { expect, test } from '../../test-with-coverage';
import { E1_COMPARE } from '../../helpers/flow-tags';
import { createProject, openSeededProject, uniqueName, uploadPdf } from '../../helpers/versiona';
import { VIEWPORTS, viewportUse, type ViewportAlias } from '../../helpers/viewports';
import type { NormalizedBBox } from '../../../lib/pdf/coords';
import type { Locator } from '@playwright/test';

test.use({ storageState: 'e2e/.auth/editor.json' });

test.describe('E1 — Comparar dos versiones (pantalla estrella)', () => {
  test.slow(); // two real upload+analysis cycles before the comparison

  test(
    'E1-F01/F02 — las tres vistas muestran la tabla de verdad exacta',
    { tag: [...E1_COMPARE, '@scenario:e1-f01', '@scenario:e1-f02', '@scenario:c3-a01', '@outcome:display'] },
    async ({ page }) => {
      await createProject(page, uniqueName('Comparación'));
      await uploadPdf(page, 'contrato_v1.pdf', { title: 'Contrato C', message: 'v1' });
      const documentLink = page
        .getByTestId('documents-list')
        .getByRole('link', { name: /Contrato C/ });
      await expect(documentLink).toBeVisible({ timeout: 90_000 });
      await documentLink.click();
      await expect(page.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });

      await uploadPdf(page, 'contrato_v2.pdf', { message: 'v2' });
      await expect(page.getByTestId('version-item-2')).toBeVisible({ timeout: 90_000 });

      // C3-A01: elegir dos versiones desde el timeline y comparar
      await expect(page.getByTestId('compare-selected')).toBeDisabled();
      await page.getByTestId('select-version-1').check();
      await page.getByTestId('select-version-2').check();
      await page.getByTestId('compare-selected').click();
      await page.waitForURL(/\/compare\//, { timeout: 20_000 });

      // Vista lado a lado (default): ambos visores + lista de secciones
      await expect(page.getByTestId('compare-view')).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId('side-before')).toBeVisible();
      await expect(page.getByTestId('side-after')).toBeVisible();
      await expect(page.getByText('2 modificadas, 1 eliminada, 1 agregada')).toBeVisible();

      // Vista de secciones: la tabla de verdad EXACTA
      await page.getByRole('tab', { name: 'Secciones' }).click();
      const list = page.getByTestId('section-change-list');
      await expect(list).toBeVisible();
      await expect(page.getByTestId('section-obligaciones-del-contratista')).toHaveAttribute(
        'data-change',
        'modified'
      );
      await expect(page.getByTestId('section-valor-y-forma-de-pago')).toHaveAttribute(
        'data-change',
        'modified'
      );
      await expect(page.getByTestId('section-plazo-de-ejecucion')).toHaveAttribute(
        'data-change',
        'removed'
      );
      await expect(page.getByTestId('section-proteccion-de-datos-personales')).toHaveAttribute(
        'data-change',
        'added'
      );
      // Las secciones renumeradas (7→6, 8→7) NO son cambios
      await expect(page.getByTestId('section-confidencialidad')).toHaveCount(0);

      // Vista de resumen: los conteos exactos
      await page.getByRole('tab', { name: 'Resumen' }).click();
      await expect(page.getByTestId('count-modified')).toHaveText('2');
      await expect(page.getByTestId('count-removed')).toHaveText('1');
      await expect(page.getByTestId('count-added')).toHaveText('1');

      // E1-F02: seleccionar una sección deja el deep-link en la URL
      await page.getByRole('tab', { name: 'Secciones' }).click();
      await page.getByTestId('section-obligaciones-del-contratista').click();
      await expect(page).toHaveURL(/#sec-obligaciones-del-contratista/);
    }
  );

  test(
    'E1-L01 — comparar una versión consigo misma no ofrece pares inválidos',
    { tag: [...E1_COMPARE, '@scenario:e1-l01', '@outcome:display'] },
    async ({ page }) => {
      await createProject(page, uniqueName('SinCambios'));
      await uploadPdf(page, 'contrato_v1.pdf', { title: 'Único', message: 'v1' });
      const documentLink = page
        .getByTestId('documents-list')
        .getByRole('link', { name: /Único/ });
      await expect(documentLink).toBeVisible({ timeout: 90_000 });
      await documentLink.click();
      await expect(page.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });

      // Con una sola versión, comparar queda deshabilitado (C2-L01)
      await page.getByTestId('select-version-1').check();
      await expect(page.getByTestId('compare-selected')).toBeDisabled();
    }
  );
});

async function assertSelectedPdfFits(viewer: Locator, bbox: NormalizedBBox) {
  const pdfPage = viewer.getByTestId(`pdf-page-${bbox.page}`);
  await expect(pdfPage.locator('canvas')).toBeVisible({ timeout: 30_000 });
  await expect(pdfPage.getByTestId('diff-highlight').first()).toBeVisible();
  await expect.poll(() => pdfPage.evaluate((element, expected) => {
    const canvas = element.querySelector('canvas')!.getBoundingClientRect();
    const highlight = element.querySelector<HTMLElement>('[data-testid="diff-highlight"]')!;
    const bounds = element.closest('[data-testid="pdf-viewer"]')!.getBoundingClientRect();
    return canvas.left >= bounds.left && canvas.right <= bounds.right && canvas.width <= 420
      && Math.abs(parseFloat(highlight.style.left) - expected.x0 * canvas.width) < 1
      && Math.abs(parseFloat(highlight.style.top) - expected.y0 * canvas.height) < 1
      && Math.abs(parseFloat(highlight.style.width) - (expected.x1 - expected.x0) * canvas.width) < 1
      && Math.abs(parseFloat(highlight.style.height) - (expected.y1 - expected.y0) * canvas.height) < 1;
  }, bbox)).toBe(true);
}

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

/** A section name shown whole, never cut by truncate/ellipsis (TIP-2). */
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

const PDF_VIEWPORTS: Array<{ alias: ViewportAlias; resized: ViewportAlias }> = [
  { alias: 'compact', resized: 'portrait' },
  { alias: 'portrait', resized: 'compact' },
  { alias: 'landscape', resized: 'compact' },
  { alias: 'desktop', resized: 'compact' },
  { alias: 'wide', resized: 'compact' },
];

for (const { alias, resized } of PDF_VIEWPORTS) {
  test.describe(`E1 PDF @viewport:${alias}`, () => {
    test.use(viewportUse(alias));
    test.slow();

    test('la sección seleccionada conserva el resaltado al cambiar el ancho',
      { tag: [...E1_COMPARE, '@outcome:display'] }, async ({ page }) => {
        // quality: allow-duplicate (per-viewport contract: e1-compare-versions PDF fit at the five standard viewports)
        // Bug: el canvas fijo de 420 px desborda su columna o el resaltado usa la escala anterior tras resize (LAY-1/MED-1).
        // Bug (R-compare-02): en la columna de 260 px el `truncate` cortaba el nombre de la sección elegida (TIP-2).
        const title = uniqueName(`Contrato responsive ${alias}`);
        await openSeededProject(page);
        await uploadPdf(page, 'contrato_v1.pdf', { title, message: 'v1' });
        await page.getByTestId('documents-list').getByRole('link', { name: new RegExp(title) }).click();
        await expect(page.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });
        await uploadPdf(page, 'contrato_v2.pdf', { message: 'v2' });
        await expect(page.getByTestId('version-item-2')).toBeVisible({ timeout: 90_000 });
        await page.getByTestId('select-version-1').check();
        await page.getByTestId('select-version-2').check();
        await page.getByTestId('compare-selected').click();
        await expect(page.getByText('2 modificadas, 1 eliminada, 1 agregada')).toBeVisible({ timeout: 30_000 });
        const diffResponse = page.waitForResponse((response) => response.url().endsWith('/sections/obligaciones-del-contratista/diff/') && response.status() === 200);
        await page.getByTestId('section-obligaciones-del-contratista').click();
        const diff = await (await diffResponse).json();
        expect(diff.bboxes_from.length).toBeGreaterThan(0);
        expect(diff.bboxes_to.length).toBeGreaterThan(0);
        await assertSelectedPdfFits(page.getByTestId('side-before').getByTestId('pdf-viewer'), diff.bboxes_from[0]);
        await assertSelectedPdfFits(page.getByTestId('side-after').getByTestId('pdf-viewer'), diff.bboxes_to[0]);
        const selectedSection = page.getByTestId('section-obligaciones-del-contratista');
        expect(await touchTarget(selectedSection)).toEqual(TOUCH_TARGET_OK);
        expect(await textClipping(selectedSection.getByText('3. OBLIGACIONES DEL CONTRATISTA'))).toEqual(TEXT_UNCLIPPED);
        await expect
          .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
          .toBe(true);

        await page.setViewportSize(VIEWPORTS[resized]);

        await assertSelectedPdfFits(page.getByTestId('side-before').getByTestId('pdf-viewer'), diff.bboxes_from[0]);
        await assertSelectedPdfFits(page.getByTestId('side-after').getByTestId('pdf-viewer'), diff.bboxes_to[0]);
        await expect(page).toHaveURL(/#sec-obligaciones-del-contratista$/);
        await expect(page.getByTestId('section-obligaciones-del-contratista')).toHaveAttribute('aria-current', 'true');
      });
  });
}

test.describe('E1 vistas @ 412 (celular)', () => {
  test.use(viewportUse('compact'));
  test.slow(); // two real upload+analysis cycles before the comparison

  test(
    'E1-R01 — a 412 px la vista Resumen muestra los conteos de la re-entrega',
    { tag: [...E1_COMPARE, '@scenario:e1-r01', '@outcome:display', '@viewport:compact'] },
    async ({ page }) => {
      // quality: allow-duplicate (per-viewport contract: e1-compare @ 412)
      // Bug que atrapa (R-compare-01/03): sin flex-wrap, «Guardar comparación» + «Siguiente
      // cambio» + pestañas piden ~442 px en 364 px útiles; la página se desplaza en
      // horizontal, «Resumen» queda fuera del viewport y los controles miden 34–38 px.
      const title = uniqueName('Contrato resumen compacto');
      await openSeededProject(page);
      await uploadPdf(page, 'contrato_v1.pdf', { title, message: 'v1' });
      await page.getByTestId('documents-list').getByRole('link', { name: new RegExp(title) }).click();
      await expect(page.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });
      await uploadPdf(page, 'contrato_v2.pdf', { message: 'v2' });
      await expect(page.getByTestId('version-item-2')).toBeVisible({ timeout: 90_000 });
      await page.getByTestId('select-version-1').check();
      await page.getByTestId('select-version-2').check();
      await page.getByTestId('compare-selected').click();
      await expect(page.getByText('2 modificadas, 1 eliminada, 1 agregada')).toBeVisible({ timeout: 30_000 });

      const summaryTab = page.getByRole('tab', { name: 'Resumen' });
      const compareControls = await Promise.all([
        page.getByTestId('save-comparison'),
        page.getByTestId('next-change'),
        summaryTab,
        page.getByTestId('hide-unchanged').locator('..'),
      ].map((control) => touchTarget(control)));
      expect(compareControls).toEqual([TOUCH_TARGET_OK, TOUCH_TARGET_OK, TOUCH_TARGET_OK, TOUCH_TARGET_OK]);
      await summaryTab.tap();

      await expect(page.getByTestId('count-modified')).toHaveText('2');
      await expect(page.getByTestId('count-removed')).toHaveText('1');
      await expect(page.getByTestId('count-added')).toHaveText('1');
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
        .toBe(true);
    }
  );
});
