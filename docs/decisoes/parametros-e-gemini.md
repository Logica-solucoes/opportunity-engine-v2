# Parâmetros e sugestão do Gemini

Decisões do B3, 26/out/2026. Spec: `docs/superpowers/specs/2026-10-26-b3-parametros-gemini-design.md`.

## `EngineConfig` provisório em `api/`

O A0 ainda não entregou o `engine/`, e o B3 e o B4 dependem do config. `api/engine_config.py` define `ParamsIn` (os campos do formulário) e `EngineConfig` (`ParamsIn` + `column_mapping`, `channel_groups`, `controls`, `gate_thresholds`) com os campos do contrato §1. Os nomes `require_significance`/`require_good_fit` e os defaults causais foram escolhidos aqui e são provisórios: o A0 decide. Quando o `engine/config.py` existir, o arquivo vira import de lá. Mesmo caminho do `validate` falso do B2.

## Rotas sob o workspace e schema fora dele

O trilha-b citava `POST /api/simulations/{id}/suggest`. Dado de cliente fica sob `/api/w/{slug}/…` (regra do `API-GUIDE.md`), então sugestões e params ficam lá. O schema é o mesmo para todos e não é dado de cliente: `/api/engine/config-schema`, com cache infinito no front.

## Sugestão dos dados escrita do zero

O time não tem acesso ao `suggest_causal_config` do protótipo. O B3 sugere só o que sai dos arquivos com regra simples: `min_pre_period_days` (um quarto do histórico, entre 28 e 90 dias se diário, entre 56 e 182 se semanal) e `optimization_target`/`kpi_is_monetary` pelo nome da coluna de KPI. Cadência estranha, data fora do ISO ou nome de KPI desconhecido não sugerem nada: o campo fica no default, sem selo. As sugestões exigem `validation` presente, porque todo upload zera o report e o mapeamento salvo pode apontar para coluna que o arquivo novo não tem.

## O Gemini só vê agregados

O BRD é confidencial e os arquivos são dados de mídia das marcas. O prompt leva nomes de colunas, cadência, período, investimento total, participação por canal e mínimo/média/máximo do KPI; nenhuma linha. O teste `test_gemini_prompt_carries_a_summary_and_no_rows` garante isso. Prompt e resposta nunca vão para o log.

## Resposta do Gemini validada item a item

A saída estruturada pede `{field, value, reason}` com `value` em string, e cada item passa pelo `ParamsIn`: valor fora do limite ou campo que não é do formulário cai sozinho, sem derrubar os outros. Sem chave (`GEMINI_API_KEY`), com erro do SDK, timeout de 20 s ou resposta ilegível, a rota responde 200 com `available: false`: a tela segue com as sugestões dos dados (aceite do BRD). O modelo é o alias `gemini-flash-latest`; fixar uma versão se as sugestões mudarem de comportamento. A chave sai da variável de ambiente até o B11 trazer o Secret Manager.

## Parâmetros não zeram a validação

O `validate` falso só lê o `column_mapping`, que o formulário não toca. Quando o `validate` real (A2) passar a depender de outro campo, o `PUT …/params` passa a zerar o report.

## Tela (B3b)

- **Formulário gerado do schema, com layout no front.** `FORM_LAYOUT` (`web/src/lib/params.ts`) diz quais campos aparecem, em que grupo e com qual rótulo; tipo, limites e defaults vêm do `GET /api/engine/config-schema`. Campo novo do A0 não aparece sem rótulo, e campo do layout que sumiu do schema é ignorado.
- **Valor inicial:** o salvo, depois a sugestão dos dados, depois o default. Só o que veio de sugestão ganha selo e explicação; editar ou salvar tira os dois.
- **Gemini só nos campos não editados**, inclusive os salvos; nada é gravado até "Salvar parâmetros".
- **Números como texto no estado.** Input controlado com `Number()` a cada tecla engolia o "1." ou o "0.0" do meio da digitação; a conversão acontece só no corpo do `PUT`.
- **`noValidate` no form.** A API valida, e o 422 do pydantic cai em cada campo pelo `loc`, com mensagem pt-BR pelo `type` e pelos limites do `ctx`. Erro que não casa com nenhum campo da tela aparece como mensagem geral.
- **O formulário remonta a cada report novo.** Novo mapeamento ou arquivo muda as sugestões dos dados; edições não salvas se perdem nesse caso, como no mapeamento.

## Ajustes da revisão

- **`inf`/`nan` recusados.** `ParamsIn` tem `allow_inf_nan=False`: `Infinity` passava pelo `gt=0` e quebrava o JSONB com 500. O 422 da API inteira deixou de ecoar o `input` (um `inf` ecoado também virava 500); `type`, `loc`, `msg` e `ctx` seguem iguais.
- **Conexão devolvida antes do Gemini.** A rota lê os arquivos e faz `rollback` antes da chamada de até 20 s, para não segurar conexão do pool.
- **`save_params` preserva as outras chaves do `config`** (`channel_groups`, `controls` quando o A3/A4 chegarem).
