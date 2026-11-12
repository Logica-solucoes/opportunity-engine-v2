# Lições das rodadas com time de agentes

Fatos deste projeto que um time de agentes (`agent-team`) aprendeu na prática: segurança, gates, ambiente. Leia antes de montar os briefs; cada linha que tocar a rodada vai para o brief do agente que precisa dela.

Rodadas: B7 export, A9 grounding, A7 backend + B11 sem servidor (2026-11-08).

## Segurança

- Atrás do nginx, rate limit por IP usa `$remote_addr`. `$proxy_add_x_forwarded_for` com uvicorn `FORWARDED_ALLOW_IPS=*` pega o XFF mais à esquerda, que o cliente forja. Liste essas invariantes no brief do revisor.

## Gates e tempos

- Pytest completo: 18–48 min; suíte do engine ~28 min; testes de rota ~5 min. Devs rodam só os seus arquivos; o consolidador roda a suíte inteira.
- E2E falha sob carga (6 falhas com CPU a 97% de pytest de outros agentes; 36/36 sozinho): o consolidador roda os gates em sequência, com a máquina quieta.
- O Postgres de dev é compartilhado entre sessões e worktrees: um usuário vazado por outra sessão quebrou um teste e as esperas de 15 s do E2E oscilaram. No preflight, procure outras sessões; reexecute uma falha sozinha antes de julgar.
- Falha pré-existente: prove uma vez (arquivos intocados na branch + rodada no commit pai) e avise o time todo.

## Ambiente (Windows)

- O worktree guard recusa git reescrito pelo `rtk` no Bash: rode git pelo PowerShell.
- `mise run e2e` falha em worktree (`mise.toml` não confiável); `bun run e2e` é equivalente.
- O Playwright MCP não chega aos subagentes e o Vite não abre a :5173 (EACCES, faixa reservada do Hyper-V): sirva `web/dist` pela API e dirija `@playwright/test` por script.
- Docker Desktop pode estar desligado: suba e confirme antes de spawnar.
- Conferência visual cria admin e workspace de teste no banco de dev: o brief pede para apagar.

## Docs

- O parágrafo "Estado atual" do CLAUDE.md muda em quase toda feature: nomeie esse trecho no brief do dev de docs. É também onde os rebases conflitam; um merge de 3 vias por linha resolve as repetições.
- O dev de docs edita cedo e commita só depois que os números saem (contagens, screenshots), para o texto bater com o que rodou.

## Features com LLM

- Um fake que devolve texto sem números esconde os bugs de grounding. Antes de dar como pronto: uma rodada com a chave real e um `/code-review high` fora do plano; deixe um teste de contrato ao vivo.
