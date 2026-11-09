# Respostas reais do Gemini

`gemini_answers.json`: as narrativas que o Gemini devolveu para os fixtures de `tests/fixtures/results/` (chave: nome do
fixture, depois o id do evento ou `global`), todas aprovadas pelo grounding. `tests/engine/test_grounding_real_answers.py`
confere que o checador não bloqueia prosa real e que mutações dela (número inventado, canal escondido, data errada)
reprovam.

Para atualizar depois de mudar o prompt ou o payload: rode `narratives.build(document, config, get_llm("gemini"))` com
`GEMINI_API_KEY` sobre cada fixture (configs em `tests/fixtures/results/add_reports.py`), troque os blocos pelos campos
`title`/`verdict`/`analysis`/`next_steps` (evento) e `title`/`summary`/`scenarios`/`recommendations` (global), sem `source` nem
`grounding`, grave em `gemini_payloads.json` o `payload`, o `published` e o `universe` de cada job (o teste confere a
resposta contra o payload de onde ela saiu, não contra o motor atual) e confira que o teste continua passando. Nunca
grave a chave em arquivo.
