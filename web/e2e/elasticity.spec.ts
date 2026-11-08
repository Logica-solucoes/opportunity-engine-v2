import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import { ROOT } from './env'
import { createWorkspace, loggedInAdmin, runToCompletion } from './helpers'

const FIXTURES = join(ROOT, 'tests', 'fixtures', 'results')

test('an inconclusive elasticity shows only its reasons', async ({ page }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  await runToCompletion(page, slug, 'Gol')

  await page.getByRole('link', { name: 'Elasticidade' }).click()
  await expect(page).toHaveURL(/\/elasticidade$/)
  const tab = page.getByRole('region', { name: 'Elasticidade' })
  await expect(tab).toContainText('Análise de elasticidade inconclusiva')
  await expect(tab).toContainText('Nenhum canal com efeito identificável')
  await expect(tab).not.toContainText('R$')
  await expect(tab.locator('.recharts-surface')).toHaveCount(0)
})

test('an identifiable run shows the planner and filters go to the scenario', async ({ page }) => {
  // the fake engine always returns the Gol; this run's results and scenario come from the identifiable synthetic
  await page.route(/\/runs\/\d+\/results$/, (route) => route.fulfill({ path: join(FIXTURES, 'identificavel.json') }))
  const scenarioUrls: string[] = []
  await page.route(/\/runs\/\d+\/scenario(\?|$)/, (route) => {
    scenarioUrls.push(route.request().url())
    return route.fulfill({ path: join(FIXTURES, 'identificavel_scenario.json') })
  })

  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  await runToCompletion(page, slug, 'Sintético')
  await page.getByRole('link', { name: 'Elasticidade' }).click()

  const table = page.getByRole('region', { name: 'Cenários' })
  for (const column of ['Atual', 'Recomendado', 'Saturação']) await expect(table).toContainText(column)
  await expect(table).toContainText('R$')
  await expect(page.getByText('Baixa confiança')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Curva de saturação' }).locator('.recharts-surface')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Mix por canal' })).toContainText('não confia na redistribuição')

  const channels = page.getByRole('region', { name: 'Canais' })
  await expect(channels.getByRole('figure')).toHaveCount(1)
  await expect(channels).toContainText('STRONG')
  await expect(channels).toContainText('NOEFFECT — O intervalo do efeito inclui zero')

  await page.getByLabel('CPA máximo', { exact: true }).fill('5')
  await expect.poll(() => scenarioUrls.some((u) => u.includes('target_cpa=5'))).toBe(true)
})
