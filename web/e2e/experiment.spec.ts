import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import { ROOT } from './env'
import { createWorkspace, loggedInAdmin, runToCompletion } from './helpers'

const FIXTURES = join(ROOT, 'tests', 'fixtures', 'results')
const gol = JSON.parse(readFileSync(join(FIXTURES, 'e2e_gol_publicado.json'), 'utf-8'))
const design = {
  status: 'ok', reasons: [], period_days: 1, target_lift: 0.05, sigma: 120, rho: 0.3, kpi_per_period: 3000,
  duration_periods: 42, duration_days: 42, feasible: true, mde_abs: 6200, mde_rel: 0.049,
  designs: [
    { channel: 'CANAL_03', test_type: 'on_off', step: null, spend_per_period: 1500, budget_at_risk: 63000 },
    { channel: 'CANAL_03', test_type: 'step_up', step: 0.2, spend_per_period: 1500, budget_at_risk: 12600 },
  ],
  assumptions: ['Fórmula provisória até a validação da Data Science.'],
}

test('an inconclusive run shows the experiment design on the causal tab', async ({ page }) => {
  await page.route(/\/runs\/\d+\/results$/, (route) => route.fulfill({ json: { ...gol, experiment_design: design } }))
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  await runToCompletion(page, slug, 'Gol')
  await page.getByRole('tab', { name: 'Causal' }).click()

  const card = page.getByRole('region', { name: 'Desenho de experimento' })
  await expect(card).toContainText('42 dias')
  await expect(card).toContainText(/4,9\s?%/)
  await expect(card.getByRole('row')).toHaveCount(2)
  await expect(card).toContainText('Aumentar orçamento')
  await expect(card).toContainText(/\+20,0\s?%/)
})
