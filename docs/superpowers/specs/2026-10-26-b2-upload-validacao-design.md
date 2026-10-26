# B2 · Upload, armazenamento e validação — design

Data: 26/out/2026. Item: B2 em `docs/m2/trilha-b-plataforma.md`. Contrato do `validate` em `docs/m2/README.md` › contrato §2.

## Objetivo e recorte

O analista cria uma simulação, sobe investimento, performance e trends (opcional), confirma o mapeamento de colunas e vê o `ValidationReport`. Dividido como o B1: **B2a** (backend) e **B2b** (telas), cada um com seu plano.

Fica de fora até a Trilha A entregar a dependência; até lá esses casos aparecem só como checks no report:

| Fora | Volta quando |
|---|---|
| Tela de agrupamento por colinearidade | A3 (`collinearity` no report) |
| Escolha DV360 / CM360 | A2 (`dv360_cm360_overlap`); 5º da ordem de corte |
| Upload do resultado de experimento | A7; 3º da ordem de corte |
| Implementação GCS do storage | B11, com bucket para testar |
| Gate do botão Rodar no servidor | B4 (criação do run) |

## Desvios do `trilha-b-plataforma.md`

- **Mapeamento antes da validação.** O `validate` recebe o `column_mapping` dentro do config, então a ordem é: upload → mapeamento confirmado → validate. O trilha-b listava o mapeamento depois.
- **Limite de 30 MB, não 200 MB.** O Cloud Run corta requisições HTTP/1 em 32 MiB, e o dado é agregado por dia e canal (2 anos × 15 canais ≈ 11 mil linhas, < 1 MB).
- **Só storage local no B2.** O GCS entra no B11.
- **`validate` falso até o A2.** `api/validation.py` implementa só `duplicate_date_channel`; quando o `engine/` existir, vira `from engine import validate`.

Os quatro entram em `docs/decisoes/upload-e-storage.md` e o trilha-b é corrigido no mesmo commit.

O contrato §2 não fixa o formato de `inputs`. Este spec propõe `{"investment_file": Path, "performance_file": Path, "generic_trends_file": Path | None}` (as mesmas chaves do `column_mapping`); avisar o dev A para o spec do A2 usar o mesmo formato ou dizer qual quer, e registrar no `docs/m2/README.md` › contrato §2.

---

## B2a · Backend

### Tabelas (migration `0003`)

`simulations`

| Coluna | Tipo | Nota |
|---|---|---|
| `id` | bigint identity PK | |
| `workspace_id` | bigint FK `workspaces.id` on delete cascade, index | escopo |
| `name` | text | 1–120 caracteres, validado no schema |
| `config` | jsonb, default `{}` | rascunho do `EngineConfig`; o B2 escreve só `column_mapping`, o B3 o resto |
| `validation` | jsonb, null | último `ValidationReport`; snapshot de propósito para não revalidar a cada reload |
| `created_by` | bigint FK `users.id` | |
| `created_at`, `updated_at` | timestamptz, default `now()` | `updated_at` atualizado pelo serviço |

`simulation_files`

| Coluna | Tipo | Nota |
|---|---|---|
| `simulation_id` | bigint FK `simulations.id` on delete cascade | PK com `kind` |
| `kind` | enum `simulation_file_kind` (`investment`, `performance`, `trends`) | PK com `simulation_id` |
| `sha256` | text | hex; compõe a chave no storage |
| `filename` | text | nome original, só para exibir (basename, ≤ 200 caracteres) |
| `size_bytes` | bigint | |
| `columns` | jsonb | cabeçalho lido no upload (`list[str]`) |
| `uploaded_by` | bigint FK `users.id` | |
| `uploaded_at` | timestamptz, default `now()` | |

Subir de novo o mesmo `kind` substitui a linha e zera `simulations.validation`. O blob antigo fica no storage (é endereçado por conteúdo; a limpeza é da retenção do B9).

`config.column_mapping`, no formato do `CODE-STYLE.md` › regras do motor:

```json
{"investment_file": {"date_col": "data", "channel_col": "canal", "investment_col": "investimento"},
 "performance_file": {"date_col": "data", "kpi_col": "conversoes"},
 "generic_trends_file": {"date_col": "data", "trends_col": "trends"}}
```

`generic_trends_file` só existe se houver arquivo de trends.

### Storage — `api/storage.py`

Funções de módulo sobre `STORAGE_DIR` (env, default `./data`; `data/` entra no `.gitignore`):

- `put(key, fileobj) -> None`, `open(key)`, `delete(key)`, `list(prefix) -> list[str]`, `path(key) -> Path`.
- Chave: `ws/{workspace_id}/sim/{simulation_id}/inputs/{sha256}.csv`.
- `put` escreve num temporário no mesmo diretório e faz `os.replace` para a chave: nunca deixa arquivo pela metade.
- Sem classe nem interface. O GCS entra no B11 escolhido por env no topo do módulo; `path(key)` vira download para temp.

