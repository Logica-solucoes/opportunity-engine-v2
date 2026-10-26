import { expect, test } from '@playwright/test'
import { addMember, changePassword, createWorkspace, loggedInAdmin, login, newSession, uid } from './helpers'

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

  await page
    .getByRole('row', { name: new RegExp(member.email) })
    .getByRole('button', { name: 'Remover' })
    .click()
  await page.getByRole('button', { name: 'Remover', exact: true }).last().click()
  await expect(page.getByRole('row', { name: new RegExp(member.email) })).toHaveCount(0)
})

test('workspace admin only links existing accounts and has no controls on their own row', async ({ page, browser }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const wsAdmin = await addMember(page, slug, 'admin')
  const viewer = await addMember(page, slug, 'viewer')

  const adminPage = await (await browser.newContext()).newPage()
  await login(adminPage, wsAdmin.email, wsAdmin.temp)
  await changePassword(adminPage, wsAdmin.temp)
  await adminPage.goto(`/w/${slug}/membros`)
  const own = adminPage.getByRole('row', { name: new RegExp(wsAdmin.email) })
  await expect(own).toBeVisible()
  await expect(own.getByLabel('Papel')).toHaveCount(0)
  await expect(own.getByRole('button', { name: 'Remover' })).toHaveCount(0)
  await expect(adminPage.getByRole('row', { name: new RegExp(viewer.email) }).getByLabel('Papel')).toBeVisible()

  await expect(adminPage.getByLabel('Nome')).toHaveCount(0)
  await adminPage.getByLabel('E-mail').fill(`ninguem-${uid()}@e2e.test`)
  await adminPage.getByRole('button', { name: 'Adicionar' }).click()
  await expect(adminPage.getByRole('alert').filter({ hasText: 'Essa conta não existe' })).toBeVisible()
})

test('platform admin links an existing account leaving the name blank', async ({ page }) => {
  await loggedInAdmin(page)
  const first = await createWorkspace(page)
  const second = await createWorkspace(page)
  const member = await addMember(page, first, 'analyst')

  await page.goto(`/w/${second}/membros`)
  await page.getByLabel('E-mail').fill(member.email)
  await page.getByRole('button', { name: 'Adicionar' }).click()

  await expect(page.getByRole('row', { name: new RegExp(member.email) })).toBeVisible()
})

test('the role select stays disabled while the change is saving', async ({ page }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const member = await addMember(page, slug, 'viewer')
  let release!: () => void
  const held = new Promise<void>((resolve) => (release = resolve))
  await page.route('**/api/w/*/members/*', async (route) => {
    if (route.request().method() === 'PATCH') await held
    await route.fallback()
  })

  const select = page.getByRole('row', { name: new RegExp(member.email) }).getByLabel('Papel')
  await select.selectOption('analyst')
  await expect(select).toBeDisabled()
  release()
  await expect(select).toBeEnabled()
  await expect(select).toHaveValue('analyst')
})

test('a member removed mid-session sees not found and loses the workspace in the header', async ({ page, browser }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const member = await addMember(page, slug, 'analyst')
  const memberPage = await newSession(browser, member)
  await expect(memberPage).toHaveURL(new RegExp(`/w/${slug}$`))
  await expect(memberPage.getByLabel('Workspace')).toBeVisible()

  await page.goto(`/w/${slug}/membros`)
  await page
    .getByRole('row', { name: new RegExp(member.email) })
    .getByRole('button', { name: 'Remover' })
    .click()
  await page.getByRole('button', { name: 'Remover', exact: true }).last().click()
  await expect(page.getByRole('row', { name: new RegExp(member.email) })).toHaveCount(0)

  // what a tab regaining focus does: stale queries refetch
  await memberPage.evaluate(() => window.dispatchEvent(new Event('visibilitychange')))

  await expect(memberPage.getByText('Não encontrado.')).toBeVisible()
  await expect(memberPage.getByLabel('Workspace')).toHaveCount(0)
})
