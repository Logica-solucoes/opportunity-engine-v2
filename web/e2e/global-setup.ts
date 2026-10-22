import { execSync } from 'node:child_process'
import { ROOT, pyEnv } from './env'

export default function globalSetup() {
  execSync('uv run python web/e2e/create_db.py', { cwd: ROOT, env: pyEnv, stdio: 'inherit' })
  execSync('uv run alembic -c api/alembic.ini upgrade head', { cwd: ROOT, env: pyEnv, stdio: 'inherit' })
}
