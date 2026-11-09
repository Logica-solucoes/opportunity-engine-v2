import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { expect, type Page, test } from '@playwright/test'
import { ROOT } from './env'
import { createWorkspace, loggedInAdmin, runToCompletion } from './helpers'

const FIXTURES = join(ROOT, 'tests', 'fixtures', 'results')
const EVENTS_HEADER =
  'Evento;Canais;Início;Fim;Veredito;Motivos;Lift;Lift IC inferior;Lift IC superior;Lift %;p-valor;' +
  'Variação do investimento %;Investimento incremental;CPA incremental;R²;WMAPE;Placebo p-valor;Robustez p-valor'

const runIdOf = (url: string) => url.match(/execucoes\/(\d+)/)![1]

// in print main is 186 mm wide and the charts redraw at that width: none may pass its right edge
const chartsPastTheEdge = (page: Page) =>
  page.evaluate(() => {
    const edge = document.querySelector('main')!.getBoundingClientRect().right + 1
    return Array.from(document.querySelectorAll('.recharts-surface')).filter((s) => s.getBoundingClientRect().right > edge)
      .length
  })

async function savePdf(page: Page, name: string) {
  // kept in test-results/ for a look by eye: legible on A4, no chart cut
  const pdf = await page.pdf({ format: 'A4', path: test.info().outputPath(name) })
  expect(pdf.byteLength).toBeGreaterThan(10_000)
}

test('the causal tab downloads the events csv and prints with the run header', async ({ page }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const runId = runIdOf(await runToCompletion(page, slug, 'Gol'))
  await page.getByRole('tab', { name: 'Causal' }).click()
  await expect(page).toHaveURL(/\/causal$/)

  const downloading = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Baixar CSV' }).click()
  const download = await downloading
  expect(download.suggestedFilename()).toBe(`execucao-${runId}-eventos.csv`)
  const text = await readFile(await download.path(), 'utf8')
  expect(text.charCodeAt(0)).toBe(0xfeff)
  const lines = text.slice(1).trimEnd().split('\n')
  expect(lines[0]).toBe(EVENTS_HEADER)
  expect(lines).toHaveLength(53) // the Gol's 52 events
  expect(lines.find((l) => l.startsWith('default_advertiser_CANAL_06,_CANAL_08_2025-01-20;'))).toContain(
    ';publicado;;-514366,04;',
  )

  const header = page.getByRole('region', { name: 'Cabeçalho de impressão' })
  await expect(header).toBeHidden()
  // the app in the dark theme still prints light
  await page.evaluate(() => document.documentElement.classList.add('dark'))
  await page.emulateMedia({ media: 'print' })

  await expect(header).toBeVisible()
  await expect(header).toContainText(slug)
  await expect(header).toContainText('Gol')
  await expect(header).toContainText(`Execução #${runId} · Inconclusiva`)
  await expect(header).toContainText('motor')
  await expect(header).not.toContainText('Grounding')
  await expect(page.getByRole('navigation', { name: 'Seções da execução' })).toBeHidden()
  await expect(page.getByRole('link', { name: 'Baixar CSV' })).toBeHidden()
  await expect(page.getByRole('region', { name: 'Evento selecionado' }).locator('.recharts-surface').first()).toBeVisible()
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe('rgb(255, 255, 255)')
  expect(await page.evaluate(() => getComputedStyle(document.body).color)).toBe('rgb(28, 31, 38)')
  await expect.poll(() => chartsPastTheEdge(page)).toBe(0)
  await savePdf(page, 'causal.pdf')
})

test('the elasticity tab links the csvs with the filters on screen and prints their summary', async ({ page }) => {
  // the fake engine always returns the Gol, whose elasticity is refused (409); results and scenario come from the
  // identifiable synthetic, and what the two CSV routes write is covered by tests/api/test_exports.py
  await page.route(/\/runs\/\d+\/results$/, (route) => route.fulfill({ path: join(FIXTURES, 'identificavel.json') }))
  await page.route(/\/runs\/\d+\/scenario(\?|$)/, (route) =>
    route.fulfill({ path: join(FIXTURES, 'identificavel_scenario.json') }),
  )

  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const runId = runIdOf(await runToCompletion(page, slug, 'Sintético'))
  await page.getByRole('tab', { name: 'Elasticidade' }).click()

  const base = `/api/w/${slug}/runs/${runId}`
  const scenarioCsv = page.getByRole('link', { name: 'Cenários CSV' })
  const curveCsv = page.getByRole('link', { name: 'Curva CSV' })
  await expect(scenarioCsv).toHaveAttribute('href', `${base}/scenario.csv`)
  await expect(curveCsv).toHaveAttribute('href', `${base}/curve.csv`)
  await page.getByLabel('CPA máximo', { exact: true }).fill('5')
  await expect(scenarioCsv).toHaveAttribute('href', `${base}/scenario.csv?target_cpa=5`)
  await expect(curveCsv).toHaveAttribute('href', `${base}/curve.csv?target_cpa=5`)

  const summary = page.getByText(/^Filtros \(valores mensais\):/)
  await expect(summary).toBeHidden()
  await page.emulateMedia({ media: 'print' })

  await expect(page.getByRole('complementary', { name: 'Filtros' })).toBeHidden()
  await expect(summary).toBeVisible()
  await expect(summary).toContainText(/CPA máximo R\$\s5,00/)
  await expect(scenarioCsv).toBeHidden()
  await expect(page.getByRole('region', { name: 'Cabeçalho de impressão' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Curva de saturação' }).locator('.recharts-surface')).toBeVisible()
  await expect.poll(() => chartsPastTheEdge(page)).toBe(0)
  await savePdf(page, 'elasticidade.pdf')
})
