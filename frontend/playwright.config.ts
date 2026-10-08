import { defineConfig, devices } from '@playwright/test';

import { backendE2eEnv } from './e2e/helpers/backend-env';

// Shared-VPS safety: another project's dev server squatting :3000/:8000 gets
// silently "reused" by webServer and poisons every spec. Override per run:
//   E2E_FRONTEND_PORT=3100 E2E_BACKEND_PORT=8100 npx playwright test ...
const FRONTEND_PORT = Number(process.env.E2E_FRONTEND_PORT ?? 3000);
const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT ?? 8000);
const PYTHON_BIN = process.env.E2E_PYTHON_BIN ?? '../backend/venv/bin/python';

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  timeout: 60_000, // Increased to 60s for slower environments
  expect: {
    timeout: 10_000, // Increased to 10s
  },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // Reduced to 1 for environments with limited resources
  reporter: [
    ['list'],
    ['html', { open: 'never' }],
    ['json', { outputFile: 'e2e-results/results.json' }],
    ['./e2e/reporters/flow-coverage-reporter.mjs', { outputDir: 'e2e-results' }],
  ],
  webServer: [
    {
      command: `${PYTHON_BIN} ../backend/manage.py runserver 127.0.0.1:${BACKEND_PORT}`,
      url: `http://127.0.0.1:${BACKEND_PORT}/api/health/`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000, // 3 minutes for server startup
      stdout: 'ignore',
      stderr: 'ignore',
      // The server must answer against the SAME throwaway database global-setup
      // seeded, not whatever backend/.env names — on a deployment host that is
      // the live one. See e2e/helpers/backend-env.ts.
      env: backendE2eEnv(),
    },
    {
      command: `npm run dev -- --port ${FRONTEND_PORT}`,
      url: `http://localhost:${FRONTEND_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000, // 3 minutes for server startup
      env: {
        ...process.env,
        NEXT_PUBLIC_BACKEND_ORIGIN: `http://127.0.0.1:${BACKEND_PORT}`,
      },
    },
  ],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${FRONTEND_PORT}`,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'Desktop Chrome',
      use: { ...devices['Desktop Chrome'] },
    },
    // {
    //   name: 'Mobile Chrome',
    //   use: { ...devices['Pixel 5'] },
    // },
    // {
    //   name: 'Tablet',
    //   use: {
    //     ...devices['iPad Mini'],
    //     browserName: 'chromium',
    //   },
    // },
  ],
});
