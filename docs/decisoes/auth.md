# Auth, sessão e workspaces

Decisões do B1a, 21/out/2026. Spec: `docs/superpowers/specs/2026-10-21-b1a-auth-backend-design.md`.

## Token opaco no banco, não cookie assinado nem JWT

**Sintoma:** o protótipo guardava `user_id` no cookie sem assinatura; trocar o número logava como outro usuário. **Decisão:** o cookie `gem_session` leva só um token aleatório de 32 bytes; o banco guarda o sha256 dele. Revogar é apagar a linha: logout, troca de senha, reset e desativação têm efeito imediato, o que um JWT não dá sem lista de revogação. Custo: uma leitura por request, irrelevante no volume do M2.

## Sessão deslizante de 8h com teto de 7d

O analista passa o dia na ferramenta; uma sessão fixa curta o desloga no meio de um run, uma fixa longa deixa um cookie roubado valer uma semana inteira sem uso. Expira após 8h ociosa, renova a cada uso (no máximo um `UPDATE` por minuto) e morre em 7d de qualquer jeito.

## `SameSite=Lax` + checagem de `Origin`

A API serve o SPA na mesma origem, então `Lax` basta para o navegador não mandar o cookie em POST de outro site. A checagem de `Origin` nas mutações é a segunda camada, e existe porque a integração com o Almap Metrics (B10) não está definida: se virar iframe cross-site, o cookie precisa de `SameSite=None` e o `Origin` passa a ser a proteção de CSRF. Compara só o host, não o esquema: o Cloud Run termina o TLS e a app vê `http` enquanto o navegador manda `https://`. Request sem `Origin` passa (CLI, curl, testes); navegador sempre manda em POST.

## 404 entre workspaces, 403 para papel insuficiente

Recurso de outro workspace responde igual a recurso inexistente; um 403 confirmaria que o slug existe. Dentro do próprio workspace o usuário já sabe que ele existe, então papel insuficiente é 403 honesto e o front pode explicar.

## Platform admin é admin em todo workspace

BRD › Journey 3: o Data Tech cria workspaces e usuários, monitora uso e logs de job e cuida da retenção. Isso exige enxergar dentro dos workspaces, então ele passa no `require_role` como `admin` sem precisar de membership.

## Conta é do platform admin, membership é do workspace

Um analista da Almap atende várias marcas. Se o admin da marca X pudesse resetar a senha ou desativar a conta, mexeria no acesso dele à marca Y. Então reset e desativação são do platform admin, e o admin do workspace vincula contas existentes, troca papel e remove. Senha temporária aparece uma vez na resposta e o admin a passa por fora; sem e-mail no M2.

**Só o platform admin cria conta** (revisão do B1, 22/out/2026). Antes, o admin do workspace criava a conta ao adicionar um e-mail novo e recebia a senha temporária: o admin da marca A podia criar `x@almap.com`, entrar com ela e definir a senha; quando a marca B adicionasse o mesmo e-mail, a conta já existia e ganhava a membership sem senha nova, e o admin de A passava a ler B. Agora `POST /api/w/{slug}/members` com e-mail desconhecido responde 404 `account_not_found` para o admin do workspace e só cria a conta (exigindo `name`) quando quem chama é o platform admin. Sem rota nova: o platform admin cria a conta já vinculando a um workspace, que é como toda conta nasce. Custo aceito: o admin do workspace descobre se um e-mail tem conta, e o nome dela, ao vinculá-la.

## Workspace nunca fica sem admin

Rebaixar ou remover o último admin do workspace responde 409 `last_admin`. As memberships admin do workspace são travadas (`FOR UPDATE`) antes da contagem, para dois admins rebaixando um ao outro ao mesmo tempo não zerarem a lista. Na tela de membros o próprio admin não vê papel editável nem "Remover" na sua linha: se rebaixar a si mesmo, o `/me` em cache e a tela ficariam desatualizados e toda ação seguinte falharia; outro admin faz isso.

## Bloqueio por conta, não por IP

5 falhas seguidas bloqueiam a conta por 15 min; acerto zera o contador. A leitura e a escrita do contador rodam sob `SELECT … FOR NO KEY UPDATE` na linha do usuário: sem isso, palpites em paralelo leem o mesmo valor e furam o bloqueio. `NO KEY` porque basta serializar o contador, e o `FOR UPDATE` cheio travaria inserts que apontam para o usuário (sessão, membership). Senha atual errada na troca de senha conta para o mesmo bloqueio, senão `POST /api/auth/password` viraria um oráculo de força bruta com sessão roubada. Conta bloqueada responde 429 e com isso revela que existe, o que é aceitável porque as contas são criadas por admin. E-mail inexistente roda um scrypt mesmo assim, para o tempo de resposta não separar os casos. Rate limit por IP fica para o B11.

