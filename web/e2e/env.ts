import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const ROOT = fileURLToPath(new URL('../..', import.meta.url))
export const PORT = 8001
export const DATABASE_URL =
  process.env.E2E_DATABASE_URL ?? 'postgresql+psycopg://app:app@localhost:5432/app_e2e'
// uploads from the E2E server go to a temp dir, never the repo's ./data
export const pyEnv = {
  ...process.env,
  DATABASE_URL,
  PYTHONIOENCODING: 'utf-8',
  STORAGE_DIR: join(tmpdir(), 'gem-e2e-storage'),
  // the E2E never calls Gemini: an empty key takes the "unavailable" path even if the dev shell has one
  GEMINI_API_KEY: '',
  // the worker subprocess inherits this env: ~5 s per run, long enough to see "Rodando" and reload mid-run
  FAKE_ENGINE_STEP_SECONDS: '1',
  FAKE_ENGINE_FAIL: '',
  // no Google credentials even if the dev shell has some: the import reaches BigQuery's client and comes back
  // with "sem credenciais", which is the whole path short of a real dataset
  GOOGLE_APPLICATION_CREDENTIALS: join(tmpdir(), 'gem-e2e-no-such-credentials.json'),
  GOOGLE_CLOUD_PROJECT: 'gem-e2e',
}
