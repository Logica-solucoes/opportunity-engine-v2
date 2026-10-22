import { fileURLToPath } from 'node:url'

export const ROOT = fileURLToPath(new URL('../..', import.meta.url))
export const PORT = 8001
export const DATABASE_URL =
  process.env.E2E_DATABASE_URL ?? 'postgresql+psycopg://app:app@localhost:5432/app_e2e'
export const pyEnv = { ...process.env, DATABASE_URL, PYTHONIOENCODING: 'utf-8' }
