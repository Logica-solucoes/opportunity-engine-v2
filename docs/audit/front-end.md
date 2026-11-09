# Auditoria do front-end (09/nov/2026)

**Documento de consulta: carregar sob demanda** ao mexer em UI (tela, componente, tema). Plano de execução: `docs/superpowers/plans/2026-11-09-refino-front.md`.

## Como usar (skills)
- Antes de editar uma tela: invocar `redesign-existing-projects` (checklist de redesign; ordem de impacto: fonte, cor, hover/estados, espaçamento, componentes, vazio/erro/carregando, polimento).
- Ao fechar cada tarefa: invocar `web-design-guidelines` nos arquivos tocados (busca as regras do Vercel e devolve `arquivo:linha`); ignorar "Title Case" (pt-BR usa sentence case).
- `design-taste-frontend`: só para tipografia (Geist), cor (um acento, neutros frios, sem roxo/gradiente), raio único, sombra tintada, cards só com hierarquia e contraste. Dashboards estão fora do escopo dela: ignorar hero, eyebrow, marquee, bento, motion pesado.
- Componentes: MCP `shadcn` (`.mcp.json`) antes de montar bloco; só primitivo de `web/src/components/ui/`.
- Verificar: screenshot claro e escuro (`node tools/audit-shots.mjs`, saída em `audit/`, fora do git), `bun run build`, `bun run lint`.

Base: screenshots em `audit/` (1440×900, `fullPage`, claro e escuro), banco de dev, run 7 no motor real (Gol, `inconclusive`). **Revisados a olho: só o tema claro**; o escuro foi gerado e falta conferir. Pendente de aprovação do usuário antes de qualquer edição. Itens 1–10 de "Caça visual" em `docs/status.md` seguem valendo; abaixo só o que os screenshots acrescentam.

## Global
- **Header:** seletor de workspace é `<select>` nativo (seta do SO); links Membros/Admin sem estado ativo; sem indicação de onde estou.
- **Primária coral usada para tudo:** botão, link sublinhado, aba ativa e erro. Sem tokens `success`/`warning`/`info`; todos os badges de status (Concluída, Inconclusiva, Publicada) são cinza.
- **Tabelas:** cabeçalho com o mesmo peso/cor das linhas, sem hover, sem estado vazio. Para "Dense system" falta cabeçalho muted e números em fonte tabular (Geist Mono previsto).
- **Locale:** inputs `date`/`month` nativos mostram "dd/mm/yyyy" e "November 2026" em inglês (`execucoes`, `admin/uso`).
- **Números:** parâmetros no formulário aparecem com ponto (`0.05`), nos resultados com vírgula (`0,05`).

## Por tela
- **/login:** card pequeno em página vazia, sem logo/marca; título "Entrar" não é heading.
- **/ (workspaces) e /w/$slug:** lista de simulações é tabela sem affordance de clique; sem estado vazio.
- **simulacoes/nova:** formulário solto, sem Card, input largo e sem "cancelar/voltar".
- **simulacoes/$id (a pior):** página única de ~2.400 px (arquivos, mapeamento, validação, params, runs, exclusão). 9 selects nativos no mapeamento; grade de parâmetros com larguras irregulares (campos de 1/3 e 1/2 misturados, checkboxes soltos alinhados com inputs); "Rodar" longe da validação; "Apagar simulação" quase invisível (destrutivo pálido) e sem separação clara; `FileDrop` quebrado (item 10); metadados do arquivo em corpo minúsculo. Sugestão: dividir em abas/seções com `Tabs` + `Card`s e `Select`/`Switch` do shadcn.
- **execucoes:** filtros nativos desalinhados em altura; coluna "Motor" mostra hash/`fake` em mono minúsculo.
- **run › causal:** o "Desenho de experimento" é tabela de 20 linhas com canal repetido (Desligar/Aumentar por canal), difícil de ler; mensagem de erro em texto vermelho solto (usar `Alert`); tiles "32 eventos" improvisados; filtro Publicados/Todos parece botão, não toggle (`ToggleGroup`/`Tabs`); master-detail quebrado: "Selecione um evento." flutua ao lado do filtro; "Nenhum evento publicado. Ver todos" é `<p>` solto.
- **run › elasticidade:** duas mensagens dizendo a mesma coisa (card de narrativa + `Alert`); badge "Texto padrão" é críptico. **Gráficos não avaliados**: o run saiu inconclusivo (nenhum canal identificável).
- **run › detalhes:** listas de parâmetros em duas colunas com valores desalinhados entre as colunas; **log vaza caminho local** (`C:\Users\...\Temp\...\response_curve_data.csv`) e mistura inglês/português ("Simulation data exported for UI", "--- Historical Contribution Split ---"): bug do motor/`logmessages.py`, não só visual.
- **membros:** rótulo "Papel" mais alto que os outros do formulário (select nativo muda a altura).
- **admin/workspaces:** botão "Conector Google" repetido em todas as 8 linhas (ruído; virar ícone/menu, badge só quando configurado); link "Membros" coral sublinhado.
- **admin/usuarios, admin/uso:** só conferido `uso`; mês nativo em inglês (acima).

