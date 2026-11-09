// Screenshots de todas as telas em claro e escuro, para a auditoria visual.
// Uso (com API e web no ar): AUDIT_EMAIL=... AUDIT_PASSWORD=... [AUDIT_WS=b6 AUDIT_SIM=14 AUDIT_RUN=7] node tools/audit-shots.mjs
// Saída em audit/ (fora do git).
import { createRequire } from 'node:module'
import { mkdirSync } from 'node:fs'
const { chromium } = createRequire(import.meta.url)('../web/node_modules/playwright-core')

const U = process.env.AUDIT_URL ?? 'http://localhost:5173'
const { AUDIT_EMAIL: email, AUDIT_PASSWORD: password } = process.env
const ws = process.env.AUDIT_WS ?? 'b6'
const sim = process.env.AUDIT_SIM ?? '1'
const run = process.env.AUDIT_RUN ?? '1'
if (!email || !password) throw new Error('defina AUDIT_EMAIL e AUDIT_PASSWORD')

const routes = [
  ['login', '/login', false],
  ['home', '/'],
  ['ws', `/w/${ws}`],
  ['sim-nova', `/w/${ws}/simulacoes/nova`],
  ['sim-detalhe', `/w/${ws}/simulacoes/${sim}`],
  ['execucoes', `/w/${ws}/execucoes`],
  ['run-causal', `/w/${ws}/execucoes/${run}/causal`],
  ['run-elasticidade', `/w/${ws}/execucoes/${run}/elasticidade`],
  ['run-detalhes', `/w/${ws}/execucoes/${run}/detalhes`],
  ['membros', `/w/${ws}/membros`],
  ['admin-workspaces', '/admin/workspaces'],
  ['admin-usuarios', '/admin/usuarios'],
  ['admin-uso', '/admin/uso'],
]

mkdirSync('audit', { recursive: true })
const browser = await chromium.launch()
for (const theme of ['claro', 'escuro']) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: theme === 'claro' ? 'light' : 'dark' })
  await ctx.addInitScript((t) => localStorage.setItem('theme', t), theme === 'claro' ? 'light' : 'dark')
  const page = await ctx.newPage()
  let logged = false
  for (const [i, [name, path, auth]] of routes.entries()) {
    if (auth !== false && !logged) {
      await page.goto(U + '/login')
      await page.getByLabel('E-mail').fill(email)
      await page.getByLabel('Senha').fill(password)
      await page.getByRole('button', { name: 'Entrar' }).click()
      await page.waitForURL(U + '/')
      logged = true
    }
    await page.goto(U + path)
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(800)
    await page.screenshot({ path: `audit/${String(i + 1).padStart(2, '0')}-${name}-${theme}.png`, fullPage: true })
  }
  await ctx.close()
}
await browser.close()
