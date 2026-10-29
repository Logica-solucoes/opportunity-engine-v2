import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { configureGoogle, createAdmin, createWorkspace, loggedInAdmin, runToCompletion } from './helpers'

test('platform admin creates a workspace and sees it on the home page', async ({ page }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  await page.goto('/')
  await expect(page.getByRole('link', { name: new RegExp(`Marca ${slug}`) })).toBeVisible()
})

test('duplicate slug shows the api message', async ({ page }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  await page.getByLabel('Nome').fill('Outra')
  await page.getByLabel('Slug').fill(slug)
  await page.getByRole('button', { name: 'Criar workspace' }).click()
  await expect(page.getByText('Já existe um workspace com esse slug')).toBeVisible()
})

test('platform admin resets a password and sees it once', async ({ page }) => {
  const admin = await loggedInAdmin(page)
  await page.goto('/admin/usuarios')
  const row = page.getByRole('row', { name: new RegExp(admin.email) })
  await expect(row).toBeVisible()
  await expect(row.getByRole('button', { name: 'Desativar' })).toHaveCount(0)
  await expect(row.getByRole('button', { name: 'Resetar senha' })).toHaveCount(0)

  const other = createAdmin()
  await page.reload()
  await page.getByRole('row', { name: new RegExp(other.email) }).getByRole('button', { name: 'Resetar senha' }).click()
  await page.getByRole('button', { name: 'Resetar', exact: true }).click()
  await expect(page.getByTestId('temp-password')).not.toBeEmpty()
})

test('platform admin sees a finished run in the usage and exports it', async ({ page }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  await runToCompletion(page, slug, 'Uso do mês')

  await page.goto('/admin/workspaces')
  await page.getByRole('link', { name: 'Uso' }).click()
  const row = page.getByRole('row').filter({ hasText: `Marca ${slug}` })
  // columns: Mês, Workspace, Usuário, Concluídas, …, Total
  await expect(row.getByRole('cell').nth(2)).toHaveText('E2E')
  await expect(row.getByRole('cell').nth(3)).toHaveText('1')
  await expect(row.getByRole('cell').nth(7)).toHaveText('1')

  const download = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Exportar CSV' }).click()
  const file = await download
  expect(file.suggestedFilename()).toMatch(/^uso-\d{4}-\d{2}\.csv$/)
  expect(readFileSync(await file.path(), 'utf8')).toContain(`Marca ${slug};E2E;`)

  await page.getByRole('button', { name: 'Todos os meses' }).click()
  await expect(page).toHaveURL(/month=todos/)
  await expect(page.getByRole('row').filter({ hasText: `Marca ${slug}` })).toBeVisible()
})

test('platform admin configures, edits and removes the google connector', async ({ page }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  await configureGoogle(page, slug)

  await page.reload()
  const row = page.getByRole('row').filter({ hasText: slug })
  await expect(row.getByText('configurado')).toBeVisible()
  await row.getByRole('button', { name: 'Conector Google' }).click()
  await expect(page.getByLabel('Customer ids')).toHaveValue('1234567890, 2222222222')
  await expect(page.getByLabel('Métrica')).toHaveValue('revenue')

  await page.getByLabel('Customer ids').fill('1234567890, 1234567890')
  await page.getByRole('button', { name: 'Salvar' }).click()
  await expect(page.getByText('Cada customer id tem 10 dígitos, sem repetir.')).toBeVisible()

  await page.getByRole('button', { name: 'Remover conector' }).click()
  await page.getByRole('button', { name: 'Remover', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(row.getByText('configurado')).toHaveCount(0)
})
