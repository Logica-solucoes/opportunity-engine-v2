# Conectores Google (B8)

## Fallback do BRD primeiro, OAuth nunca por ora

O BRD autoriza puxar Ads e GA4 pelo BigQuery (Data Transfer Service do Google Ads + export nativo do GA4) em vez de OAuth próprio. O OAuth depende de developer token que não saiu e é o último da ordem de corte (`docs/m2/README.md`). A carga diária fica com o DTS; a plataforma só lê.

## Sem acesso real: schema documentado + sandbox

Em 29/out/2026 não havia projeto GCP nem dataset de nenhuma conta Core. As queries foram escritas contra a doc do DTS (Google Ads API v25) e do export do GA4. O teste `tests/api/test_bigquery_live.py` as roda de verdade num BigQuery sandbox (GA4 contra `bigquery-public-data.ga4_obfuscated_sample_ecommerce`, Ads contra tabelas semeadas com as colunas das views do DTS), mas em 29/out/2026 ele ficou pulado por falta de sandbox: até alguém rodá-lo com `BIGQUERY_TEST_PROJECT`, a SQL só é coberta pelos testes com fake. O aceite de ±1% contra o Google Ads UI fica pendente até haver uma conta real. A doc não diz o tipo de `segments_date`, por isso o `CAST(… AS DATE)`.

## Um import, o mesmo caminho do upload

O import gera os mesmos dois CSV canônicos (`data,canal,investimento` e `data,kpi`) e chama `save_file` e `save_mapping`. O `validate`, o snapshot do run e o download das entradas não sabem de onde veio o dado. O nome do arquivo (`google-ads_<início>_<fim>.csv`) diz a origem, e não há coluna nova. O import é síncrono: duas queries de até 60 s, com a conexão do banco devolvida ao pool durante a espera. Vira job se os dados reais passarem disso.

## Grade com zeros

O BigQuery não distingue "dia sem linha" de "dia com zero", e o motor precisa da série contínua: todo dia do período × todo canal que apareceu sai no CSV, com 0 onde não houve gasto. O KPI também. Período sem gasto ou sem evento algum é 422, porque quase sempre é config errada (evento com outro nome, conta errada).

## Canais

`SEARCH→SEARCH`, `PERFORMANCE_MAX→PMAX`, `VIDEO→YOUTUBE`, `DEMAND_GEN→DEMAND_GEN`, fixo no código. Os outros tipos (`DISPLAY`, `SHOPPING`…) viram canal com o próprio nome: descartar faria o total não bater com o Google Ads UI, e juntar em "OUTROS" misturaria mídias diferentes. O tipo é o do snapshot mais recente da campanha (`_DATA_DATE = _LATEST_DATE`, como na query de exemplo da doc). Isso também evita contar a campanha uma vez por snapshot. O join com `ads_Campaign_<cid>` é `LEFT JOIN`: campanha que sumiu do snapshot mais recente mantém o gasto, no canal `UNKNOWN`, em vez de sumir do total.

## Uma service account, config só do platform admin

A plataforma lê com uma service account só (*BigQuery Data Viewer* em cada dataset de cliente, *Job User* no projeto da plataforma, que paga as queries), e o config guarda `projeto.dataset` completo. Assim tanto faz se o DTS de cada cliente mora no projeto Omnicom ou no do cliente. O preço é que apontar um dataset equivale a ler os dados de quem estiver lá. Por isso só o platform admin configura (`SECURITY.md`). Se um dia o admin do workspace precisar configurar sozinho, isso exige uma service account por cliente. Quem configura o export do GA4 de cada Core é pergunta em aberto com o Data Tech.

## Teto de custo

Cada query leva `maximum_bytes_billed` de 20 GB (`api/bigquery.py`). Um GA4 grande com 3 anos pode passar disso; o erro vira 502 "Não foi possível consultar o BigQuery." e o teto sobe com dado real na mão.
