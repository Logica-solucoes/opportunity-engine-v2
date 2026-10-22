import { expect, test } from '@playwright/test'
import { loggedInAdmin } from './helpers'

test('first login forces a password change, then shows the workspaces', async ({ page }) => {
  await loggedInAdmin(page)
  await expect(page).toHaveURL(/\/$/)
})

test('logout returns to login and protected routes redirect there', async ({ page }) => {
  await loggedInAdmin(page)
  await page.getByRole('button', { name: 'Conta' }).click()
  await page.getByRole('menuitem', { name: 'Sair' }).click()
  await expect(page).toHaveURL(/\/login/)

  await page.goto('/admin/workspaces')
  await expect(page).toHaveURL(/\/login\?redirect=/)
})

test('theme toggle switches to dark and survives a reload', async ({ page }) => {
  await loggedInAdmin(page)
  await page.getByRole('button', { name: 'Tema' }).click()
  await page.getByRole('menuitem', { name: 'Escuro' }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.reload()
  await expect(page.locator('html')).toHaveClass(/dark/)
})
