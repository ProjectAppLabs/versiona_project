import { expect, test } from '../../test-with-coverage';
import { B3_PROJECT_SETTINGS, E3_CONFIGURABLE_CHECKS } from '../../helpers/flow-tags';
import { viewportUse } from '../../helpers/viewports';
import { openSeededProject, uniqueName, uploadPdf } from '../../helpers/versiona';

test.describe('B3 + E3 — Gobernanza del proyecto', () => {
  test.slow();

  test(
    'B3-F01/E3-F01 — el admin configura la checklist y la siguiente versión la evalúa con evidencia',
    {
      tag: [
        ...B3_PROJECT_SETTINGS,
        ...E3_CONFIGURABLE_CHECKS,
        '@scenario:b3-f01',
        '@scenario:e3-f01',
        '@scenario:e3-f02',
        '@outcome:success',
      ],
    },
    async ({ browser }) => {
      // Admin: configura un check de texto requerido (crea config nueva — I8)
      const adminContext = await browser.newContext({ storageState: 'e2e/.auth/admin.json' });
      const adminPage = await adminContext.newPage();
      await openSeededProject(adminPage);
      await adminPage.getByTestId('project-settings-link').click();
      await adminPage.waitForURL(/\/settings$/);
      await expect(adminPage.getByTestId('project-config')).toBeVisible({ timeout: 20_000 });

      const checkLabel = uniqueName('Regula el anticipo');
      const checkRows = adminPage.locator('[data-testid^="check-label-"]');
      const initialCount = await checkRows.count();
      await adminPage.getByTestId('add-check').click();
      await expect(checkRows).toHaveCount(initialCount + 1);
      const index = initialCount;
      await adminPage.getByTestId(`check-label-${index}`).fill(checkLabel);
      await adminPage.getByTestId(`check-type-${index}`).selectOption('required_text');
      await adminPage.getByTestId(`check-param-${index}`).fill('anticipo');
      await adminPage.getByTestId('save-config').click();
      await expect(adminPage.getByText(/Configuración v\d+ creada/)).toBeVisible({
        timeout: 15_000,
      });

      // Editor: sube un documento NUEVO — pina la config nueva y corre el check
      const editorContext = await browser.newContext({ storageState: 'e2e/.auth/editor.json' });
      const editorPage = await editorContext.newPage();
      await openSeededProject(editorPage);
      const title = uniqueName('Chequeado E3');
      await uploadPdf(editorPage, 'contrato_v1.pdf', { title, message: 'v1' });
      const documentLink = editorPage
        .getByTestId('documents-list')
        .getByRole('link', { name: title });
      await expect(documentLink).toBeVisible({ timeout: 90_000 });
      await documentLink.click();
      await expect(editorPage.getByTestId('version-item-1')).toBeVisible({ timeout: 20_000 });

      // Semáforo en el timeline (E3-F03)
      await expect(editorPage.getByTestId('check-light-1')).toBeVisible({ timeout: 15_000 });

      // ChecksPanel con evidencia (E3-F02)
      await editorPage.getByRole('link', { name: 'Ver documento' }).click();
      await editorPage.waitForURL(/versions\//);
      await expect(editorPage.getByTestId('checks-panel')).toBeVisible({ timeout: 20_000 });
      const anticipoCheck = editorPage
        .locator('[data-testid^="check-"][data-outcome]')
        .filter({ hasText: checkLabel });
      await expect(anticipoCheck).toHaveAttribute('data-outcome', 'pass');
      await expect(anticipoCheck).toContainText('valor-y-forma-de-pago');

      await adminContext.close();
      await editorContext.close();
    }
  );

  test(
    'B3-P02 — la configuración está oculta para quien no es admin',
    { tag: [...B3_PROJECT_SETTINGS, ...E3_CONFIGURABLE_CHECKS, '@scenario:b3-p02', '@outcome:failure'] },
    async ({ browser }) => {
      const viewerContext = await browser.newContext({ storageState: 'e2e/.auth/viewer.json' });
      const viewerPage = await viewerContext.newPage();
      await openSeededProject(viewerPage);
      await viewerPage.getByTestId('project-settings-link').click();
      await viewerPage.waitForURL(/\/settings$/);

      await expect(
        viewerPage.getByText('La configuración del proyecto es una vista de administración.')
      ).toBeVisible({ timeout: 20_000 });
      await expect(viewerPage.getByTestId('project-config')).toHaveCount(0);
      await viewerContext.close();
    }
  );

  test.describe('checklist responsiva', () => {
    test.use({ ...viewportUse('portrait'), storageState: 'e2e/.auth/admin.json' });

    test(
      'B3-R01 — a 835 px el admin persiste un check sin comprimir sus controles',
      {
        tag: [
          ...B3_PROJECT_SETTINGS,
          '@scenario:b3-r01',
          '@outcome:success',
          '@viewport:portrait',
        ],
      },
      async ({ page }) => {
        // quality: allow-duplicate (per-viewport contract: b3-project-settings @ 835)
        // Catches: checklist columns that squeeze controls below a touch target
        // or discard a new check while saving the next configuration version.
        await openSeededProject(page);
        await page.getByTestId('project-settings-link').click();
        await page.waitForURL(/\/settings$/);
        await expect(page.getByTestId('project-config')).toBeVisible({ timeout: 20_000 });

        const checkRows = page.getByTestId(/^check-label-/);
        const initialCount = await checkRows.count();
        const index = initialCount;
        const label = uniqueName('Portrait checklist');
        await page.getByTestId('add-check').click();
        await expect(checkRows).toHaveCount(initialCount + 1);
        await page.getByTestId(`check-label-${index}`).fill(label);
        await page.getByTestId(`check-type-${index}`).selectOption('required_text');
        await page.getByTestId(`check-param-${index}`).fill('portrait-proof');

        const rowMetrics = await page.getByTestId(`check-label-${index}`).evaluate((input) =>
          Array.from(input.parentElement?.querySelectorAll('input, select, button') ?? []).map(
            (control) => ({ height: control.getBoundingClientRect().height })
          )
        );
        expect(rowMetrics).toHaveLength(5);
        expect(rowMetrics.every((metric) => metric.height >= 44)).toBe(true);

        await page.getByTestId('save-config').click();
        await expect(page.getByTestId('toaster')).toContainText(/Configuración v\d+ creada/, {
          timeout: 15_000,
        });
        await page.reload();
        await expect(page.getByTestId(`check-label-${index}`)).toHaveValue(label, { timeout: 15_000 });
        await expect
          .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
          .toBe(true);
      }
    );
  });
});
