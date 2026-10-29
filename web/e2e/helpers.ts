import { execSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { type Browser, expect, type Page } from '@playwright/test'
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

export async function newSession(browser: Browser, user: { email: string; temp: string }) {
  const page = await (await browser.newContext()).newPage()
  await login(page, user.email, user.temp)
  await changePassword(page, user.temp)
  return page
}

export const template = (name: string) => fileURLToPath(new URL(`../public/templates/${name}`, import.meta.url))

export async function createSimulation(page: Page, slug: string, name: string) {
  await page.goto(`/w/${slug}`)
  await page.getByRole('link', { name: 'Nova simulação' }).click()
  await page.getByLabel('Nome').fill(name)
  await page.getByRole('button', { name: 'Criar' }).click()
  await expect(page.getByRole('heading', { name })).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`/w/${slug}/simulacoes/\\d+$`))
}

export async function uploadTemplatesAndValidate(page: Page) {
  await page.getByLabel('Arquivo de investimento').setInputFiles(template('investimento.csv'))
  await expect(page.getByText('investimento.csv', { exact: true })).toBeVisible()
  await page.getByLabel('Arquivo de performance').setInputFiles(template('performance.csv'))
  await expect(page.getByText('performance.csv', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Validar' }).click()
  await expect(page.getByText('Nenhum problema encontrado.')).toBeVisible()
}

// the fake engine takes ~5 s (FAKE_ENGINE_STEP_SECONDS=1 in env.ts); returns the run page's URL
export async function runToCompletion(page: Page, slug: string, name: string) {
  await createSimulation(page, slug, name)
  await uploadTemplatesAndValidate(page)
  await page.getByRole('button', { name: 'Salvar parâmetros' }).click()
  await expect(page.getByRole('button', { name: 'Rodar' })).toBeEnabled()
  await page.getByRole('button', { name: 'Rodar' }).click()
  await expect(page).toHaveURL(new RegExp(`/w/${slug}/execucoes/\\d+$`))
  await expect(page.getByText('Concluída', { exact: true })).toBeVisible()
  return page.url()
}

export async function configureGoogle(page: Page, slug: string) {
  await page.goto('/admin/workspaces')
  await page.getByRole('row').filter({ hasText: slug }).getByRole('button', { name: 'Conector Google' }).click()
  await page.getByLabel('Dataset do Google Ads').fill('proj-teste.google_ads')
  await page.getByLabel('Customer ids').fill('123-456-7890, 2222222222')
  await page.getByLabel('Dataset do GA4').fill('proj-teste.analytics_123')
  await page.getByLabel('Evento do KPI').fill('purchase')
  await page.getByLabel('Métrica').selectOption('revenue')
  await page.getByRole('button', { name: 'Salvar' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('row').filter({ hasText: slug }).getByText('configurado')).toBeVisible()
}
