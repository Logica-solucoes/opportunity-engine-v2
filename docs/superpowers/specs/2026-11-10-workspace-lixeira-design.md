# Lixeira de workspace (soft delete com purga em 7 dias) — design

Data: 10/nov/2026. Substitui o hard delete de `DELETE /api/admin/workspaces/{id}` (commit `c9988a3`), que apaga tudo na hora.

## Objetivo

Excluir um workspace por engano não pode custar o cliente inteiro. A exclusão passa a mover o workspace para uma lixeira: some para todo mundo na hora, o platform admin pode restaurar por 7 dias, e depois disso ele é apagado de vez (linhas e arquivos), como o hard delete faz hoje.

## Decisões

| Pergunta | Decisão |
|---|---|
| Como marcar? | Coluna `workspaces.deleted_at` (nula = ativo). Nada é apagado até a purga; memberships, simulações e runs ficam intactos para a restauração trazer tudo de volta. |
| Quem exclui e restaura? | Só o platform admin. Excluir continua pedindo a própria senha (mesma checagem e bloqueio de hoje). Restaurar não pede senha: não destrói nada. |
| O que muda para quem usa o workspace? | Ele deixa de existir: `require_role` responde 404 (como slug inexistente), some do `/api/me` e do seletor do cabeçalho. Membros perdem acesso na hora, sem precisar remover vínculo. |
| Prazo | 7 dias fixos, constante `TRASH_DAYS = 7` em `api/accounts.py`. Sem variável de ambiente enquanto ninguém pedir outro prazo. |
| Quem dispara a purga? | Comando de CLI `python -m api.cli purge-workspaces`, rodado pelo cron do servidor uma vez por dia (mesmo padrão do `backup.sh`). A API não tem agendador. Sem o cron configurado nada é purgado, e o workspace fica na lixeira indefinidamente (ainda restaurável): por isso o cron entra no `docs/deploy.md` como passo obrigatório. |
| Excluir de vez agora | Comando de CLI `python -m api.cli delete-workspace <slug>`: apaga na hora, esteja o workspace ativo ou na lixeira, para pedido de LGPD ou limpeza. Sem tela: o acesso ao shell do servidor já é a autorização, então não pede senha. Pede confirmação digitando o slug de novo (ou `--yes` para script). Run em andamento barra, como na tela. |
| Run em andamento | Continua barrando a exclusão com 409 (run morto há 20 min não conta). Assim nenhum worker escreve num workspace na lixeira. |
| Slug na lixeira | Continua reservado até a purga (a restauração precisa dele). Criar workspace com esse slug → 409 com mensagem própria: "Esse slug é de um workspace na lixeira. Restaure-o ou aguarde a exclusão definitiva." |
| Uso (`/admin/uso`) | Sem mudança: os runs de um workspace na lixeira continuam contando no mês em que rodaram. Depois da purga somem por cascade, como hoje. |
| Backup | O `backup.sh` guarda 7 dias, então um workspace purgado ainda existe nos backups por até 7 dias depois da purga. Fica documentado, sem código. |

## Banco

Migration `0007`:

- `workspaces.deleted_at timestamptz NULL`
- `workspaces.deleted_by bigint NULL REFERENCES users(id) ON DELETE SET NULL`

Sem índice: são poucas dezenas de workspaces. O `UNIQUE(slug)` fica como está (slug reservado na lixeira, ver acima).

Toda consulta de workspace "ativo" filtra `deleted_at IS NULL`: `require_role` (`api/auth.py`), `me_out` (`api/routes/auth.py`) e o `find_workspace` das rotas de admin que mexem em workspace ativo (conector Google, excluir). Uma função `active_workspaces()` em `api/accounts.py` devolve o `select` filtrado, para não espalhar o filtro.

## API

```text
DELETE /api/admin/workspaces/{workspace_id}          {password}  → 204   (move para a lixeira)
POST   /api/admin/workspaces/{workspace_id}/restore             → 200 WorkspaceOut
GET    /api/admin/workspaces                                     → 200 [WorkspaceOut]  (purga os vencidos antes)
```

