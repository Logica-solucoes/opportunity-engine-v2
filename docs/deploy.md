# Deploy no servidor próprio

Uma imagem (`Dockerfile`), três serviços (`deploy/compose.yml`): `postgres`, `migrate` (aplica as migrations e sai) e `api` (API + SPA; o worker é subprocess dela). O proxy reverso com TLS é do servidor; a API escuta só em `127.0.0.1:${API_PORT}`.

## Pré-requisitos
- Docker com compose v2, x86-64.
- DNS do domínio apontado e TLS no proxy do servidor.
- Memória: 2 GB ou mais. Até 4 logins simultâneos usam ~128 MB de scrypt cada (`passwords.SLOTS`), e cada run do motor roda num subprocess.
- Disco para o Postgres, o `STORAGE_DIR` (uploads de até 30 MB) e 7 dias de backup.

## Primeiro deploy
```bash
git clone <repo> /opt/gem && cd /opt/gem
cp deploy/.env.example deploy/.env && chmod 600 deploy/.env   # preencha POSTGRES_PASSWORD (URL-safe: vai cru no DATABASE_URL; use `openssl rand -hex 32`) e GEMINI_API_KEY
TAG=$(git rev-parse --short HEAD)
docker build --build-arg ENGINE_VERSION=$TAG -t gem:$TAG .
sed -i "s/^TAG=.*/TAG=$TAG/" deploy/.env
docker compose -f deploy/compose.yml --env-file deploy/.env up -d
docker compose -f deploy/compose.yml --env-file deploy/.env run --rm --no-deps api python -m api.cli create-admin voce@exemplo.com "Seu Nome"
curl -fsS http://127.0.0.1:8080/api/health
```

## Atualizar
O `up -d` recria a api e mata os runs em andamento (eles viram runs mortos só depois de 20 min). Atualize quando não houver run ativo.

```bash
git pull && TAG=$(git rev-parse --short HEAD)
docker build --build-arg ENGINE_VERSION=$TAG -t gem:$TAG .
sed -i "s/^TAG=.*/TAG=$TAG/" deploy/.env
docker compose -f deploy/compose.yml --env-file deploy/.env up -d   # o migrate roda antes da api
```

## Imagem no Docker Hub (provisório)
Enquanto não há acesso ao servidor, a produção (`http://webapi.seudash.com.br:18085`) roda a imagem publicada no Docker Hub, com a tag fixa `logicasolucoesanaliticas/logicaprivado:opportunity_engine_v2_latest`. Atualizar a produção é buildar e pushar essa tag a partir do commit desejado (precisa de `docker login` com acesso ao repositório privado), e depois o servidor puxa a imagem e recria o container:

```bash
TAG=$(git rev-parse --short HEAD)
IMG=logicasolucoesanaliticas/logicaprivado:opportunity_engine_v2_latest
docker build --build-arg ENGINE_VERSION=$TAG -t $IMG -t gem:$TAG .
docker push $IMG
```

**Migrations não rodam sozinhas aqui.** Sem o serviço `migrate` do compose, uma imagem com migration nova sobre o banco antigo quebra em runtime (`UndefinedColumn`, como `workspaces.deleted_at` da 0007). Depois de puxar a imagem e antes de a api atender, rode no servidor, com o `backup.sh` antes se a migration mexer em dados:

```bash
docker run --rm --env-file <env-da-api> $IMG alembic -c api/alembic.ini upgrade head
```

Ou, num container da api já de pé, `docker exec <container> alembic -c api/alembic.ini upgrade head`. Confira a versão aplicada com `alembic -c api/alembic.ini current`.

A tag é única e sobrescrita a cada push, então não há rollback por tag: para voltar, builde de novo a partir do commit anterior. Esse ambiente roda em HTTP puro, sem TLS, por isso o `.env` dele precisa de `COOKIE_SECURE=false` (sem isso, o navegador descarta o cookie de sessão e todo acesso volta ao login). Quando o servidor próprio tiver proxy com TLS, remova a flag e passe a usar o fluxo acima, com tag por commit.

## Rollback
Volte o `TAG` do `deploy/.env` para a tag anterior (`docker images gem`) e rode `up -d`. Se a versão nova trouxe migration, a imagem antiga pode não ler o schema novo. Nesse caso, restaure o backup de antes do deploy (abaixo). Rode o `backup.sh` antes de todo deploy com migration.

## Proxy do servidor (nginx)
```nginx
server {
    server_name gem.exemplo.com;
    # TLS do servidor aqui
    client_max_body_size 32m;   # a API só barra Content-Length > 32 MiB; corpo chunked passa sem este limite

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;   # o check de Origin compara com o Host
        proxy_set_header X-Forwarded-For $remote_addr;   # IP do rate limit do login; tem de sobrescrever, não acrescentar (o uvicorn confia no primeiro item)
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # log do run ao vivo (SSE): sem isto o nginx segura os eventos até o run acabar
    location ~ ^/api/w/[^/]+/runs/[0-9]+/logs/stream$ {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_buffering off;
        proxy_read_timeout 1h;
    }
}
```

O `X-Forwarded-For` é sobrescrito com `$remote_addr` de propósito: com `$proxy_add_x_forwarded_for` o cliente forjaria o cabeçalho e burlaria o rate limit do login. Se houver outro proxy na frente do nginx, configure `real_ip` (`set_real_ip_from`) para o `$remote_addr` continuar sendo o IP do cliente.

## Backup e restauração
- Cron do dono: `0 3 * * * /opt/gem/deploy/backup.sh >> /var/log/gem-backup.log 2>&1`. Grava `db.dump` e `storage.tgz` em `/var/backups/gem/AAAA-MM-DD/` (ou `BACKUP_DIR`) e guarda 7 dias.
- Cron da purga da lixeira de workspaces (obrigatório, depois do backup das 3h para o backup do dia ainda ter o workspace): `30 3 * * * docker compose -f /opt/gem/deploy/compose.yml --env-file /opt/gem/deploy/.env exec -T api python -m api.cli purge-workspaces >> /var/log/gem-purge.log 2>&1`. Sem ele, workspace excluído fica na lixeira para sempre.
- Apagar um workspace na hora (LGPD): `docker compose -f deploy/compose.yml --env-file deploy/.env exec api python -m api.cli delete-workspace <slug>`. Um workspace purgado ainda existe nos backups por até 7 dias.
- Restaurar: `deploy/restore.sh /var/backups/gem/AAAA-MM-DD`. Ele para a api, sobrescreve banco e arquivos e sobe a api de novo. Teste uma vez depois do primeiro deploy.
- O backup fica no mesmo disco. Copiar para fora do servidor é decisão do time do servidor.

## Logs
`docker compose -f deploy/compose.yml --env-file deploy/.env logs -f api`: uma linha JSON por evento, com `user_id`, `workspace_id` e `run_id`.

## Pendente até o acesso ao servidor
Teste de carga (10 runs simultâneos e 30 usuários), restauração e rollback testados, homologação das 4 jornadas.