## Lacunas da auditoria
- Abas Causal (detalhe do evento) e Elasticidade (curvas, Recharts) **sem dados reais**: run inconclusivo. Falta um run com canal identificável (outro dataset ou outro agrupamento) para auditar gráficos.
- Tema escuro, `admin/usuarios` e estados vazios/erro/carregando não foram vistos.
- Dados do Gol precisaram de ajuste para validar (datas dd/mm→ISO, `GOOGLE ` com espaço, soma de duplicatas, `GOOGLE DISPLAY/VIDEO`+`KAYAK` fundidos): o validate rejeita o CSV bruto do `exemplo_csv`, vale checar se isso é esperado.

## Passe com as skills de bom gosto (09/nov/2026)

Skills usadas: `web-design-guidelines` (regras do Vercel, grep em `web/src`, ~4.100 linhas fora de `ui/`), `redesign-existing-projects` (checklist de redesign) e `design-taste-frontend`. Esta última declara dashboards fora de escopo (seção 13): aplicadas só tipografia, cor, tokens, estados, consistência de forma e contraste; ignoradas as regras de landing page (hero, eyebrow, marquee, bento). Regra "Title Case" do Vercel ignorada (pt-BR usa sentence case, como pede a `redesign`).

**Já está bom:** nenhum `<div onClick>`, `transition: all` nem `outline-none` sem foco (só `NativeSelect`, que tem `focus-visible:ring`); `aria-label` nos botões de ícone; `Intl`/`toLocale*` com pt-BR; confirmação em ações destrutivas (`AlertDialog` na remoção de membro e na exclusão); reticências `…` corretas.

**Achados novos:**
- `index.html`/tema: sem `color-scheme: dark` no `<html>` (scrollbar e inputs nativos claros no escuro) e sem `<meta name="theme-color">`.
- Só 3 arquivos usam `autoComplete`; e-mail/código sem `spellCheck={false}`; placeholders sem `…` ("Opcional", "Buscar pelo nome").
- `tabular-nums` só em 4 componentes: ficam sem (tabelas de execuções, uso, parâmetros, `ui/table`). Resolver no `Table` base, junto com Geist Mono.
- Títulos sem `text-balance`; `$runId.tsx` tem dois `<h1>` (linhas 73 e 111, conferir se o segundo é estado de erro) e `h2` sem `h1` em partes das abas.
- `date`/`month` nativos (`execucoes`, `admin/uso`, `GoogleImport`) ignoram o locale da página: trocar por `Calendar`/`Popover` do shadcn com pt-BR.
- Formulário de parâmetros sem aviso de alterações não salvas (`useBlocker` do TanStack Router).
- Filtros do histórico em estado local: o guideline pede URL refletindo filtros (search params do router).
- `lucide-react` e `Inter` aparecem como "discouraged" nas duas skills: reforça Phosphor + Geist (já no T0).
- Checklist de redesign: `box-shadow` sem tinta, bordas + fundo em todos os cards (usar `Card` só onde há hierarquia; resto com `divide-y`/espaço), raio único a decidir, badge em pílula para status (trocar por quadrado/ponto semântico com cor).
