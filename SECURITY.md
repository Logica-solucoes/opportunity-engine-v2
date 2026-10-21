# Segurança

## Reportar uma vulnerabilidade

Abra um relato privado pelo GitHub: aba **Security → Report a vulnerability** deste repositório. Não abra issue pública. Só a versão em produção (a `main`) recebe correção.

O resto deste arquivo são as regras que o código segue. O porquê de cada uma está no arquivo da área em `docs/decisoes/`. As regras de auth abaixo são o alvo do B1 (`docs/m2/trilha-b-plataforma.md`); marque aqui o que já está implementado ao entregar.

## Escopo por workspace

- **Toda** query de dado de cliente filtra por `workspace_id`. Sem exceção, inclusive em join e subquery.
- O workspace chega por uma dependência do FastAPI que valida a **membership** do usuário da sessão — nunca por body ou query param confiado cegamente.
- Recurso de outro workspace responde **404, nunca 403**: 403 vira oráculo de existência.
- Papéis: **viewer** (vê runs publicados, mexe em cenários, exporta) < **analyst** (upload, roda, publica/despublica) < **admin** (membros e thresholds) · **platform admin** (cria workspaces, vê o uso de todos). Todo endpoint tem teste papel × rota.

## Auth

- Sem auto-cadastro: o Admin cria usuários com senha temporária e troca obrigatória no 1º login. Reset de senha só pelo Admin no M2.
- Senha com `hashlib.scrypt` (stdlib). Bloqueio após 5 falhas seguidas por 15 min.
- Sessão em cookie `HttpOnly; Secure; SameSite=Lax` guardando um token aleatório; o banco guarda só o **hash**. Nunca guardar `user_id` ou `username` no cookie, nem token de sessão na URL (o protótipo fazia as duas coisas).
- Cookie adulterado → 401.
- Senha, token e chave nunca aparecem em log.

## Segredos e superfícies expostas

- Segredo só via env, nunca no código nem no repositório: `DATABASE_URL`, a chave do Gemini (Secret Manager em produção), o que o B1 e o B8 acrescentarem. O `.env.example` traz o que cada um é e como gerar.
- Chave do Gemini é **única da plataforma** (Secret Manager), nunca por usuário nem em texto puro no banco.
- O BRD e dados de cliente (CSV de investimento, resultados) **não vão para o repositório** (`.gitignore`: `*.docx`, `inputs/`, `outputs/`).
- `/docs`, `/redoc` e `/openapi.json`: fechar em produção (decisão a registrar no B11).
- Mesma origem (API serve o SPA): sem CORS aberto.
- Upload (B2): validar tipo e tamanho antes de processar; CSV exportado deve escapar texto que começa com `=`, `+`, `-`, `@`, tab ou CR (o Excel executaria a fórmula).

## Mexer em auth

Quando o B1 entregar, liste aqui os arquivos que o formam (sessão, dependência de membership, rotas de login, interceptors do front), como o Tally faz.