## scrypt da stdlib

`hashlib.scrypt` com N=2¹⁷, r=8, p=1 (mínimo da OWASP), sem dependência nova. Cada login usa ~128 MB de RAM por ~0,3 s (1,5 s num notebook lento). Os parâmetros ficam no hash, então subir o custo depois não invalida senhas antigas.

Como o login é público, uma rajada de requests derrubaria a instância. Por isso há dois limites (revisão do B1, 22/out/2026):

- **Semáforo de 4 scrypts simultâneos** (`passwords.SLOTS`): o resto espera na fila, então o teto de RAM é ~512 MB. Ao dimensionar o Cloud Run no B11, deixe memória para isso ou reduza `SLOTS`.
- **Espera na fila limitada a 5 s** (`SLOT_WAIT_S`), depois 503 `busy` com `Retry-After`. As rotas são `def` síncronas e dividem as 40 threads do AnyIO: sem teto, uma rajada de logins com e-mail aleatório deixava todas as threads paradas no semáforo e travava a API inteira, `/api/health` incluído (review de 26/out/2026). 5 s e não 1 s porque o E2E faz logins em paralelo num notebook lento, onde um scrypt leva ~1,5 s. É um teto, não um rate limit: o rate limit por IP continua no B11.
- **Login sem conexão presa durante o scrypt**: lê o usuário, encerra a transação, roda o scrypt e só então trava a linha para contar a falha ou zerar o contador. Se a senha mudou nesse meio-tempo, o palpite conta como errado. Sem isso, uns 15 logins ruins simultâneos esgotariam o pool (5+10) e travariam todas as rotas.

Senha acima de 1024 caracteres é 422 antes de chegar ao scrypt.

## Troca de senha gira o token

A troca de senha derruba todas as sessões do usuário, inclusive a que fez a troca, e responde com um cookie novo. Antes ela mantinha o token atual: quem trocava a senha por suspeitar de cookie roubado, no mesmo navegador, mantinha vivo justamente o token roubado por até 7 dias (review de 26/out/2026, OWASP pede renovar o ID de sessão na troca de senha).

## Sessões vencidas somem no login

Sessão expirada é apagada quando o cookie volta, mas cookie que nunca volta (sobrescrito por outro login, apagado) deixaria a linha para sempre. Todo login apaga as sessões já vencidas por ociosidade ou pelo teto de 7d. É um `DELETE` pequeno e dispensa job agendado.

## Bootstrap por CLI

Sem auto-cadastro, alguém cria o primeiro platform admin: `mise run create-admin <email> <nome>` (em produção, Cloud Run Job one-off com o mesmo comando). Seed por env deixaria uma senha morando num secret para sempre.

## `detail` em código estável nos erros de auth

O front precisa decidir o fluxo (mandar para a troca de senha, mostrar o tempo de bloqueio), então esses `detail` são códigos e a tradução para pt-BR fica na apresentação. Erros sem fluxo especial, como o 409, já vêm em pt-BR.

## Guardas do front no `beforeLoad`, lendo `/api/me`

Decisões do B1b, 22/out/2026. Spec: `docs/superpowers/specs/2026-10-22-b1b-auth-telas-design.md`.

O `/api/me` fica no cache do TanStack Query e as rotas `_auth`, `w/$slug` e `admin` decidem no `beforeLoad`, antes de renderizar: sem flash de tela protegida. Slug de workspace fora de `me.workspaces` cai na mesma tela de "não encontrado" de uma rota inexistente, como o 404 da API. Esconder link é só UX; quem barra é a API. Sessão que expira no meio do uso volta como 401 `not_authenticated` em qualquer query ou mutation e um handler global em `main.tsx` manda para o login com `redirect`; o 401 `invalid_credentials` do próprio login não dispara isso. O `redirect` atravessa a troca de senha obrigatória e é aceito só como path do próprio site: começa com `/`, não com `//` nem `/\`, e não tem caractere de controle.

Erro de carga (query com 5xx ou falha de rede) vira um toast genérico global, sem repetir a mesma mensagem. Mutation mostra o próprio erro, inline ou em toast, e o handler global não duplica.

## Workspace ativo na URL

`/w/$slug/...` espelha `/api/w/{slug}`: link compartilhável e abas em marcas diferentes sem brigar por estado. O seletor do header só navega.

## Tema do protótipo, trocável no B10

Tailwind v4 + shadcn/ui com as cores do Streamlit (primária `#ff4b4b`, Inter), claro e escuro, padrão do sistema com escolha salva no `localStorage`. As cores moram só nos tokens de `web/src/index.css`; trocar pelo design system do Almap Metrics no B10 é trocar esses tokens.
