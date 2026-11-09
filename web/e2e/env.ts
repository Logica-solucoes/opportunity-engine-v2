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
  // every spec logs in from 127.0.0.1; the production limit (20 per 15 min) would trip mid-suite
  LOGIN_RATE_LIMIT: '10000',
  // the worker subprocess inherits this env: the fake engine takes ~5 s per run, long enough to see "Rodando"
  // and reload mid-run; the real one needs months of data
  ENGINE_FAKE: '1',
  FAKE_ENGINE_STEP_SECONDS: '1',
  FAKE_ENGINE_FAIL: '',
  // every E2E run returns the anonymized Gol as the engine wrote it before the audit fixes (08/nov/2026): the current
  // Gol publishes no event, and the screens need published ones. The current document is covered by tests/api
  FAKE_ENGINE_RESULTS: join(ROOT, 'tests', 'fixtures', 'results', 'e2e_gol_publicado.json'),
  // no Google credentials even if the dev shell has some: the import reaches BigQuery's client and comes back
  // with "sem credenciais", which is the whole path short of a real dataset
  GOOGLE_APPLICATION_CREDENTIALS: join(tmpdir(), 'gem-e2e-no-such-credentials.json'),
  GOOGLE_CLOUD_PROJECT: 'gem-e2e',
}

// the tables paginate at 10; the specs create more rows than that and look them up by name
export const storageState = {
  cookies: [],
  origins: [{ origin: `http://localhost:${PORT}`, localStorage: [{ name: 'table:pageSize', value: '100' }] }],
}
