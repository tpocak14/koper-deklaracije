# Cutover Flask → v2 (deklaracije + umik)

## Trenutno stanje (2026-08-04)

| Komponenta | Kdo | Flag |
|------------|-----|------|
| UI | **v2 only** | — |
| Flask UI/login | **OFF** | `FLASK_MACHINE_ONLY` (privzeto ON) |
| Declarations vrstice (Faza 1) | v2 cron 18:40 UTC | vedno |
| PDF + MK upload (Faza 2) | v2 + Flask backup | `DECL_BATCH_FULL` na Vercel |
| Mandrill send (safety-net) | **še Flask** | `DECL_SENDER_ENABLED` (OFF) |
| Shadow parity | v2 hourly | ~96% `matches_flask` |

## Korak 1 — PDF/MK na v2 (zdaj)

1. Vercel: `DECL_BATCH_FULL=1` (production) + redeploy
2. Flask 21:00 ostane kot varnostna mreža (idempotentno: `pdf_generated_at` / `mk_decl_uploaded_at`)
3. Naslednji dan preveri Vercel cron log `/api/cron/declaration-batch` → `fullPhase.mkUploaded`
4. Če OK: `heroku config:set DISABLE_DAILY_DECLARATIONS_JOB=1`

## Korak 2 — Mandrill send na v2 (kasneje)

1. Preglej `decl_shadow_log` mismatch-e (`matches_flask = false`)
2. Vercel: `DECL_SENDER_ENABLED=1`
3. Heroku: `DISABLE_SAFETY_NET_JOB=1` (in po potrebi ostale send jobe)
4. 48h opazovanje (bounce / blocked / Mandrill)

## Korak 3 — Ostalo

- Shopify paid/cancel/refund zaloga
- MK stock webhook
- Ugasniti Heroku

## Rollback

```bash
# Vercel
vercel env rm DECL_BATCH_FULL production --yes   # ali nastavi 0
# Heroku
heroku config:unset DISABLE_DAILY_DECLARATIONS_JOB -a amour-deklaracije-staging
```
