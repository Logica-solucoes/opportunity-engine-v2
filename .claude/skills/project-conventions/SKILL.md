---
name: project-conventions
description: Use when writing or reviewing any Marketing GEM code - workspace scoping, 404-not-403, math only in Python, column_mapping, logging, migrations and scope boundaries
user-invocable: false
---

# Marketing GEM — Convenções do Projeto

As regras moram em quatro arquivos na raiz. Leia o do ramo que a tarefa toca **antes** de escrever código:

| Ramo | Arquivo |
|---|---|
| Qualquer código: ferramentas, idioma, dinheiro, erro, testes, commits, regras do motor | `CODE-STYLE.md` |
| Model, migration, query, coluna | `DATABASE.md` |
| Rota REST, schema Pydantic, status de erro, cliente do frontend | `API-GUIDE.md` |
| Auth, sessão, papéis, workspace, segredo, dado de outro workspace | `SECURITY.md` |

Plano e contrato: `docs/m2/README.md` (vence em escopo, contrato A↔B e schema; ele responde ao BRD). Porquê de cada regra: `docs/decisoes/<área>.md`. Se a spec contradisser um desses arquivos, corrija o arquivo.

As regras que valem em todo ramo:

- Toda rota e query é escopada por workspace via dependência do FastAPI que checa a membership; recurso de outro workspace → **404, nunca 403**.
- A matemática fica só em Python (`engine/`); o front nunca recalcula curva, CPA ou ponto ótimo.
- Nunca hardcode nome de coluna: resolva por `column_mapping`.
- Nada de `print()`: `log = logging.getLogger(__name__)`.
- Segredo só por env; senha nunca em log.
- Migration Alembic com `downgrade` que funciona; tabelas do `DATABASE.md` e do `API-GUIDE.md` atualizadas no mesmo commit.
