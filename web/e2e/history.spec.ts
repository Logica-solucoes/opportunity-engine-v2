import { expect, test } from '@playwright/test'
import { addMember, createWorkspace, loggedInAdmin, newSession, runToCompletion } from './helpers'

test('analyst filters the history, publishes a run and the viewer sees only that one', async ({ page, browser }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const analyst = await addMember(page, slug, 'analyst')
  const viewer = await addMember(page, slug, 'viewer')
  const analystPage = await newSession(browser, analyst)

  await runToCompletion(analystPage, slug, 'Verão')
  await runToCompletion(analystPage, slug, 'Inverno')
  await analystPage.getByRole('button', { name: 'Publicar' }).click()
  await expect(analystPage.getByText(/Publicada por Pessoa E2E/)).toBeVisible()

  await analystPage.goto(`/w/${slug}`)
  await analystPage.getByRole('link', { name: 'Execuções' }).click()
  await expect(analystPage.getByRole('cell', { name: 'Verão' })).toBeVisible()
  await expect(analystPage.getByRole('cell', { name: 'Inverno' })).toBeVisible()

  await analystPage.getByLabel('Simulação').fill('verão')
  await expect(analystPage.getByRole('cell', { name: 'Inverno' })).toHaveCount(0)
  await expect(analystPage.getByRole('cell', { name: 'Verão' })).toBeVisible()
  await expect(analystPage).toHaveURL(/q=ver/)

  await analystPage.getByLabel('Status').selectOption('failed')
  await expect(analystPage.getByText('Nenhuma execução com esses filtros.')).toBeVisible()
  await analystPage.getByRole('button', { name: 'Limpar filtros' }).click()
  await expect(analystPage.getByRole('cell', { name: 'Inverno' })).toBeVisible()
  await expect(analystPage.getByRole('cell', { name: 'Verão' })).toBeVisible()

  const viewerPage = await newSession(browser, viewer)
  await expect(viewerPage).toHaveURL(new RegExp(`/w/${slug}/execucoes$`))
  await expect(viewerPage.getByRole('cell', { name: 'Inverno' })).toBeVisible()
  await expect(viewerPage.getByRole('cell', { name: 'Verão' })).toHaveCount(0)

  await viewerPage.getByRole('link', { name: /^#\d+$/ }).click()
  await expect(viewerPage.getByText('investimento.csv', { exact: true })).toBeVisible()
  await expect(viewerPage.getByRole('link', { name: 'investimento.csv' })).toHaveCount(0)
  await expect(viewerPage.getByRole('button', { name: 'Despublicar' })).toHaveCount(0)
  await expect(viewerPage.getByRole('button', { name: 'Rodar de novo' })).toHaveCount(0)
})

test('rodar de novo restores the run parameters and the inputs download', async ({ page, browser }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const analystPage = await newSession(browser, await addMember(page, slug, 'analyst'))

  const runUrl = await runToCompletion(analystPage, slug, 'Reprise')
  await expect(analystPage.getByText('Fator limite de investimento')).toBeVisible()

  const download = analystPage.waitForEvent('download')
  await analystPage.getByRole('link', { name: 'investimento.csv' }).click()
  expect((await download).suggestedFilename()).toBe('investimento.csv')

  await analystPage.getByRole('link', { name: '← Reprise' }).click()
  const factor = analystPage.getByLabel('Fator limite de investimento')
  const original = await factor.inputValue()
  await factor.fill('3')
  await analystPage.getByRole('button', { name: 'Salvar parâmetros' }).click()
  await expect(analystPage.getByRole('button', { name: 'Rodar' })).toBeEnabled()

  await analystPage.goto(runUrl)
  await analystPage.getByRole('button', { name: 'Rodar de novo' }).click()
  await analystPage.getByRole('button', { name: 'Substituir' }).click()

  await expect(analystPage).toHaveURL(new RegExp(`/w/${slug}/simulacoes/\\d+$`))
  await expect(analystPage.getByLabel('Fator limite de investimento')).toHaveValue(original)
})
