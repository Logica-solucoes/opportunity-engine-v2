import { type Browser, expect, type Page, test } from '@playwright/test'
import {
  addMember,
  createSimulation,
  configureGoogle,
  createWorkspace,
  loggedInAdmin,
  newSession,
  runToCompletion,
  template,
  uploadTemplatesAndValidate,
} from './helpers'

async function analystOnNewWorkspace(page: Page, browser: Browser) {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const analyst = await addMember(page, slug, 'analyst')
  return { slug, analystPage: await newSession(browser, analyst) }
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
  // the history is all a viewer sees: the workspace home sends them there
  await expect(viewerPage).toHaveURL(new RegExp(`/w/${slug}/execucoes$`))
  await expect(viewerPage.getByText('Nenhuma execução ainda.')).toBeVisible()
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
  // the reload must land mid-run, or the test would only prove the backlog of a finished run
  await expect(analystPage.getByText('Rodando', { exact: true })).toBeVisible()

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

test('workspace admin deletes a simulation and its runs; analysts never see the button', async ({
  page,
  browser,
}) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const analystPage = await newSession(browser, await addMember(page, slug, 'analyst'))

  const runUrl = await runToCompletion(page, slug, 'Descartável')
  await page.getByRole('link', { name: '← Descartável' }).click()
  const simUrl = page.url()

  await analystPage.goto(simUrl)
  await expect(analystPage.getByRole('heading', { name: 'Descartável' })).toBeVisible()
  await expect(analystPage.getByRole('button', { name: 'Apagar simulação' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Apagar simulação' }).click()
  const confirm = page.getByRole('button', { name: 'Apagar', exact: true })
  await expect(confirm).toBeDisabled()
  await page.getByLabel('Nome da simulação').fill('Descartáve')
  await expect(confirm).toBeDisabled()
  await page.getByLabel('Nome da simulação').fill('Descartável')
  await confirm.click()

  await expect(page).toHaveURL(new RegExp(`/w/${slug}$`))
  await expect(page.getByText('Descartável')).toHaveCount(0)
  await page.goto(runUrl)
  await expect(page.getByText('Execução não encontrada.')).toBeVisible()
  await analystPage.goto(simUrl)
  await expect(analystPage.getByText('Simulação não encontrada.')).toBeVisible()
})

test('analyst imports from google only where the workspace has the connector', async ({ page, browser }) => {
  await loggedInAdmin(page)
  const withGoogle = await createWorkspace(page)
  const without = await createWorkspace(page)
  await configureGoogle(page, withGoogle)
  const analyst = await addMember(page, withGoogle, 'analyst')
  const other = await addMember(page, without, 'analyst')

  const analystPage = await newSession(browser, analyst)
  await createSimulation(analystPage, withGoogle, 'Do Google')
  await expect(analystPage.getByLabel('Início')).toHaveValue(/^\d{4}-\d{2}-\d{2}$/)
  await analystPage.getByRole('button', { name: 'Importar do Google' }).click()
  await expect(analystPage.getByText('Conector Google sem credenciais neste ambiente.')).toBeVisible()
  await expect(analystPage.getByRole('button', { name: 'Importar do Google' })).toBeEnabled()

  const otherPage = await newSession(browser, other)
  await createSimulation(otherPage, without, 'Sem Google')
  await expect(otherPage.getByLabel('Arquivo de investimento')).toBeAttached()
  await expect(otherPage.getByRole('button', { name: 'Importar do Google' })).toHaveCount(0)
})