### Upload

Fluxo do `PUT …/files/{kind}` (serviço em `api/simulations.py`):

1. Copia o `UploadFile` em blocos para um temporário, somando bytes e o sha256; passou de 30 MB (`30 * 1024 * 1024`) → aborta com 413 `"Arquivo maior que 30 MB."`.
2. Extensão diferente de `.csv` → 422 `"Envie um arquivo .csv."`.
3. Lê o cabeçalho: decodifica as primeiras linhas como `utf-8-sig` e cai para `latin-1`; `csv.Sniffer` com delimitadores `,;\t|`. Falhou ou menos de 2 colunas → 422 `"Não foi possível ler o cabeçalho do CSV."`.
4. `storage.put` na chave do workspace da simulação, upsert em `simulation_files`, `validation = null`.
5. `log.info` com `simulation_id`, `kind`, `sha256` e `size_bytes` (nunca conteúdo).

O conteúdo nunca é executado nem interpretado além de `csv`; o nome original nunca vira caminho.

### Sugestão de mapeamento

Função pura `suggest_mapping(kind, columns) -> dict[str, str | None]`, chamada ao montar a resposta (derivada, não guardada). Normaliza (sem acento, minúsculo, sem espaço/`_`) e casa por apelidos, primeira coluna que bater:

| Campo | Apelidos |
|---|---|
| `date_col` | `data`, `date`, `dia`, `day` |
| `channel_col` | `canal`, `channel`, `midia`, `media` |
| `investment_col` | `investimento`, `invest`, `spend`, `custo`, `cost`, `valor` |
| `kpi_col` | primeira coluna que não é a de data |
| `trends_col` | primeira coluna que não é a de data |

Os cabeçalhos dos templates (abaixo) têm de ser sugeridos corretamente.

### Validação — `api/validation.py`

```python
def validate(inputs: dict[str, Path | None], config: dict) -> dict: ...
# inputs = {"investment_file": Path, "performance_file": Path, "generic_trends_file": Path | None}
```

Mesma assinatura que o A2 vai expor. O fake (`# ponytail: fake até o A2; troca por "from engine import validate"`):

- lê o investimento em stream com o `csv` (mesma detecção de encoding/delimitador do upload) usando `date_col` e `channel_col` do mapping;
- conta repetições de `(data, canal)`; havendo, emite `{"id": "duplicate_date_channel", "level": "error", "message": "N linhas repetidas de (data, canal) no investimento", "details": {"rows": [...]}}` com até 20 pares `{"date", "channel", "count"}`;
- devolve `{"ok": <sem error>, "cadence": null, "period_days": null, "date_range": null, "channels": [<canais ordenados>], "checks": [...], "collinearity": null}`.

### Rotas — `api/routes/simulations.py`

Todas `require_role("analyst")`; viewer → 403; simulação de outro workspace ou inexistente → 404.

| Método | Path | Corpo → resposta |
|---|---|---|
| GET | `/api/w/{slug}/simulations` | `[{id, name, created_by_name, created_at, updated_at}]`, `updated_at` desc |
| POST | `/api/w/{slug}/simulations` | `{name}` → 201 `SimulationOut` |
| GET | `/api/w/{slug}/simulations/{id}` | `SimulationOut` |
| PUT | `/api/w/{slug}/simulations/{id}/files/{kind}` | multipart `file` → `SimulationOut`; 413 > 30 MB; 422 não-CSV ou cabeçalho ilegível |
| PUT | `/api/w/{slug}/simulations/{id}/mapping` | `column_mapping` → `SimulationOut` com `validation` preenchido |

```
SimulationOut = {id, name, config, validation: ValidationReport | null,
                 files: {investment|performance|trends: FileOut | null}}
FileOut       = {filename, size_bytes, sha256, columns: list[str],
                 suggested: dict[str, str | None], uploaded_at}
```

`PUT …/mapping`:

1. Investimento e performance enviados; senão 422 `"Envie investimento e performance antes de validar."`.
2. Cada coluna escolhida existe em `columns` do arquivo; senão 422 apontando o campo (`"Coluna 'x' não existe no arquivo de investimento."`). `generic_trends_file` só é aceito se houver trends.
3. Grava `config["column_mapping"]`, chama `validate`, grava `validation`, atualiza `updated_at`.

Dependência nova: `python-multipart` (`uv add`), exigida pelo `UploadFile` do FastAPI.

### Testes B2a (`tests/api/test_simulations.py` + matriz RBAC)

