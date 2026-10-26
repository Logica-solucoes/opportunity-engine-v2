import { fileURLToPath } from 'node:url'
import { type Browser, expect, type Page, test } from '@playwright/test'
import { addMember, createWorkspace, loggedInAdmin, newSession } from './helpers'

const template = (name: string) => fileURLToPath(new URL(`../public/templates/${name}`, import.meta.url))

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

test('analyst uploads the templates, accepts the suggested mapping and validates', async ({ page, browser }) => {
  const { slug, analystPage } = await analystOnNewWorkspace(page, browser)
  await expect(analystPage.getByText('Nenhuma simulação ainda.')).toBeVisible()
  await createSimulation(analystPage, slug, 'Black Friday')

  await analystPage.getByLabel('Arquivo de investimento').setInputFiles(template('investimento.csv'))
  await expect(analystPage.getByText('investimento.csv', { exact: true })).toBeVisible()
  await analystPage.getByLabel('Arquivo de performance').setInputFiles(template('performance.csv'))
  await expect(analystPage.getByText('performance.csv', { exact: true })).toBeVisible()
  await expect(analystPage.getByRole('button', { name: 'Rodar' })).toBeDisabled()
  await expect(analystPage.getByText('Valide os arquivos antes de rodar.')).toBeVisible()

  await analystPage.getByRole('button', { name: 'Validar' }).click()

  await expect(analystPage.getByText('Nenhum problema encontrado.')).toBeVisible()
  await expect(analystPage.getByText('SEARCH, YOUTUBE')).toBeVisible()
  await expect(analystPage.getByRole('button', { name: 'Rodar' })).toBeDisabled()
  await expect(analystPage.getByText('Execução disponível em breve')).toBeVisible()

  await analystPage.getByRole('link', { name: '← Simulações' }).click()
  await expect(analystPage.getByRole('link', { name: 'Black Friday' })).toBeVisible()
})

test('a repeated (date, channel) row shows the pt-BR error and blocks the run', async ({ page, browser }) => {
  const { slug, analystPage } = await analystOnNewWorkspace(page, browser)
  await createSimulation(analystPage, slug, 'Duplicada')

  await analystPage.getByLabel('Arquivo de investimento').setInputFiles({
    name: 'investimento.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('data,canal,investimento\n2024-01-01,SEARCH,100\n2024-01-01,SEARCH,30\n'),
  })
  await expect(analystPage.getByText('investimento.csv', { exact: true })).toBeVisible()
  await analystPage.getByLabel('Arquivo de performance').setInputFiles(template('performance.csv'))
  await expect(analystPage.getByText('performance.csv', { exact: true })).toBeVisible()
  await analystPage.getByRole('button', { name: 'Validar' }).click()

  await expect(analystPage.getByText('1 linha repetida de (data, canal) no investimento')).toBeVisible()
  await expect(analystPage.getByRole('button', { name: 'Rodar' })).toBeDisabled()
  await expect(analystPage.getByText('Corrija os erros antes de rodar.')).toBeVisible()
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
