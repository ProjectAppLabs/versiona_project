import { expect, test, type Page } from '../../test-with-coverage';
import { B2_PROJECTS_BOARD } from '../../helpers/flow-tags';
import { viewportUse } from '../../helpers/viewports';
import { createProject, uniqueName, uploadPdf } from '../../helpers/versiona';

test.use({ storageState: 'e2e/.auth/editor.json' });

async function createProjectWithLongDescription(page: Page, name: string, description: string): Promise<void> {
  await page.goto('/projects');
  await page.getByRole('link', { name: 'Nuevo proyecto' }).click();
  await page.waitForURL(/\/projects\/new$/);
  await page.getByTestId('project-name').fill(name);
  await page.getByTestId('project-description').fill(description);
  await page.getByTestId('project-submit').click();
  await expect(page.getByTestId('upload-dropzone')).toBeVisible({ timeout: 15_000 });
}

async function visualTextMetrics(locator: ReturnType<Page['getByText']>) {
  return locator.evaluate((element) => {
    const style = window.getComputedStyle(element);
    return {
      horizontallyClipped: element.scrollWidth > element.clientWidth,
      verticallyClipped: element.scrollHeight > element.clientHeight,
      hasEllipsis: style.textOverflow === 'ellipsis',
      hasNoWrap: style.whiteSpace === 'nowrap',
      hasLineClamp: style.webkitLineClamp !== 'none',
    };
  });
}

test.describe('B2 — Tablero completo', () => {
  test.slow();

  test(
    'B2-A03 — la búsqueda encuentra el proyecto por CONTENIDO del PDF',
    { tag: [...B2_PROJECTS_BOARD, '@scenario:b2-a03', '@scenario:b2-a01', '@outcome:display'] },
    async ({ page }) => {
      // Proyecto fresco cuyo NOMBRE no contiene el término: si aparece al
      // buscar, la coincidencia vino del contenido del PDF.
      const name = uniqueName('Zulia');
      await createProject(page, name);
      await uploadPdf(page, 'contrato_v1.pdf', { title: 'Contenido', message: 'v1' });
      await expect(
        page.getByTestId('documents-list').getByRole('link', { name: 'Contenido' })
      ).toBeVisible({ timeout: 90_000 });

      // 'interventoría' vive DENTRO del PDF (sin acento en el binario: la
      // búsqueda es insensible a acentos vía unaccent)
      await page.goto('/projects');
      await page.getByTestId('board-search').fill('interventoría');
      await expect(
        page.getByTestId('projects-grid').getByRole('link', { name })
      ).toBeVisible({ timeout: 15_000 });

      // Una búsqueda sin coincidencias muestra el vacío-con-guía. La primera
      // búsqueda (FTS sobre ~100 proyectos residuales) puede seguir en vuelo:
      // esperamos la RESPUESTA del segundo término antes de asertar.
      await Promise.all([
        page.waitForResponse(
          (response) => response.url().includes('blockchain'), { timeout: 20_000 }
        ),
        page.getByTestId('board-search').fill('blockchain quantum'),
      ]);
      // El diseño reserva el vacío-con-guía para el primer uso; una búsqueda
      // sin coincidencias deja el grid sin tarjetas.
      await expect(
        page.getByTestId('projects-grid').locator('li')
      ).toHaveCount(0, { timeout: 15_000 });

      // El filtro de estado lista el proyecto activo
      await page.getByTestId('board-search').fill('');
      await page.getByTestId('board-status-filter').selectOption('active');
      await expect(
        page.getByTestId('projects-grid').getByRole('link', { name })
      ).toBeVisible({ timeout: 15_000 });
    }
  );

  test.describe('controles responsivos', () => {
    test.use(viewportUse('compact'));

    test(
      'B2-R01 — a 412 px la búsqueda y el filtro conservan la tarjeta creada dentro del tablero',
      {
        tag: [
          ...B2_PROJECTS_BOARD,
          '@scenario:b2-r01',
          '@outcome:display',
          '@viewport:compact',
        ],
      },
      async ({ page }) => {
        // quality: allow-duplicate (per-viewport contract: b2-projects-board @ 412)
        // Catches: a compact filter bar that leaves its select, search, or CTA
        // outside the projects module after a member creates a project.
        const name = `${'Proyecto de seguimiento documental '.repeat(3)}${uniqueName('compact')}`;
        const description = 'Descripción extensa del proyecto para confirmar que la tarjeta conserva todo el contenido visible '.repeat(3);
        await createProjectWithLongDescription(page, name, description);

        await page.getByTestId('app-nav-toggle').click();
        await page.getByTestId('app-nav-menu').getByRole('link', { name: 'Panel', exact: true }).click();
        await page.waitForURL(/\/projects$/);
        await page.getByTestId('board-search').fill(name);
        await page.getByTestId('board-status-filter').selectOption('active');

        const cardTitle = page.getByTestId('projects-grid').getByText(name, { exact: true });
        const cardDescription = page.getByTestId('projects-grid').getByText(description, { exact: true });
        await expect(cardTitle).toHaveCount(1);
        await expect(cardDescription).toHaveCount(1);

        const viewportWidth = await page.evaluate(() => window.innerWidth);
        const controls = [
          page.getByTestId('board-status-filter'),
          page.getByTestId('board-search'),
          page.getByRole('link', { name: 'Nuevo proyecto' }),
        ];
        const controlMetrics = await Promise.all(controls.map(async (control) => {
          const box = await control.boundingBox();
          return box === null
            ? { insideViewport: false, touchTarget: false }
            : { insideViewport: box.x + box.width <= viewportWidth, touchTarget: box.height >= 44 };
        }));
        const textMetrics = await Promise.all([cardTitle, cardDescription].map(visualTextMetrics));
        expect(controlMetrics.every(({ insideViewport, touchTarget }) => insideViewport && touchTarget)).toBe(true);
        expect(textMetrics.every(({ horizontallyClipped, verticallyClipped, hasEllipsis, hasNoWrap, hasLineClamp }) => (
          !horizontallyClipped && !verticallyClipped && !hasEllipsis && !hasNoWrap && !hasLineClamp
        ))).toBe(true);
      }
    );
  });

  test.describe('distribución landscape', () => {
    test.use(viewportUse('landscape'));

    test(
      'B2-R02 — a 1195 px la búsqueda y el filtro conservan el tablero sin desborde',
      {
        tag: [
          ...B2_PROJECTS_BOARD,
          '@scenario:b2-r02',
          '@outcome:display',
          '@viewport:landscape',
        ],
      },
      async ({ page }) => {
        // quality: allow-duplicate (per-viewport contract: b2-projects-board @ 1195)
        // Catches: a compact-layout repair that overflows again when the board
        // returns to its horizontal landscape distribution.
        const name = uniqueName('Landscape board project');
        await createProject(page, name);

        await page.getByRole('link', { name: 'Panel' }).click();
        await page.waitForURL(/\/projects$/);
        await page.getByTestId('board-search').fill(name);
        await page.getByTestId('board-status-filter').selectOption('active');

        await expect(page.getByTestId('projects-grid').getByText(name, { exact: true })).toHaveCount(1);
        await expect
          .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
          .toBe(true);
      }
    );
  });
});
