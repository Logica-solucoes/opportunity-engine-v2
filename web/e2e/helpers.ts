import { execSync } from 'node:child_process'
import { expect, type Page } from '@playwright/test'
import { ROOT, pyEnv } from './env'

export const NEW_PASSWORD = 'senha-nova-e2e-123'

export const uid = () => Math.random().toString(36).slice(2, 8)

export function createAdmin() {
  const email = `admin-${uid()}@e2e.test`
  const out = execSync(`uv run python -m api.cli create-admin ${email} E2E`, {
    cwd: ROOT,
    env: pyEnv,
    encoding: 'utf8',
  })
  return { email, temp: out.trim().split(' ').pop()! }
}

export async function login(page: Page, email: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('E-mail').fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar' }).click()
}

export async function changePassword(page: Page, current: string) {
  await expect(page).toHaveURL(/\/trocar-senha/)
  await page.getByLabel('Senha atual').fill(current)
  await page.getByLabel('Nova senha', { exact: true }).fill(NEW_PASSWORD)
  await page.getByLabel('Confirme a nova senha').fill(NEW_PASSWORD)
  await page.getByRole('button', { name: 'Salvar' }).click()
  await expect(page).not.toHaveURL(/\/trocar-senha/)
}

export async function loggedInAdmin(page: Page) {
  const admin = createAdmin()
  await login(page, admin.email, admin.temp)
  await changePassword(page, admin.temp)
  await expect(page.getByRole('heading', { name: 'Workspaces' })).toBeVisible()
  return admin
}

export async function createWorkspace(page: Page) {
  const slug = `ws-${uid()}`
  await page.goto('/admin/workspaces')
  await page.getByLabel('Nome').fill(`Marca ${slug}`)
  await page.getByLabel('Slug').fill(slug)
  await page.getByRole('button', { name: 'Criar workspace' }).click()
  await expect(page.getByRole('cell', { name: slug, exact: true })).toBeVisible()
  return slug
}

export async function addMember(page: Page, slug: string, role: 'admin' | 'analyst' | 'viewer') {
  const email = `user-${uid()}@e2e.test`
  await page.goto(`/w/${slug}/membros`)
  await page.getByLabel('E-mail').fill(email)
  await page.getByLabel('Nome').fill('Pessoa E2E')
  // .first(): the form's select comes before the per-row role selects
  await page.getByLabel('Papel').first().selectOption(role)
  await page.getByRole('button', { name: 'Adicionar' }).click()
  const temp = (await page.getByTestId('temp-password').textContent())!.trim()
  await page.getByRole('button', { name: 'Fechar' }).click()
  return { email, temp }
}
