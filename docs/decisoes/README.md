# Decisões

Por que cada parte do Marketing GEM é do jeito que é. O texto guarda o sintoma junto com a decisão, de propósito: sem o sintoma a regra parece arbitrária e é desfeita na primeira refatoração. Um arquivo por área, criado quando a área ganha sua primeira decisão real (sem placeholders vazios).

Divisão de trabalho: o `CLAUDE.md` e os arquivos da raiz (`CODE-STYLE.md`, `DATABASE.md`, `API-GUIDE.md`, `SECURITY.md`) dizem **as regras**, o `docs/CODEBASE_MAP.md` (quando existir) diz **onde** as coisas estão, estes arquivos dizem **por quê**. O plano do M2 (`docs/m2/README.md`) vence em dúvida de escopo, contrato ou schema.

| Arquivo | Cobre |
| --- | --- |
| [infra-e-operacao.md](infra-e-operacao.md) | Imagem única, health, SPA, CI, dependências |
| [auth.md](auth.md) | Sessão, cookie, CSRF, 404 × 403, papéis, bloqueio, bootstrap, guardas do front, workspace na URL, tema |
| [upload-e-storage.md](upload-e-storage.md) | Simulação como rascunho, mapeamento antes do validate, limite de 30 MB, storage local por conteúdo, leitura do CSV, validate falso até o A2 |

Ao concluir uma tarefa que muda alguma dessas decisões, atualize o arquivo da área no mesmo commit.
