import path from 'node:path';

import type { Page, Route } from '@playwright/test';

import { expect, test } from '../test-with-coverage';
import { TESTDATA } from '../helpers/versiona';

const FIRST_ID = '01999c00-0000-7000-8000-000000000001';
const SECOND_ID = '01999c00-0000-7000-8000-000000000002';

test.slow();

function comparison(publicId: string, status: 'processing' | 'done' | 'failed') {
  return {
    public_id: publicId,
    status,
    error_code: status === 'failed' ? 'processing_failed' : '',
    file_a_name: `${publicId}-before.pdf`,
    file_b_name: `${publicId}-after.pdf`,
    created_at: '2026-10-08T00:00:00Z',
    expires_at: '2026-10-09T00:00:00Z',
    result: {
      counts: { modified: 2, added: 1, removed: 1, unchanged: 0, renamed_only: 0 },
      summary_text: publicId,
      sections: [],
      meta: { page_count_a: 1, page_count_b: 1 },
    },
  };
}

async function installDelayedComparison(page: Page) {
  const ids = [FIRST_ID, SECOND_ID];
  let firstReads = 0;
  let capturePoll!: (route: Route) => void;
  const outstandingPoll = new Promise<Route>((resolve) => { capturePoll = resolve; });

  // Only HTTP is controlled: the actual forms, links, page lifecycle, timers,
  // Axios cancellation and result component all run in the live application.
  await page.route('**/public/comparisons/', (route) => route.fulfill({
    json: { public_id: ids.shift(), status: 'processing' },
  }));
  await page.route(`**/public/comparisons/${FIRST_ID}/`, (route) => {
    firstReads += 1;
    if (firstReads === 1) {
      return route.fulfill({ json: comparison(FIRST_ID, 'processing') });
    }
    capturePoll(route);
  });
  await page.route(`**/public/comparisons/${SECOND_ID}/`, (route) => route.fulfill({
    json: comparison(SECOND_ID, 'done'),
  }));
  return { outstandingPoll, firstReads: () => firstReads };
}

async function uploadComparison(page: Page) {
  await page.getByTestId('public-file-a').setInputFiles(
    path.join(TESTDATA, 'contrato_v1.pdf')
  );
  await page.getByTestId('public-file-b').setInputFiles(
    path.join(TESTDATA, 'contrato_v2.pdf')
  );
  await page.getByTestId('public-compare-submit').click();
}

for (const lateStatus of ['done', 'failed'] as const) {
  test(
    `keeps the new comparison after leaving a delayed ${lateStatus} result`,
    { tag: [
      '@flow:public-compare-lifecycle', '@module:public', '@priority:P1', '@outcome:success',
    ] },
    async ({ page }) => {
      const boundary = await installDelayedComparison(page);
      await page.goto('/comparar');
      await uploadComparison(page);
      await expect(page).toHaveURL(`/comparar/${FIRST_ID}`);
      await expect(page.getByRole('status')).toContainText('Analizando y comparando');
      const oldPoll = await boundary.outstandingPoll;
      const cancelled = page.waitForEvent('requestfailed', {
        predicate: (request) => request.url().endsWith(`/${FIRST_ID}/`),
      });

      await page.getByTestId('public-header').getByRole('link', {
        name: 'Comparar PDFs',
      }).click();
      await expect(page.getByRole('heading', {
        name: 'Compara dos PDF gratis',
      })).toBeVisible();
      const cancelledRequest = await cancelled;
      await uploadComparison(page);
      await expect(page).toHaveURL(`/comparar/${SECOND_ID}`);
      await expect(page.getByTestId('public-files-line')).toHaveText(
        `${SECOND_ID}-before.pdf → ${SECOND_ID}-after.pdf`
      );
      await oldPoll.fulfill({ json: comparison(FIRST_ID, lateStatus) });

      expect(cancelledRequest.failure()?.errorText).toContain('ERR_ABORTED');
      await expect(page.getByTestId('public-files-line')).toHaveText(
        `${SECOND_ID}-before.pdf → ${SECOND_ID}-after.pdf`
      );
      await expect(page.getByTestId('count-modified')).toHaveText('2');
      await expect(page.getByTestId('public-compare-error')).toHaveCount(0);
      expect(boundary.firstReads()).toBe(2);
    }
  );
}

test(
  'shows a failure alert for the current comparison',
  { tag: [
    '@flow:public-compare', '@module:public', '@priority:P1', '@outcome:failure',
  ] },
  async ({ page }) => {
    await page.route('**/public/comparisons/', (route) => route.fulfill({
      json: { public_id: FIRST_ID, status: 'processing' },
    }));
    await page.route(`**/public/comparisons/${FIRST_ID}/`, (route) => route.fulfill({
      json: { ...comparison(FIRST_ID, 'failed'), result: null },
    }));
    await page.goto('/');
    await page.getByTestId('public-header').getByRole('link', {
      name: 'Comparar PDFs',
    }).click();

    await uploadComparison(page);

    await expect(page.getByTestId('public-compare-error')).toHaveText(
      'No pudimos comparar estos PDF. Inténtalo de nuevo.'
    );
    await expect(page.getByTestId('public-compare-result')).toHaveCount(0);
    await expect(page).toHaveURL(`/comparar/${FIRST_ID}`);
  }
);
