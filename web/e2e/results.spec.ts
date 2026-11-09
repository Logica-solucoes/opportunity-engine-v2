import { expect, test } from '@playwright/test'
import { addMember, createWorkspace, loggedInAdmin, newSession, runToCompletion } from './helpers'

test('causal tab shows published events and keeps rejected ones without numbers', async ({ page, browser }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const analyst = await addMember(page, slug, 'analyst')
  const viewer = await addMember(page, slug, 'viewer')
  const analystPage = await newSession(browser, analyst)

  const detailsUrl = await runToCompletion(analystPage, slug, 'Gol')
  await analystPage.getByRole('tab', { name: 'Causal' }).click()
  await expect(analystPage).toHaveURL(/\/causal$/)

  const summary = analystPage.getByRole('region', { name: 'Resumo' })
  await expect(summary).toContainText('52 eventos detectados')
  await expect(summary).toContainText('5 publicados')
  await expect(summary).toContainText('47 rejeitados')

  // the first published event of the Gol: CANAL_06 + CANAL_08, 20/01/2025, -31,1%
  const detail = analystPage.getByRole('region', { name: 'Evento selecionado' })
  await expect(detail).toContainText('CANAL_06, CANAL_08')
  await expect(detail).toContainText('Queda de')
  await expect(detail).toContainText('-31,1%')
  await expect(detail.locator('.recharts-surface').first()).toBeVisible()

  // A9: the published event carries its narrative; the E2E runs with no API key, so it is the deterministic text
  const analysis = detail.getByRole('region', { name: 'Análise' })
  await expect(analysis).toContainText('Texto padrão')
  await expect(analysis).toContainText('Queda de')

  await analystPage.getByRole('radio', { name: 'Todos', exact: true }).click()
  await analystPage.getByRole('button', { name: /Não significativo/ }).first().click()
  await expect(detail).toContainText('Rejeitado')
  await expect(detail).toContainText('Não significativo')
  await expect(detail).not.toContainText('%')
  await expect(detail).not.toContainText('R$')
  await expect(detail.getByRole('region', { name: 'Análise' })).toHaveCount(0)
  await expect(detail.locator('.recharts-surface')).toHaveCount(0)

  await analystPage.getByRole('tab', { name: 'Detalhes' }).click()
  await analystPage.getByRole('button', { name: /Log da execução/ }).click()
  await expect(analystPage.getByRole('log', { name: 'Log da execução' })).toBeVisible()
  await analystPage.getByRole('button', { name: 'Publicar' }).click()
  await expect(analystPage.getByText(/Publicada por/)).toBeVisible()

  const viewerPage = await newSession(browser, viewer)
  await viewerPage.goto(detailsUrl.replace(/\/detalhes$/, ''))
  await expect(viewerPage).toHaveURL(/\/causal$/)
  await expect(viewerPage.getByRole('region', { name: 'Evento selecionado' })).toContainText('Queda de')
})
