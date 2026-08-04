# Neon least-privilege: Flask ne sme brati agent_/mcp_

Flask (Heroku) in Next.js (Vercel) trenutno delita isti `DATABASE_URL` /
isti Postgres role. Če kdo vdremo v Flask, vidi tudi:

- `agent_nabiralniki.geslo_encrypted` (IMAP App Password-i)
- `mcp_tokens` / `mcp_oauth_clients`
- `agent_pravila`, `agent_audit`

## Cilj

1. Role `amour_flask` — samo tabele, ki jih Flask uporablja (orders, parfumi, …).
2. Role `amour_next` — poln dostop vključno z `agent_*` / `mcp_*`.
3. Lastnik / migracije — ločen `amour_migrator`.

## Koraki (ročno v Neon SQL Editor)

```sql
-- 1) Ustvari vlogi (gesla si izberi sam, shrani v Heroku/Vercel)
CREATE ROLE amour_flask LOGIN PASSWORD '...';
CREATE ROLE amour_next LOGIN PASSWORD '...';

-- 2) Shema
GRANT USAGE ON SCHEMA public TO amour_flask, amour_next;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO amour_next;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO amour_next;

-- Flask: vse razen agent_/mcp_
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO amour_flask;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO amour_flask;
REVOKE ALL ON TABLE
  agent_pravila, agent_pravila_zgodovina, agent_predloge,
  agent_nabiralniki, agent_audit,
  mcp_oauth_clients, mcp_auth_codes, mcp_tokens
FROM amour_flask;

-- Privzete pravice za nove tabele
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO amour_next;
```

3. Heroku `DATABASE_URL` → connection string z `amour_flask`.
4. Vercel `DATABASE_URL` → connection string z `amour_next`.
5. Rotiraj stari shared password.

Dokler to ni narejeno, Flask ostaja blast radius za v2 skrivnosti —
zato so P0 luknje v Flasku (HMAC, MK webhook, SECRET_KEY) nujne.
