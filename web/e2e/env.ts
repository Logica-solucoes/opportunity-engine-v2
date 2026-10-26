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
}
