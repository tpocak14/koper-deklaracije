# Flask machine-only mode

**Status: privzeto ON na Heroku** (`DYNO` nastavljen).

Ljudje uporabljajo samo **v2** (`deklaracije.eu`). Flask ostane headless:

| Dovoljeno | Namen |
|-----------|--------|
| `/webhook/*` | Shopify webhooki |
| `/api/internal/*` | Cron + klici iz v2 (`CRON_SECRET`) |
| `/api/mk/.../secret`, `/api/mk/webhook/stock` | MetaKocka |
| `/api/health` | Healthcheck |
| `/apps/deklaracije/*` | Storefront (inspired-image prek Vercel edge) |
| `/shopify/install`, `/shopify/callback` | Shopify app OAuth |

Vse ostalo (login, HTML UI, `/api/narocila`, …) → **404**.

## Izklop (samo za nujni debug)

```bash
heroku config:set FLASK_MACHINE_ONLY=0 -a amour-deklaracije-staging
```

Lokalno je privzeto OFF (brez `DYNO`); vklop:

```bash
export FLASK_MACHINE_ONLY=1
```
