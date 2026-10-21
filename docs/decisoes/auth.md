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

Um analista da Almap atende várias marcas. Se o admin da marca X pudesse resetar a senha ou desativar a conta, mexeria no acesso dele à marca Y. Então o admin do workspace adiciona (criando a conta se não existir), troca papel e remove; reset e desativação são do platform admin. Senha temporária aparece uma vez na resposta e o admin a passa por fora; sem e-mail no M2.

## Bloqueio por conta, não por IP

5 falhas seguidas bloqueiam a conta por 15 min; acerto zera o contador. A leitura e a escrita do contador rodam sob `SELECT … FOR NO KEY UPDATE` na linha do usuário: sem isso, palpites em paralelo leem o mesmo valor e furam o bloqueio. `NO KEY` porque basta serializar o contador, e o `FOR UPDATE` cheio travaria inserts que apontam para o usuário (sessão, membership). Senha atual errada na troca de senha conta para o mesmo bloqueio, senão `POST /api/auth/password` viraria um oráculo de força bruta com sessão roubada. Conta bloqueada responde 429 e com isso revela que existe, o que é aceitável porque as contas são criadas por admin. E-mail inexistente roda um scrypt mesmo assim, para o tempo de resposta não separar os casos. Rate limit por IP fica para o B11.

## scrypt da stdlib

`hashlib.scrypt` com N=2¹⁷, r=8, p=1 (mínimo da OWASP), sem dependência nova. Cada login usa ~128 MB de RAM por ~0,3 s; considere isso ao dimensionar a instância do Cloud Run. Os parâmetros ficam no hash, então subir o custo depois não invalida senhas antigas.

## Bootstrap por CLI

Sem auto-cadastro, alguém cria o primeiro platform admin: `mise run create-admin <email> <nome>` (em produção, Cloud Run Job one-off com o mesmo comando). Seed por env deixaria uma senha morando num secret para sempre.

## `detail` em código estável nos erros de auth

O front precisa decidir o fluxo (mandar para a troca de senha, mostrar o tempo de bloqueio), então esses `detail` são códigos e a tradução para pt-BR fica na apresentação. Erros sem fluxo especial, como o 409, já vêm em pt-BR.
