/**
 * Playwright globalSetup (docs/plan/06 §5.1 — harness gaps H02/H03):
 * 1. Deterministic seed (`create_fake_data --scenario=e2e`).
 * 2. Mint JWTs per role (manage.py e2e_tokens — globalSetup runs before the
 *    webServer, so no HTTP login is possible) and persist them as
 *    storageState cookie files under e2e/.auth/ (gitignored).
 * 3. Purge mailpit so email assertions start clean.
 */

import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';

import { E2E_ENV_HINT, backendE2eEnv, hasDedicatedE2eEnv } from './helpers/backend-env';

const BACKEND = path.resolve(__dirname, '../../backend');
const PYTHON = process.env.E2E_PYTHON_BIN ?? path.join(BACKEND, 'venv/bin/python');
const AUTH_DIR = path.resolve(__dirname, '.auth');
const MAILPIT_API = process.env.MAILPIT_API ?? 'http://127.0.0.1:8025';

function storageState(tokens: { access: string; refresh: string }) {
  const cookie = (name: string, value: string) => ({
    name,
    value,
    domain: 'localhost',
    path: '/',
    expires: -1,
    httpOnly: false,
    secure: false,
    sameSite: 'Lax' as const,
  });
  return {
    cookies: [cookie('access_token', tokens.access), cookie('refresh_token', tokens.refresh)],
    origins: [],
  };
}

export default async function globalSetup() {
  // Never inherit backend/.env blindly: on a deployment host it names the live
  // database. See helpers/backend-env.ts.
  const env = backendE2eEnv();

  try {
    execFileSync(PYTHON, ['manage.py', 'create_fake_data', '--scenario=e2e'], {
      cwd: BACKEND,
      stdio: 'inherit',
      env,
    });
  } catch (err) {
    if (!hasDedicatedE2eEnv()) {
      throw new Error(
        `Seeding the E2E scenario failed.\n\n${E2E_ENV_HINT}\n\n` +
          `Original failure: ${(err as Error).message}`
      );
    }
    throw err;
  }

  // The minter's stdout can carry import-time noise ahead of the JSON (pymupdf
  // 1.28.2 prints its `fitz` deprecation warning to STDOUT), so parse from the
  // first `{` instead of trusting the whole stream.
  const raw = execFileSync(PYTHON, ['manage.py', 'e2e_tokens'], { cwd: BACKEND, env }).toString();
  const jsonStart = raw.indexOf('{');
  if (jsonStart === -1) throw new Error(`e2e_tokens produced no JSON on stdout:\n${raw}`);
  const tokens = JSON.parse(raw.slice(jsonStart)) as Record<string, { access: string; refresh: string }>;

  mkdirSync(AUTH_DIR, { recursive: true });
  for (const [alias, pair] of Object.entries(tokens)) {
    writeFileSync(path.join(AUTH_DIR, `${alias}.json`), JSON.stringify(storageState(pair)));
  }

  try {
    await fetch(`${MAILPIT_API}/api/v1/messages`, { method: 'DELETE' });
  } catch {
    // mailpit down is not fatal for specs that don't assert email
  }
}
