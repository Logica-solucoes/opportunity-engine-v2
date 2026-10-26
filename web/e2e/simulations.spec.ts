import { type Browser, expect, type Page, test } from '@playwright/test'
import { addMember, createWorkspace, loggedInAdmin, newSession } from './helpers'

async function analystOnNewWorkspace(page: Page, browser: Browser) {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const analyst = await addMember(page, slug, 'analyst')
  return { slug, analystPage: await newSession(browser, analyst) }
}

async function createSimulation(page: Page, slug: string, name: string) {
  await page.goto(`/w/${slug}`)
  await page.getByRole('link', { name: 'Nova simulação' }).click()
  await page.getByLabel('Nome').fill(name)
  await page.getByRole('button', { name: 'Criar' }).click()
  await expect(page.getByRole('heading', { name })).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`/w/${slug}/simulacoes/\\d+$`))
}

test('analyst creates a simulation and finds it in the list', async ({ page, browser }) => {
  const { slug, analystPage } = await analystOnNewWorkspace(page, browser)
  await expect(analystPage.getByText('Nenhuma simulação ainda.')).toBeVisible()

  await createSimulation(analystPage, slug, 'Black Friday')

  await analystPage.getByRole('link', { name: '← Simulações' }).click()
  await expect(analystPage.getByRole('link', { name: 'Black Friday' })).toBeVisible()
})

test('viewer cannot create or edit simulations', async ({ page, browser }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const viewer = await addMember(page, slug, 'viewer')

  const viewerPage = await newSession(browser, viewer)
  await expect(viewerPage).toHaveURL(new RegExp(`/w/${slug}$`))
  await expect(viewerPage.getByText('Nenhuma simulação ainda.')).toBeVisible()
  await expect(viewerPage.getByRole('link', { name: 'Nova simulação' })).toHaveCount(0)

  await viewerPage.goto(`/w/${slug}/simulacoes/nova`)
  await expect(viewerPage.getByText('Sem permissão para editar simulações deste workspace.')).toBeVisible()
})
