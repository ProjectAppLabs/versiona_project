/**
 * Environment for every backend process the E2E harness starts.
 *
 * The harness runs `manage.py` twice before a single test executes (seed +
 * token minting) and then boots a real Django server. All three read
 * `backend/.env`, which on a deployment host points at the LIVE database — on
 * the staging host the work clone IS the deployment. Following the documented
 * `npx playwright test` would therefore seed test accounts into staging.
 *
 * `backend/.env.e2e` (gitignored; copy `.env.e2e.example`) names the throwaway
 * database this suite is allowed to touch. Its values are passed on the child
 * process environment, so `.env` is never edited and the running services are
 * never reconfigured — python-dotenv's load_dotenv does not override variables
 * that are already set, so these win.
 *
 * When the file is absent the environment is inherited unchanged, which is what
 * CI wants (its job env already names a disposable database). The safety net in
 * that case is `core.fake_data_guard`: on a production-grade host the seed
 * command refuses instead of writing.
 */

import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';

export const BACKEND_DIR = path.resolve(__dirname, '../../../backend');
const E2E_ENV_FILE = path.join(BACKEND_DIR, '.env.e2e');

/** Parse the KEY=value lines of an env file, ignoring blanks and comments. */
function parseEnvFile(file: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const rawLine of readFileSync(file, 'utf-8').split('\n')) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq === -1) continue;
    out[line.slice(0, eq).trim()] = line.slice(eq + 1).trim();
  }
  return out;
}

/** Overrides for a backend child process. Empty when no `.env.e2e` exists. */
export function backendE2eOverrides(): Record<string, string> {
  return existsSync(E2E_ENV_FILE) ? parseEnvFile(E2E_ENV_FILE) : {};
}

/** Full child environment: the current one, with the E2E overrides applied. */
export function backendE2eEnv(): Record<string, string> {
  const inherited: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined) inherited[key] = value;
  }
  return { ...inherited, ...backendE2eOverrides() };
}

/** Whether a dedicated E2E environment file is in play, for diagnostics. */
export function hasDedicatedE2eEnv(): boolean {
  return existsSync(E2E_ENV_FILE);
}

export const E2E_ENV_HINT =
  `No backend/.env.e2e found, so the backend inherited backend/.env.\n` +
  `On a deployment host that names the LIVE database and the seed command will\n` +
  `refuse (core.fake_data_guard). Fix it by pointing the suite at a throwaway DB:\n` +
  `  cp backend/.env.e2e.example backend/.env.e2e   # then edit the credentials`;