| Verificação | Cobre |
|---|---|
| As 5 rotas em `ROUTES` de `test_rbac.py`; o builder passa a aceitar `files=` | viewer não sobe arquivo (aceite) |
| Upload grava em `ws/{id do workspace da simulação}/sim/{id}/inputs/{sha256}.csv` e o sha256 bate | arquivo no bucket do workspace certo (aceite) |
| Simulação do workspace A pedida pelo slug de B → 404 | escopo |
| Investimento com `(data, canal)` repetido → `ok: false` com check `duplicate_date_channel` e mensagem pt-BR | duplicata bloqueia (aceite) |
| 31 MB → 413; `.txt` → 422; CSV de uma coluna → 422; coluna inexistente no mapping → 422; mapping sem performance → 422 | regras |
| CSV `;` em latin-1 tem o cabeçalho lido | detecção |
| Re-upload substitui a linha e zera `validation` | re-upload |
| `suggest_mapping` acerta os cabeçalhos dos 3 templates | sugestão |

`STORAGE_DIR` aponta para `tmp_path` nos testes (fixture).

---

## B2b · Telas

### Rotas

```
/w/$slug/                       lista de simulações + "Nova simulação" (analyst+); viewer vê "Nenhuma simulação ainda."
/w/$slug/simulacoes/nova        nome → POST → redireciona para o detalhe
/w/$slug/simulacoes/$id         arquivos, mapeamento, validação
```

Viewer em `nova` ou no detalhe: `<p>Sem permissão para editar simulações deste workspace.</p>`, como `membros.tsx:34`. O link e o botão só aparecem para analyst+; quem barra é a API.

### Detalhe da simulação

Uma página, três blocos em sequência:

1. **Arquivos.** Três cartões: Investimento, Performance, Trends (selo "opcional"). Cada um: `<input type="file" accept=".csv">`, nome/tamanho/data do arquivo atual, link "Baixar template". Erro 413/422 aparece no cartão.
2. **Mapeamento de colunas.** Aparece com investimento e performance enviados. Um `NativeSelect` por campo, pré-preenchido com o salvo em `config.column_mapping` ou o `suggested`. Botão "Validar" → `PUT …/mapping`; 422 aparece no formulário.
3. **Validação.** Do report: erros (destaque de erro), avisos (cada um com checkbox "Estou ciente"), informações, e a lista de canais. Rodapé com o botão **Rodar**, desabilitado quando: não validado, há `error`, ou há aviso sem confirmação. Um texto ao lado diz o motivo. No B2 o botão nunca habilita: com tudo ok, o texto é "Execução disponível em breve" (o run é do B4, que também confere o gate no servidor). As confirmações de aviso ficam só no estado da página até o B4.

Depois de cada mutation, `invalidateQueries` da simulação (e da lista após criar).

### Arquivos

- `web/src/lib/api.ts`: `body` `FormData` vai sem `Content-Type` e sem `JSON.stringify`.
- `web/src/lib/simulations.ts`: tipos (`SimulationOut`, `ValidationReport`…) e query options.
- `web/src/routes/_auth/w/$slug/index.tsx`: lista.
- `web/src/routes/_auth/w/$slug/simulacoes/nova.tsx`, `…/simulacoes/$id.tsx`.
- `web/public/templates/investimento.csv` (`data,canal,investimento`), `performance.csv` (`data,conversoes`), `trends.csv` (`data,trends`), cada um com 3 linhas de exemplo. Trocados pelos oficiais quando o Data Analytics entregar.

### Testes B2b (`web/e2e/simulations.spec.ts`)

| Verificação | Cobre |
|---|---|
| Analyst cria simulação, sobe os templates, aceita a sugestão, valida: report ok, Rodar desabilitado com "Execução disponível em breve" | fluxo feliz |
| Investimento com `(data, canal)` repetido: mensagem pt-BR do erro na tela e Rodar desabilitado | aceite |
| Viewer não vê "Nova simulação"; abrir `/simulacoes/nova` mostra "Sem permissão" | aceite |

Screenshots do detalhe nos dois temas antes de fechar (`CLAUDE.md` › verificar mudanças no frontend).

---

## Docs no mesmo commit

- `API-GUIDE.md`: as 5 rotas na tabela e o 413 em status de erro.
- `DATABASE.md`: `simulations` e `simulation_files` na tabela, com o snapshot de `validation` registrado.
- `docs/decisoes/upload-e-storage.md` (novo) + índice em `docs/decisoes/README.md`: os quatro desvios acima.
- `docs/m2/trilha-b-plataforma.md`: ordem do fluxo, 30 MB, e `Status` do B2 ao concluir.
- `CLAUDE.md`: "Estado atual", tabela de decisões e `storage.py`/`simulations.py`/`validation.py` no mapa de `api/`.
- `.env.example`: `STORAGE_DIR`.
