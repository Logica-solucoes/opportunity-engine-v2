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

async function uploadTemplatesAndValidate(page: Page) {
  await page.getByLabel('Arquivo de investimento').setInputFiles(template('investimento.csv'))
  await expect(page.getByText('investimento.csv', { exact: true })).toBeVisible()
  await page.getByLabel('Arquivo de performance').setInputFiles(template('performance.csv'))
  await expect(page.getByText('performance.csv', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Validar' }).click()
  await expect(page.getByText('Nenhum problema encontrado.')).toBeVisible()
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
  await expect(analystPage.getByText('Salve os parâmetros antes de rodar.')).toBeVisible()

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

test('a file over 30 MB or not .csv is refused before any upload', async ({ page, browser }) => {
  const { slug, analystPage } = await analystOnNewWorkspace(page, browser)
  await createSimulation(analystPage, slug, 'Grande')
  let uploads = 0
  analystPage.on('request', (r) => {
    if (r.method() === 'PUT') uploads++
  })
  const input = analystPage.getByLabel('Arquivo de investimento')

  await input.setInputFiles({
    name: 'grande.csv',
    mimeType: 'text/csv',
    buffer: Buffer.alloc(30 * 1024 * 1024 + 1, 'a'),
  })
  await expect(analystPage.getByRole('alert').filter({ hasText: 'Arquivo maior que 30 MB.' })).toBeVisible()

  await input.setInputFiles({ name: 'planilha.xlsx', mimeType: 'application/octet-stream', buffer: Buffer.from('x') })
  await expect(analystPage.getByRole('alert').filter({ hasText: 'Envie um arquivo .csv.' })).toBeVisible()
  expect(uploads).toBe(0)
})

test('a failed background refetch keeps the simulation on screen', async ({ page, browser }) => {
  const { slug, analystPage } = await analystOnNewWorkspace(page, browser)
  await createSimulation(analystPage, slug, 'Instável')
  await analystPage.getByLabel('Arquivo de investimento').setInputFiles(template('investimento.csv'))
  await expect(analystPage.getByText('investimento.csv', { exact: true })).toBeVisible()
  await analystPage.route(/\/api\/w\/[^/]+\/simulations\/\d+$/, (route) =>
    route.request().method() === 'GET' ? route.fulfill({ status: 500, json: {} }) : route.fallback(),
  )

  await analystPage.evaluate(() => window.dispatchEvent(new Event('visibilitychange')))

  await expect(analystPage.getByText('Erro no servidor. Tente de novo.')).toBeVisible()
  await expect(analystPage.getByRole('heading', { name: 'Instável' })).toBeVisible()
  await expect(analystPage.getByText('investimento.csv', { exact: true })).toBeVisible()
})

test('parameters open with the data suggestions, save and persist', async ({ page, browser }) => {
  const { slug, analystPage } = await analystOnNewWorkspace(page, browser)
  await createSimulation(analystPage, slug, 'Parâmetros')
  await uploadTemplatesAndValidate(analystPage)

  // performance.csv has 3 days of history and a "conversoes" KPI
  await expect(analystPage.getByText('Mínimo para série diária: o histórico tem só 3 dias.')).toBeVisible()
  await expect(analystPage.getByLabel('Pré-período mínimo (dias)')).toHaveValue('28')
  await expect(analystPage.getByLabel('Otimizar para')).toHaveValue('CONVERSIONS')
  await expect(analystPage.getByText('Sugerido pelos dados')).toHaveCount(3)
  await expect(analystPage.getByText('Salve os parâmetros antes de rodar.')).toBeVisible()

  await analystPage.getByLabel('Fator limite de investimento').fill('2')
  await analystPage.getByRole('button', { name: 'Salvar parâmetros' }).click()
  await expect(analystPage.getByRole('button', { name: 'Rodar' })).toBeEnabled()
  await expect(analystPage.getByText('Sugerido pelos dados')).toHaveCount(0)

  // an edit still on screen would not reach the run, which uses the saved config
  await analystPage.getByLabel('Fator limite de investimento').fill('3')
  await expect(analystPage.getByRole('button', { name: 'Rodar' })).toBeDisabled()
  await expect(analystPage.getByText('Salve os parâmetros antes de rodar.')).toBeVisible()
  await analystPage.getByLabel('Fator limite de investimento').fill('2.0')
  await expect(analystPage.getByRole('button', { name: 'Rodar' })).toBeEnabled()

  await analystPage.reload()
  await expect(analystPage.getByLabel('Fator limite de investimento')).toHaveValue('2')
  await expect(analystPage.getByLabel('Pré-período mínimo (dias)')).toHaveValue('28')
  await expect(analystPage.getByText('Sugerido pelos dados')).toHaveCount(0)
})

test('an invalid parameter shows its error and gemini unavailable keeps the form', async ({ page, browser }) => {
  const { slug, analystPage } = await analystOnNewWorkspace(page, browser)
  await createSimulation(analystPage, slug, 'Inválido')
  await uploadTemplatesAndValidate(analystPage)

  await analystPage.getByRole('button', { name: 'Sugerir com Gemini' }).click()
  await expect(analystPage.getByText('Sugestão do Gemini indisponível. Os demais campos seguem valendo.')).toBeVisible()
  await expect(analystPage.getByLabel('Pré-período mínimo (dias)')).toHaveValue('28')

  await analystPage.getByLabel('Fator limite de investimento').fill('1')
  await analystPage.getByRole('button', { name: 'Salvar parâmetros' }).click()
  await expect(analystPage.getByText('Deve ser maior que 1.')).toBeVisible()
  await expect(analystPage.getByText('Salve os parâmetros antes de rodar.')).toBeVisible()
})

test('a mistyped optional target is refused instead of saved as no target', async ({ page, browser }) => {
  const { slug, analystPage } = await analystOnNewWorkspace(page, browser)
  await createSimulation(analystPage, slug, 'CPA errado')
  await uploadTemplatesAndValidate(analystPage)

  // "1e" leaves the number input with value "" and validity.badInput
  await analystPage.getByLabel('CPA alvo', { exact: true }).pressSequentially('1e')
  await analystPage.getByRole('button', { name: 'Salvar parâmetros' }).click()
  await expect(analystPage.getByText('Informe um número.')).toBeVisible()
  await expect(analystPage.getByText('Salve os parâmetros antes de rodar.')).toBeVisible()
})

test('analyst runs a simulation and the log resumes after a reload', async ({ page, browser }) => {
  const { slug, analystPage } = await analystOnNewWorkspace(page, browser)
  await createSimulation(analystPage, slug, 'Rodada')
  await uploadTemplatesAndValidate(analystPage)
  await analystPage.getByRole('button', { name: 'Salvar parâmetros' }).click()

  await analystPage.getByRole('button', { name: 'Rodar' }).click()

  await expect(analystPage).toHaveURL(new RegExp(`/w/${slug}/execucoes/\\d+$`))
  const log = analystPage.getByRole('log', { name: 'Log da execução' })
  await expect(log.getByText('Lendo os arquivos de investimento e performance')).toBeVisible()

  await analystPage.reload()

  await expect(analystPage.getByText('Concluída', { exact: true })).toBeVisible()
  await expect(log.getByText('Lendo os arquivos de investimento e performance')).toBeVisible()
  await expect(log.getByText('Montando o resultado')).toBeVisible()
  await expect(analystPage.getByText('Execução concluída. Os dashboards chegam em breve.')).toBeVisible()

  await analystPage.getByRole('link', { name: '← Rodada' }).click()
  await expect(analystPage.getByRole('heading', { name: 'Execuções' })).toBeVisible()
  await expect(analystPage.getByRole('cell', { name: 'Concluída' })).toBeVisible()
  await expect(analystPage.getByRole('button', { name: 'Rodar' })).toBeEnabled()
})
