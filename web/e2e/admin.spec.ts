import { expect, test } from '@playwright/test'
import { createAdmin, createWorkspace, loggedInAdmin } from './helpers'

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