- **DELETE:** mesma rota e mesmos erros de hoje (400 `invalid_current_password` contando no bloqueio, 429 `locked`, 409 run em andamento), mas só grava `deleted_at = now()` e `deleted_by`. Workspace já na lixeira ou inexistente → 404.
- **restore:** platform admin. Só workspace na lixeira; ativo ou inexistente → 404. Zera `deleted_at` e `deleted_by`.
- **GET:** lista ativos e na lixeira; `WorkspaceOut` ganha `deleted_at` e `purge_at` (`deleted_at + TRASH_DAYS`, calculado no Python), ambos `null` no ativo. Não purga nada.
- **POST /workspaces** com slug de workspace na lixeira → 409 com a mensagem da tabela.
- **Logs:** `auth.workspace_trashed`, `auth.workspace_restored`, `auth.workspace_purged` com `workspace_id`, `slug` e `by` (a CLI loga `by=cli`).

## CLI (`api/cli.py`)

```text
python -m api.cli purge-workspaces                 # apaga de vez os que estão na lixeira há mais de 7 dias
python -m api.cli delete-workspace <slug> [--yes]  # apaga de vez agora, ativo ou na lixeira
```

Os dois chamam `accounts.purge_workspace(db, workspace)`: a lógica atual de `delete_workspace` (cascade nas linhas, depois `ws/{id}` do storage, `workspace.files_orphaned` no log se o disco falhar). `purge-workspaces` seleciona `deleted_at < now() - TRASH_DAYS`, apaga um por vez (um que falhar não para os outros) e imprime quantos apagou; sai com código 0 mesmo sem nada a apagar. `delete-workspace` com slug inexistente ou run em andamento sai com código 1 e mensagem pt-BR.

Cron sugerido no `docs/deploy.md`, depois do backup das 3h para o backup do dia ainda ter o workspace:

```text
30 3 * * * docker compose -f /opt/gem/deploy/compose.yml --env-file /opt/gem/deploy/.env exec -T api python -m api.cli purge-workspaces >> /var/log/gem-purge.log 2>&1
```

## Tela (`/admin/workspaces`)

- A tabela atual mostra só os ativos. O diálogo da lixeira continua pedindo a senha; o texto passa a ser "Vai para a lixeira e some para todos os membros agora. Dá para restaurar até {purge_at}; depois disso é apagado de vez, com simulações, execuções e arquivos." Toast: "Workspace movido para a lixeira."
- Abaixo, uma seção **Lixeira**, só quando houver itens: nome, slug, excluído em, exclusão definitiva em (`purge_at`, data pt-BR) e botão **Restaurar** (sem senha; toast "Workspace restaurado."). Restaurar invalida a lista e o `meQuery`.

## Testes

Em `tests/api/test_delete_workspace.py` (reescrito):

- excluir move para a lixeira: 204, linha continua com `deleted_at`, simulações e arquivos intactos;
- workspace na lixeira dá 404 em `require_role` (ex.: `GET /api/w/{slug}/simulations`), some do `/api/me` de membro e de platform admin;
- senha errada, bloqueio, run ativo (409), run morto não barra, 403/401, 422 sem senha: como hoje;
- excluir de novo um que já está na lixeira → 404;
- restaurar devolve acesso e dados; restaurar ativo → 404; não-platform → 403;
- slug de workspace na lixeira em `POST /workspaces` → 409 com a mensagem;
- purga (`tests/api/test_cli.py`): com `now` congelado 7 dias + 1 s depois, `purge-workspaces` apaga linhas e `ws/{id}`; com 7 dias − 1 s, não apaga; workspace ativo nunca é purgado; falha de disco ainda apaga as linhas e loga o órfão;
- `delete-workspace`: apaga ativo e da lixeira na hora; slug inexistente e run ativo saem com 1 sem apagar; sem `--yes` e confirmação errada não apaga;
- `test_rbac.py`: rota de restore na matriz.

## Docs no mesmo commit

`API-GUIDE.md` (rotas), `DATABASE.md` (colunas novas), `docs/decisoes/auth.md` (a seção "Excluir workspace pede a senha de quem exclui" passa a descrever a lixeira, a purga pela CLI e o `delete-workspace`), `docs/deploy.md` (cron da purga como passo obrigatório, `delete-workspace` para LGPD, backup guarda workspace purgado por mais 7 dias).

## Fora do escopo

- "Excluir de vez" pela tela. Fica só na CLI.
- Prazo configurável. `TRASH_DAYS = 7` fixo até alguém pedir outro.
- Lixeira para simulação. Continua com hard delete e confirmação pelo nome.

## Decidido em 10/nov/2026

1. Purga por comando de CLI no cron do servidor, não preguiçosa na API.
2. "Excluir de vez agora" também por comando de CLI.
3. Prazo fixo em 7 dias.
