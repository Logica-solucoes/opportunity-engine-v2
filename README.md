<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://shieldcn.dev/header/graph.svg?title=Marketing+GEM&subtitle=Quanto+cada+real+em+m%C3%ADdia+trouxe%2C+e+quanto+ainda+pode+trazer&font=geist&align=left&mode=dark" />
    <img alt="Marketing GEM" src="https://shieldcn.dev/header/graph.svg?title=Marketing+GEM&subtitle=Quanto+cada+real+em+m%C3%ADdia+trouxe%2C+e+quanto+ainda+pode+trazer&font=geist&align=left&mode=light" />
  </picture>
</p>

<p align="center">
  <a href="https://github.com/Logica-solucoes/opportunity-engine-v2/actions/workflows/ci.yml"><img alt="CI" src="https://shieldcn.dev/github/ci/Logica-solucoes/opportunity-engine-v2.svg?workflow=ci.yml&variant=secondary" /></a>
  <img alt="Python 3.13" src="https://shieldcn.dev/badge/Python-3.13-3776AB.svg?logo=python&variant=secondary" />
  <img alt="FastAPI" src="https://shieldcn.dev/badge/FastAPI-API-009688.svg?logo=fastapi&variant=secondary" />
  <img alt="React 19" src="https://shieldcn.dev/badge/React-19-61DAFB.svg?logo=react&variant=secondary" />
  <img alt="PostgreSQL 16" src="https://shieldcn.dev/badge/PostgreSQL-16-4169E1.svg?logo=postgresql&variant=secondary" />
  <a href="https://github.com/Logica-solucoes/opportunity-engine-v2/commits/main"><img alt="Último commit" src="https://shieldcn.dev/github/last-commit/Logica-solucoes/opportunity-engine-v2.svg?variant=secondary" /></a>
</p>

O Marketing GEM é uma plataforma para analisar investimento em mídia, feita para a AlmapBBDO (Omnicom). Você sobe os CSVs de investimento e resultado de uma marca, e ela responde duas perguntas:

1. **Uma campanha ou evento mudou alguma coisa?** A análise causal compara o que aconteceu com o que teria acontecido sem o evento.
2. **Onde ainda vale colocar dinheiro?** A análise de saturação mostra, canal por canal, a partir de que ponto o investimento extra para de render, respeitando os limites de CPA e ROAS que você definir.

Cada marca tem seu workspace. Os runs rodam em segundo plano e ficam guardados no histórico, com dashboards, simulador de cenários, narrativa em texto e export em CSV.

Este repositório substitui o protótipo em Streamlit (Max Impact Engine).

## Como está organizado

O projeto tem duas partes que conversam por um contrato (o `results.json`):

| Pasta | O que é |
|-|-|
| `engine/` | O motor estatístico. Python puro, roda sozinho pela linha de comando. Toda a matemática mora aqui. |
| `api/` | FastAPI + Postgres: login, workspaces, upload, fila de runs, export. |
| `web/` | O front em React. Só mostra o que o motor calculou, nunca refaz conta. |
| `llm/` | Acesso ao Gemini, usado nas sugestões de parâmetro e nas narrativas. |
| `deploy/` | Compose de produção, backup e restore. |

## Rodando localmente

Precisa de Docker, [mise](https://mise.jdx.dev), [uv](https://docs.astral.sh/uv/) e [bun](https://bun.sh).

```bash
docker compose up -d                                  # Postgres em :5432
mise run db-migrate                                   # aplica as migrations
mise run create-admin voce@exemplo.com "Seu Nome"     # imprime uma senha temporária
mise run api                                          # API em :8000
mise run web                                          # front em :5173
```

Abra `http://localhost:5173` e entre com a senha que o `create-admin` mostrou. No primeiro login ele pede para trocar.

Sem `.env`, valem os defaults do `.env.example`. A chave do Gemini (`GEMINI_API_KEY`) é opcional: sem ela, as sugestões de parâmetro saem só das regras sobre os dados e as narrativas usam um texto fixo.

## Testes

```bash
mise run test      # pytest (API, motor, LLM)
mise run e2e       # Playwright contra a app de verdade
mise run parity    # confere os números do motor contra um snapshot fixo (só Linux, ~95 s)
```

Dá para rodar o motor sem a plataforma:

```bash
uv run python -m engine --config run.json --out saida/
```

## Deploy

Uma imagem Docker serve a API, o front e o worker. O alvo é um servidor próprio com Docker, sem nuvem gerenciada. O passo a passo está em [`docs/deploy.md`](docs/deploy.md).

## Onde ler mais

- [`docs/m2/README.md`](docs/m2/README.md): a spec do projeto. Em dúvida sobre escopo, ela decide.
- [`docs/CODEBASE_MAP.md`](docs/CODEBASE_MAP.md): mapa do código, endpoints e schema.
- [`docs/decisoes/`](docs/decisoes/): o porquê de cada escolha.
- [`docs/status.md`](docs/status.md): o que já está pronto e o que falta.
- `CODE-STYLE.md`, `DATABASE.md`, `API-GUIDE.md` e `SECURITY.md`: as regras de cada área. Leia a da parte que você vai mexer.

O BRD do cliente é confidencial e não fica no repositório. Peça ao time.
