import { defineConfig, devices } from '@playwright/test'
import { PORT, ROOT, pyEnv } from './e2e/env'

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: true,
  // parallel logins queue on api.passwords.SLOTS and one scrypt takes ~1.5 s on a slow laptop
  expect: { timeout: 15_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: { baseURL: `http://localhost:${PORT}`, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    // serves the built SPA from web/dist, so run `bun run build` first (the e2e script does)
    command: `uv run uvicorn api.main:app --port ${PORT}`,
    cwd: ROOT,
    env: pyEnv,
    url: `http://localhost:${PORT}/api/health`,
    reuseExistingServer: false,
  },
})
