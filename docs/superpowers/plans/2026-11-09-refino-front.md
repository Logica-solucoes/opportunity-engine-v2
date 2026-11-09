# Refino do front-end para a demo de quinta (13/nov/2026)

Direção (decidida em 09/nov): shadcn `radix-nova` de verdade, sóbrio, neutros frios, coral da Almap só como acento (CTA, aba ativa, foco). Status com cores semânticas próprias. Menos texto: dica em tooltip, título só onde orienta. Ordem da demo: **resultados → parâmetros → workspace → resto** (o resto só se sobrar tempo). Base: `docs/audit/front-end.md` e itens 1–10 de `docs/status.md`.

Regras: só primitivo shadcn (`bunx shadcn@latest add`), consultar o MCP do shadcn (`.mcp.json`, reiniciar a sessão para carregar) antes de montar bloco; `Write`/`Edit` em `web/src/routes/**`; screenshot (claro e escuro) antes de dar cada tarefa por pronta; `bun run build` e `bun run lint` verdes; um commit por tarefa.

## T0 Fundação (primeiro; tudo depende dela)
1. Tokens em `index.css`: neutros frios, `--success/--warning/--info` (+ foreground) claro/escuro, coral só em `--primary`/`--ring`, raio único (hoje 0.75rem; testar 0.5rem), sombras mínimas.
2. Fonte: Geist Sans + Geist Mono (`@fontsource-variable/geist`, `geist-mono`), `tabular-nums` nas tabelas e números.
3. Ícones: lucide → Phosphor nos 11 arquivos; `components.json` `iconLibrary`.
4. Primitivos novos: `select`, `tabs`, `skeleton`, `separator`, `switch`, `tooltip`, `sonner`, `textarea`, `popover`, `toggle-group`, `collapsible`/`accordion`, `empty` (estado vazio), `field` se existir no registry. Remover `NativeSelect`.
5. `Badge` com variantes de status (success/warning/destructive/info/neutral) e `RunStatusBadge` usando-as.
6. `AppHeader`: `Select` do shadcn para workspace, link ativo, ícones Phosphor.
7. Tabela: cabeçalho muted, hover, fonte tabular; `LoadState` com `Skeleton`; estado vazio padrão (`Empty`).

## T1 Resultados (demo)
- **Layout do run:** abas via `Tabs` ligadas ao router; cabeçalho compacto (título, status, meta numa linha).
- **Causal:** "Desenho de experimento" agrupado por canal (uma linha por canal, duas colunas Desligar/Aumentar), erro em `Alert`; tiles de contagem num `Card` com 3 métricas; filtro com `ToggleGroup`; master-detail (lista de eventos | detalhe) com `ScrollArea` e estado vazio decente; evento rejeitado continua sem número (`docs/decisoes/dashboards.md`).
- **Elasticidade:** uma mensagem só (some a duplicata narrativa/alert); curvas por canal em `Card`s consistentes; "Texto padrão" vira tooltip.
- **Detalhes:** parâmetros em `Card` com grade alinhada, mapeamento e entradas em tabela, log em `Collapsible` fechado por padrão; traduzir/esconder o caminho local do log (`engine/logmessages.py`).
- Precisa de um run com canal identificável para ver os gráficos (rodar outro dataset ou o fake #5).

## T2 Parâmetros e simulação (demo)
- **`simulacoes/$id` em passos:** `Tabs` ou stepper: Arquivos → Mapeamento → Parâmetros → Execuções; "Rodar" fixo num rodapé/ação principal.
- **Corrigir o `FileDrop`** (item 10, não abre o seletor): diagnosticar e refazer sobre o `file-upload-04` do blocks.so.
- **Mapeamento:** `Select`s numa grade de 3 colunas, uma linha por arquivo.
- **`ParamsForm`:** seções em `Card`/`Accordion` (Objetivo, Metas, Orçamento, Causal avançado fechado), `Switch` no lugar dos checkboxes, número com vírgula (pt-BR), dicas em `Tooltip`, valores padrão visíveis.
- "Apagar simulação" numa zona de perigo discreta (`AlertDialog` já existe).

## T3 Workspace (demo)
- Home: cartões de workspace com papel em `Badge`; `/w/$slug`: lista de simulações como tabela limpa com ação principal "Nova simulação", estado vazio.
- `simulacoes/nova`: dentro de `Card`, ou vira `Dialog` na lista.
- `execucoes`: filtros em barra única com `Select`/`DatePicker` (locale pt-BR), status coloridos, coluna Motor discreta.

## T4 O resto (se sobrar tempo)
Login (card com marca), `trocar-senha`, `membros`, `admin/*` (abas via `Tabs`; botão "Conector Google" por linha vira menu/ícone; mês em pt-BR).

## Fechamento
Passe final de screenshots claro/escuro em todas as telas, atualizar `docs/status.md`, `docs/decisoes/dashboards.md` e a seção "UI stack" do `CLAUDE.md` (Phosphor, Geist, primitivos).
