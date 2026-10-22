import { expect, test } from '@playwright/test'
import { changePassword, createAdmin, loggedInAdmin, login } from './helpers'

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

test('login returns to a same-site redirect, also through the forced password change', async ({ page }) => {
  const admin = createAdmin()
  await page.goto('/admin/usuarios')
  await expect(page).toHaveURL(/\/login\?redirect=/)
  await page.getByLabel('E-mail').fill(admin.email)
  await page.getByLabel('Senha', { exact: true }).fill(admin.temp)
  await page.getByRole('button', { name: 'Entrar' }).click()
  await changePassword(page, admin.temp)
  await expect(page).toHaveURL(/\/admin\/usuarios$/)

  await page.goto('/login?redirect=/admin/workspaces')
  await expect(page).toHaveURL(/\/admin\/workspaces$/)
  await page.goto('/login?redirect=//evil.com')
  await expect(page).toHaveURL(/^http:\/\/localhost:\d+\/$/)
})

test('the forced password change screen has a way out', async ({ page }) => {
  const admin = createAdmin()
  await login(page, admin.email, admin.temp)
  await expect(page).toHaveURL(/\/trocar-senha/)
  await page.getByRole('button', { name: 'Sair' }).click()
  await expect(page).toHaveURL(/\/login/)
})
