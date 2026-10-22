import { expect, test } from '@playwright/test'
import { addMember, changePassword, createWorkspace, loggedInAdmin, login } from './helpers'

test('analyst gets a temp password, logs in and lands on the only workspace', async ({ page, browser }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const other = await createWorkspace(page)
  const analyst = await addMember(page, slug, 'analyst')

  const analystPage = await (await browser.newContext()).newPage()
  await login(analystPage, analyst.email, analyst.temp)
  await changePassword(analystPage, analyst.temp)
  await expect(analystPage).toHaveURL(new RegExp(`/w/${slug}$`))
  await expect(analystPage.getByRole('link', { name: 'Membros' })).toHaveCount(0)
  await expect(analystPage.getByRole('link', { name: 'Admin' })).toHaveCount(0)

  await analystPage.goto(`/w/${other}`)
  await expect(analystPage.getByText('Página não encontrada.')).toBeVisible()
  await analystPage.goto('/admin/workspaces')
  await expect(analystPage.getByText('Página não encontrada.')).toBeVisible()
  await analystPage.goto(`/w/${slug}/membros`)
  await expect(analystPage.getByText('Sem permissão')).toBeVisible()
})

test('five wrong passwords lock the account', async ({ page, browser }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const member = await addMember(page, slug, 'viewer')

  const other = await (await browser.newContext()).newPage()
  for (let i = 0; i < 6; i++) {
    await login(other, member.email, 'senha-errada-123')
    await expect(other.getByText(/inválidos|bloqueada/)).toBeVisible()
  }
  await expect(other.getByText(/Conta bloqueada\. Tente de novo em \d+ min\./)).toBeVisible()
})

test('workspace admin changes a role and removes a member', async ({ page }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const member = await addMember(page, slug, 'viewer')

  const row = page.getByRole('row', { name: new RegExp(member.email) })
  await Promise.all([
    page.waitForResponse((r) => r.request().method() === 'PATCH' && r.ok()),
    row.getByLabel('Papel').selectOption('analyst'),
  ])
  await page.reload()
  await expect(page.getByRole('row', { name: new RegExp(member.email) }).getByLabel('Papel')).toHaveValue('analyst')

  await page.getByRole('row', { name: new RegExp(member.email) }).getByRole('button', { name: 'Remover' }).click()
  await page.getByRole('button', { name: 'Remover', exact: true }).last().click()
  await expect(page.getByRole('row', { name: new RegExp(member.email) })).toHaveCount(0)
})
