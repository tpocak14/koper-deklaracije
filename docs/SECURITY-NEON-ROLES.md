# Neon least-privilege: Flask ne sme brati agent_/mcp_

**Status (2026-08-04): uveljavljeno.**

| App | Role | Kje |
|-----|------|-----|
| Flask (Heroku) | `amour_flask` | `DATABASE_URL` |
| Next.js (Vercel) | `amour_next` | `DATABASE_URL` |
| Admin / migracije | `neondb_owner` | samo ročno (geslo rotirano) |

## Zakaj

Če kdo vdremo v Flask, ne sme videti:

- `agent_nabiralniki.geslo_encrypted` (IMAP App Password-i)
- `mcp_tokens` / `mcp_oauth_clients`
- `agent_pravila`, `agent_audit`, …

## Preverjanje

```bash
# mora pasti
psql "$HEROKU_DATABASE_URL" -c "SELECT * FROM agent_nabiralniki LIMIT 1"
# mora delati
psql "$HEROKU_DATABASE_URL" -c "SELECT count(*) FROM orders"
```

## Nove skupne tabele (brez agent_/mcp_)

`amour_flask` **nima** samodejnih pravic na tabelah, ki jih ustvari `amour_next`
ali `neondb_owner` (da agent_* ne uidejo). Po novi skupni migraciji:

```sql
-- kot neondb_owner
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE ime_tabele TO amour_flask;
GRANT USAGE, SELECT ON SEQUENCE ime_tabele_id_seq TO amour_flask; -- če obstaja
```

## Flask migracije (DDL)

Web dyno teče kot `amour_flask` (DML + CREATE na `public`). Če migracija
zahteva `ALTER` na tabeli v lasti `neondb_owner`, jo zaženi enkrat kot owner:

```bash
psql "$OWNER_URL" -f migrations/0xx_....sql
```

## Gesla

- App gesla so v Heroku/Vercel `DATABASE_URL` (ne v gitu).
- `neondb_owner` geslo je bilo rotirano ob uvedbi; shrani ga v password manager.
  Stari shared connection string več ne deluje.
