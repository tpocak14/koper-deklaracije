"""
services/declaration_safety_net.py
==================================

Pošiljanje PDF deklaracij kupcem (od 2026-05-26 dalje **primarni sender**).

Arhitektura
-----------
1. Naša aplikacija tvori PDF deklaracijo za vsako Shopify naročilo s parfumi
   (ob 21:00 dnevno + ob ročnih izjemnih primerih).
2. PDF naložimo na MetaKocka sales_order kot prilogo (audit/arhiv).
3. **Sami pošljemo email kupcu** prek Mandrill API-ja, v jeziku po
   `country_code` naročila (`pick_declaration_template_name`).
4. MK Mandrill avto-trigger za 'deklaracije_si' je **izklopljen v MK
   admin-u** (sicer dvojni mail tujim kupcem).

Iz MK potrebujemo le signal `status = Zaključeno` (preko polling-a vsakih
30 min ali webhook-a). Tako vemo, kdaj je naročilo dokončno predano in
varno za pošiljanje deklaracije.

Zakaj ne pošljemo takoj ob fulfillment-u?
- Zaposleni vnašajo serije/roke do 21:00 — pred tem PDF ne sme biti tvorjen
- MK status `Zaključeno` je končni indikator dokončanja
- Če MK označi `Vračilo paketa`, pošiljanje preskočimo

Robustnost
----------
- PDF tvorba lahko spodleti (manjkajoča INCI, pretečene serije, manjkajoči
  Shopify metafields, multi-store mismatch). Strukturirano blokado označimo
  in admin obvestimo.
- Idempotency: pred vsakim send-om preverimo Mandrill log za isti
  template + order_id; če že obstaja, preskočimo.

Strategija pošiljanja
---------------------
Smart retry s strukturirano klasifikacijo blokad:

  1. Identificiramo kandidate (requires_declaration=TRUE,
     mk_status = 'Zaključeno', deklaracija še ni poslana).
  2. Za vsakega preverimo, ali se da PDF generirati:
     - če NE → shranimo strukturirane razloge (pdf_generation_blocked_codes),
       povezane parfume (pdf_generation_blocked_parfumi) in opozorimo admina.
       NE ponavljamo retry-ja avtomatsko; čakamo na invalidation hook
       (ko admin vnese serijo, popravi INCI, ali pride product/update webhook
       z novimi metafields, prizadetim naročilom resetiramo blocked flag).
  3. Če PDF gre skozi:
     a. Naložimo v MK na sales_order kot prilogo (audit/arhiv).
     b. Pošljemo email kupcu preko Mandrill API z lokaliziranim template-om
        in PDF prilogo.
  4. Za vsak direkten Mandrill send shranimo message_id in čez 15+ minut
     preverimo status (verify job). Pri bounced/rejected pošljemo admin alert.

Reason codes (pdf_generation_blocked_codes)
-------------------------------------------

| code                  | scenarij                                      | invalidation trigger             |
|-----------------------|-----------------------------------------------|----------------------------------|
| expired_serije        | vse serije parfuma so pretekle                | vnos nove serije (rok ≥ danes)   |
| missing_inci          | parfum nima INCI sestave v DB                 | INCI vnesen v parfumi tabelo     |
| missing_metafields    | Shopify produkt brez product_no/proizvajalec  | Shopify products/update webhook  |
| parfum_not_in_db      | Shopify ima produkt, naša DB nima parfum-a    | sync iz Shopify ali ročni vnos   |
| shopify_unreachable   | Shopify ni vrnil podatkov (token/shop_domain) | popravljen shopify_store_domain  |
| line_items_missing    | line_items v Shopify so prazni                | re-sync iz Shopify (orders/get)  |
| unknown               | neznana napaka                                | ročno reševanje                  |

Public entry points
-------------------
- analyze_order(order_data, cursor) → dict
- process_one(order_data, cursor) → dict (rezultat akcije)
- run_safety_net_job(window_days=14) → dict (stats za log/alert)
- run_mandrill_verify_job() → dict (stats)
- invalidate_blocks_for_parfum(parfum_id, code, cursor)
- invalidate_blocks_for_shopify_product(product_no, proizvajalec_ime, cursor)

Vse funkcije so safe za klicanje iz Flask request handler-jev in iz APScheduler
cron-a (uporabljajo current_app, get_db ipd.).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from flask import current_app
from database import get_db

from services import mandrill_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reason code klasifikacija
# ---------------------------------------------------------------------------

CODE_EXPIRED_SERIJE = "expired_serije"
CODE_MISSING_INCI = "missing_inci"
CODE_MISSING_METAFIELDS = "missing_metafields"
CODE_PARFUM_NOT_IN_DB = "parfum_not_in_db"
CODE_SHOPIFY_UNREACHABLE = "shopify_unreachable"
CODE_LINE_ITEMS_MISSING = "line_items_missing"
CODE_UNKNOWN = "unknown"

CODE_LABELS = {
    CODE_EXPIRED_SERIJE: "Vse serije parfuma so pretekle (rok < danes)",
    CODE_MISSING_INCI: "Manjka INCI sestava v DB",
    CODE_MISSING_METAFIELDS: "Manjka product_no ali proizvajalec_id v Shopify metafields",
    CODE_PARFUM_NOT_IN_DB: "Parfum obstaja v Shopify, manjka v naši DB",
    CODE_SHOPIFY_UNREACHABLE: "Shopify ni vrnil podatkov (preveri shop_domain in token)",
    CODE_LINE_ITEMS_MISSING: "Line items v Shopify so prazni",
    CODE_UNKNOWN: "Neznana napaka",
}


# ============================================================================
# Lokalizacija Mandrill template-ov
# ============================================================================
#
# Mandrill ima ločene template-e po jeziku (subject + body), ki uporabljajo
# isti nabor merge_vars. Glede na `country_code` naročila izberemo pravi
# template. PDF priponka je že tvorjena v ustreznem jeziku (glej pdf_service.
# ustvari_pdf — uporablja `lang_suffix` po country_code).
#
# Trenutno na Mandrillu obstajajo: deklaracije_si, deklaracije_en,
# deklaracije_de, deklaracije_hr, deklaracije_hu, deklaracije_it.
#
# ARHITEKTURNA ODLOČITEV (2026-05-26):
# Vse pošiljanje deklaracij opravlja **naša aplikacija** (Mandrill API).
# MetaKocka Order Management služi le kot signal: ko ima naročilo status
# `Zaključeno`, naš hourly safety-net job pošlje pravi jezikovni Mandrill
# template. MK-jev avtomatski Mandrill trigger mora biti v MK admin-u
# **izklopljen** (sicer bi kupci v tujini dobili dvojni mail: SI od MK +
# pravi jezik od nas).

# Mapping: ISO-3166 country_code → Mandrill template name (publish name).
# Privzeto za neznane države je `deklaracije_en`.
DECLARATION_TEMPLATE_BY_COUNTRY: Dict[str, str] = {
    "SI": "deklaracije_si",
    "HR": "deklaracije_hr",
    "DE": "deklaracije_de",
    "AT": "deklaracije_de",
    "HU": "deklaracije_hu",
    "IT": "deklaracije_it",
}

DEFAULT_DECLARATION_TEMPLATE = "deklaracije_en"


def pick_declaration_template_name(country_code: Optional[str]) -> str:
    """Izbere Mandrill template name (publish name) za jezik kupca.

    Vrne npr. 'deklaracije_si', 'deklaracije_de', ... Privzeto
    DEFAULT_DECLARATION_TEMPLATE ('deklaracije_en') če country_code ni
    znan ali jezikovne predloge ni v `DECLARATION_TEMPLATE_BY_COUNTRY`.

    Args:
        country_code: ISO-3166 alpha-2 koda iz `orders.country_code`
            (npr. 'SI', 'DE', 'AT'). Primerja se case-insensitive.

    Returns:
        Publish name template-a, ki ga sprejme Mandrill API
        (`messages/send-template.json`).
    """
    if not country_code:
        return DEFAULT_DECLARATION_TEMPLATE
    return DECLARATION_TEMPLATE_BY_COUNTRY.get(
        country_code.strip().upper(), DEFAULT_DECLARATION_TEMPLATE
    )


def classify_blockers(missing_strings: List[str]) -> List[str]:
    """Pretvori human-readable missing strings v structured codes."""
    codes: set[str] = set()
    for raw in missing_strings or []:
        s = (raw or "").lower()
        if "ni razpoložljive serije" in s or "ni razpolozljive serije" in s or "rok" in s and "potek" in s:
            codes.add(CODE_EXPIRED_SERIJE)
        elif "manjka inci" in s and "shopify" not in s:
            # "Manjka INCI" lahko pomeni: ni parfum-a v DB ali pa parfum brez INCI.
            # Brez dodatnega lookupa ne vemo zagotovo - default missing_inci.
            codes.add(CODE_MISSING_INCI)
        elif "manjka product_no" in s or "manjka proizvajalec_ime" in s or "manjka proizvajalec" in s:
            codes.add(CODE_MISSING_METAFIELDS)
        elif "shopify ni vrnil" in s or "shop_domain" in s:
            codes.add(CODE_SHOPIFY_UNREACHABLE)
        elif "line_items" in s:
            codes.add(CODE_LINE_ITEMS_MISSING)
        else:
            codes.add(CODE_UNKNOWN)
    return sorted(codes)


# ---------------------------------------------------------------------------
# Pomožne funkcije za parfum lookup (za invalidation)
# ---------------------------------------------------------------------------

def _extract_blocked_parfumi_ids(declaration_items: List[Dict[str, Any]],
                                 cursor, shopify_details: Dict[str, Any]) -> List[int]:
    """Iz blokade pridobi parfum_id-je v DB (za smart invalidation).

    Args:
        declaration_items: line items naročila po Shopify lookup-u
        cursor: DB cursor
        shopify_details: mapping product_id → {product_no, proizvajalec_id}

    Returns:
        seznam parfum_id-jev (int), ki so povezani z blokado
    """
    ids: set[int] = set()
    for product_id, details in (shopify_details or {}).items():
        product_no = (details or {}).get("product_no")
        proizvajalec_ime = ((details or {}).get("proizvajalec_id") or "").upper()
        if not product_no or not proizvajalec_ime:
            continue
        try:
            cursor.execute(
                "SELECT p.id FROM parfumi p "
                "JOIN proizvajalci pr ON p.proizvajalec_id = pr.id "
                "WHERE p.product_no = %s AND UPPER(pr.ime) = %s",
                (product_no, proizvajalec_ime),
            )
            row = cursor.fetchone()
            if row:
                ids.add(row[0] if not isinstance(row, dict) else row["id"])
        except Exception as e:
            logger.warning("Failed to resolve parfum_id for %s/%s: %s",
                           product_no, proizvajalec_ime, e)
    return sorted(ids)


# ---------------------------------------------------------------------------
# Analiza enega naročila
# ---------------------------------------------------------------------------

def _parse_line_items(order_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Robustno parsiraj line_items iz orders.line_items polja."""
    raw = order_data.get("line_items") if isinstance(order_data, dict) else None
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            return []
    return []


def analyze_order(order_data: Dict[str, Any], cursor) -> Dict[str, Any]:
    """Analiziraj naročilo glede možnosti tvorbe PDF deklaracije.

    Args:
        order_data: dict iz orders SELECT *
        cursor: DB cursor

    Returns:
        {
          'order_number': str,
          'requires_declaration': bool,
          'declaration_items': list,           # če je vse OK, sicer []
          'missing': list[str],                # human-readable razlogi
          'warnings': list[str],               # opozorila (expiry < 60d)
          'blocked': bool,                     # True če PDF ne moremo tvoriti
          'blocked_codes': list[str],
          'blocked_parfumi': list[int],
        }
    """
    order_number = order_data.get("order_number") if isinstance(order_data, dict) else None
    shop_domain = order_data.get("shopify_store_domain") if isinstance(order_data, dict) else None

    line_items = _parse_line_items(order_data)
    if not line_items:
        return {
            "order_number": order_number,
            "requires_declaration": True,  # konzervativno: ne moremo dokazat nasprotnega
            "declaration_items": [],
            "missing": ["line_items v Shopify so prazni"],
            "warnings": [],
            "blocked": True,
            "blocked_codes": [CODE_LINE_ITEMS_MISSING],
            "blocked_parfumi": [],
        }

    try:
        from blueprints.api_routes import _pridobi_podatke_za_deklaracijo_iz_shopify
        from services.shopify_service import get_bulk_product_details
    except Exception as e:
        logger.error("Cannot import declaration helpers: %s", e)
        return {
            "order_number": order_number,
            "requires_declaration": True,
            "declaration_items": [],
            "missing": [f"Internal import error: {e}"],
            "warnings": [],
            "blocked": True,
            "blocked_codes": [CODE_UNKNOWN],
            "blocked_parfumi": [],
        }

    # En sam Shopify klic - reuse za requires_declaration in invalidation lookup
    product_ids = [str(item["product_id"]) for item in line_items if item and item.get("product_id")]
    shopify_details: Dict[str, Any] = {}
    if product_ids:
        try:
            shopify_details = get_bulk_product_details(product_ids, shop_domain=shop_domain) or {}
        except Exception as e:
            logger.warning("get_bulk_product_details failed for %s: %s", order_number, e)

    # Določi requires_declaration: ali vsaj 1 line item ima product_type='parfumi'
    requires_declaration = any(
        ((d or {}).get("product_type") or "").strip().lower() == "parfumi"
        for d in shopify_details.values()
    )

    # Pridobi declaration items prek obstoječe Flask logike (uporabi isti cursor)
    declaration_items, missing, warnings = _pridobi_podatke_za_deklaracijo_iz_shopify(
        line_items, cursor, shop_domain=shop_domain
    )

    # Strukturirana klasifikacija razlogov
    blocked = bool(missing)
    codes = classify_blockers(missing)

    # Pridobi parfum_id-je za smart invalidation
    blocked_parfumi: List[int] = []
    if blocked and requires_declaration:
        try:
            blocked_parfumi = _extract_blocked_parfumi_ids(declaration_items, cursor, shopify_details)
        except Exception as e:
            logger.warning("Failed to extract blocked parfumi ids: %s", e)

    return {
        "order_number": order_number,
        "requires_declaration": requires_declaration,
        "declaration_items": declaration_items or [],
        "missing": missing or [],
        "warnings": warnings or [],
        "blocked": blocked,
        "blocked_codes": codes,
        "blocked_parfumi": blocked_parfumi,
    }


# ---------------------------------------------------------------------------
# MK status check (cached)
# ---------------------------------------------------------------------------

def mk_check_sales_order_status(mk_sales_order_id: Optional[str]) -> Optional[str]:
    """Vrne MK status_desc za sales_order (npr. 'shipped', 'completed').

    Backwards-compatible wrapper: za nov code path uporabi
    mk_check_sales_order_status_full() ki vrne tudi status_code (Slovene
    human-readable npr. "Vračilo paketa", "Zaključeno").
    """
    full = mk_check_sales_order_status_full(mk_sales_order_id)
    return full.get("status_desc") or full.get("status_code") if full else None


def mk_check_sales_order_status_full(mk_sales_order_id: Optional[str]) -> Dict[str, Optional[str]]:
    """Vrne dict z status_desc IN status_code za sales_order.

    Returns:
        {"status_desc": str|None, "status_code": str|None}

    Status convention v MK:
      - status_desc = machine readable (en): "completed", "shipped", "returned"
      - status_code = human readable (sl):  "Zaključeno", "Odpremljeno", "Vračilo paketa"
    """
    empty = {"status_desc": None, "status_code": None}
    if not mk_sales_order_id:
        return empty
    try:
        from services.mk_service import mk_get_document
        try:
            doc = mk_get_document("sales_order", str(mk_sales_order_id))
        except RuntimeError as e:
            logger.info("mk_get_document(sales_order, %s) miss: %s", mk_sales_order_id, e)
            return empty
        if not doc or not isinstance(doc, dict):
            return empty
        return {
            "status_desc": doc.get("status_desc"),
            "status_code": doc.get("status_code"),
        }
    except Exception as e:
        logger.warning("mk_check_sales_order_status_full(%s) failed: %s", mk_sales_order_id, e)
        return empty


def classify_mk_status(status_desc: Optional[str], status_code: Optional[str]) -> str:
    """Klasificiraj MK status v 4 kategorije za safety net flow.

    Returns:
        'completed' — naročilo dostavljeno + plačano → pošlji deklaracijo + Shopify Delivered
        'returned'  — paket se vrača nazaj → STOP, ne pošiljaj, ne markaj Delivered
        'shipped'   — paket na poti → čakaj (MK bo sam sprožil Mandrill ob completion)
        'pending'   — pred odpremo (za odpremo, izdaja računa) → čakaj
        'unknown'   — neznan / MK API ne odgovori
    """
    desc = (status_desc or "").strip().lower()
    code = (status_code or "").strip().lower()

    # Returned: MK status_code je "Vračilo paketa" (slo) ali status_desc "returned"
    return_keywords = ("vrač", "vrac", "vrnitev", "return")
    if any(k in desc for k in return_keywords) or any(k in code for k in return_keywords):
        return "returned"

    # Completed: "Zaključeno" / "completed" / "closed"
    completed_keywords = ("complet", "closed", "zaključ", "zakljuc", "končan", "koncan")
    if any(k in desc for k in completed_keywords) or any(k in code for k in completed_keywords):
        return "completed"

    # Shipped / Odpremljeno / Predano dostavni službi
    shipped_keywords = ("shipped", "odpremlj", "predano", "dispatched", "delivered")
    if any(k in desc for k in shipped_keywords) or any(k in code for k in shipped_keywords):
        return "shipped"

    # Pending: za odpremo, izdaja računa, draft, ...
    if desc or code:
        return "pending"
    return "unknown"


def mk_find_and_cache_sales_order_id(order_number: str, cursor) -> Optional[str]:
    """Poišči mk_sales_order_id v MK-ju (prek title search) in ga cache-aj.

    To uporabljamo, ko v lokalni DB manjka mk_sales_order_id, ampak ga
    potrebujemo za safety net (priponka MORA iti na sales_order, da MK
    sproži Mandrill trigger).

    Returns mk_id ali None.
    """
    if not order_number:
        return None
    try:
        from services.mk_service import mk_find_sales_order_by_title
        clean = str(order_number).lstrip("#").strip()
        so = mk_find_sales_order_by_title(clean) or mk_find_sales_order_by_title(order_number)
        if not so:
            return None
        mk_id = so.get("mk_id") or so.get("id") or so.get("doc_id")
        if not mk_id:
            return None
        # Cache v lokalnem DB za hitre nadaljnje klice (in Next.js)
        try:
            cursor.execute(
                """
                UPDATE orders SET
                    mk_sales_order_id = %s,
                    mk_last_checked_at = NOW()
                  WHERE (order_number = %s OR order_number = %s)
                """,
                (str(mk_id), order_number, f"#{clean}")
            )
        except Exception as e:
            logger.warning("Failed to cache mk_sales_order_id for %s: %s", order_number, e)
        return str(mk_id)
    except Exception as e:
        logger.warning("mk_find_and_cache_sales_order_id(%s) failed: %s", order_number, e)
        return None


# ---------------------------------------------------------------------------
# Mandrill merge_vars builder
# ---------------------------------------------------------------------------

def _format_eur(value: Any) -> str:
    """Format decimal/string kot '12,34'."""
    if value is None:
        return ""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return str(value)
    s = f"{n:.2f}"
    return s.replace(".", ",")


def _shopify_order_payload(order_data: Dict[str, Any]) -> Dict[str, Any]:
    """Pridobi raw Shopify payload za boljše merge vars (če je shranjen).

    Trenutno koristimo lokalno shranjene podatke iz `orders` tabele, ker je
    Shopify Admin API klic dragocen. Če bodo merge vars nepopolni, lahko v
    prihodnosti dodamo fallback na Shopify GET /orders/{id}.json.
    """
    return order_data if isinstance(order_data, dict) else {}


def build_mandrill_merge_vars(
    order_data: Dict[str, Any],
    declaration_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Zgradi global_merge_vars za Mandrill template 'deklaracije_si'.

    Template uporablja mailchimp merge syntax (*|key|*). Polja sledijo
    konvenciji, ki jo MK pošlje (glej primer Mandrill napake za SI2377).

    Args:
        order_data: dict iz orders SELECT
        declaration_items: PDF declaration items (ne uporabimo za vse,
            samo za quick reference)

    Returns:
        List of {'name': key, 'content': value} za Mandrill API.
    """
    o = _shopify_order_payload(order_data)
    order_number = (o.get("order_number") or "").lstrip("#")

    # Customer / receiver fields
    customer_name = (o.get("customer_name")
                     or _compose_name(o.get("customer_first_name"), o.get("customer_last_name"))
                     or o.get("customer_email") or "")
    customer_email = o.get("customer_email") or ""
    addr = _parse_address(o.get("shipping_address")) or _parse_address(o.get("billing_address")) or {}

    today_str = date.today().strftime("%d.%m.%Y")
    shipped_str = _format_date(o.get("shopify_fulfilled_at") or o.get("fulfilled_at") or o.get("shipped_at"))

    tracking_no = o.get("tracking_number") or ""
    tracking_url = o.get("tracking_url") or ""

    total = _format_eur(o.get("total_price") or o.get("amount"))

    # Build product_list & items_summary HTML
    items_summary_html, items_summary_material, items_summary_service, items_summary_sms, product_list = (
        _build_items_summary(o, declaration_items)
    )

    payment_amount_html = f"{total} EUR<br>" if total else ""

    vars_map: Dict[str, Any] = {
        "customer_name": customer_name,
        "customer_street": addr.get("street", ""),
        "customer_postal_code": addr.get("zip", ""),
        "customer_post": addr.get("city", ""),
        "customer_province": addr.get("province", ""),
        "customer_country": addr.get("country", ""),
        "customer_email": customer_email,
        "current_year": str(date.today().year),
        "current_date": today_str,
        "receiver_name": customer_name,
        "receiver_street": addr.get("street", ""),
        "receiver_postal_code": addr.get("zip", ""),
        "receiver_post": addr.get("city", ""),
        "receiver_province": addr.get("province", ""),
        "receiver_country": addr.get("country", ""),
        "order_payment_method": o.get("payment_method") or "",
        "payment_amount": payment_amount_html,
        "order_items_summary": items_summary_html,
        "order_items_summary_material": items_summary_material,
        "order_items_summary_service": items_summary_service,
        "order_items_summary_sms": items_summary_sms,
        "order_items_out_of_stock_summary": "",
        "order_id": order_number,
        "order_amount": total,
        "store_email": "orders@amourparfums.com",
        "store_name": o.get("shopify_store_domain") or "amourparfums.com",
        "thank_you_after_shipment_email_sent_at": today_str,
        "shipped_date": shipped_str,
        "parcel_tracking_number": tracking_no,
        "parcel_track_and_trace_url": tracking_url,
        "tracking_url": tracking_url,
        "tracking_url_short": tracking_url,
        "tracking_page_url": tracking_url,
        "gls_parcel_tracking_number": tracking_no,
        "gls_parcel_track_and_trace_url": tracking_url,
        "product_list": product_list,
    }

    # Convert to Mandrill format
    return [{"name": k, "content": v} for k, v in vars_map.items()]


# ---------------------------------------------------------------------------
# Mandrill send (primary) + SMTP fallback (opt-in)
# ---------------------------------------------------------------------------

_MANDRILL_FAILURE_STATUSES = frozenset(
    {"rejected", "invalid", "bounced", "soft-bounced", "spam"}
)


def smtp_declaration_fallback_enabled() -> bool:
    """SMTP rezerva je privzeto izklopljena; vklopi z SMTP_DECLARATION_FALLBACK=1."""
    v = (os.environ.get("SMTP_DECLARATION_FALLBACK", "") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _mandrill_already_sent(order_data: Dict[str, Any]) -> bool:
    mid = order_data.get("mandrill_safety_message_id")
    if not mid:
        return False
    status = (order_data.get("mandrill_safety_status") or "").lower()
    return status not in _MANDRILL_FAILURE_STATUSES


def _fulfilled_at_local_date(order_data: Dict[str, Any]) -> Optional[date]:
    """Datum fulfill-a v Europe/Ljubljana (za 21:00 batch pravilo)."""
    raw = order_data.get("shopify_fulfilled_at") or order_data.get("fulfilled_at")
    if not raw:
        return None
    try:
        from zoneinfo import ZoneInfo

        lj = ZoneInfo("Europe/Ljubljana")
    except Exception:
        lj = timezone.utc
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, date):
        return raw
    else:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(lj).date()


def should_wait_for_2100_pdf_batch(order_data: Dict[str, Any]) -> Tuple[bool, str]:
    """PDF za današnja fulfilled naročila se pripravi šele ob 21:00 (Ljubljana)."""
    try:
        from zoneinfo import ZoneInfo

        lj = ZoneInfo("Europe/Ljubljana")
        now = datetime.now(lj)
    except Exception:
        return False, ""
    if now.hour >= 21:
        return False, ""
    fulfilled_day = _fulfilled_at_local_date(order_data)
    if fulfilled_day and fulfilled_day == now.date():
        return True, (
            "PDF deklaracije za današnja fulfilled naročila se pripravi ob 21:00. "
            "Pošiljanje in generiranje PDF-ja sta onemogočena do takrat."
        )
    return False, ""


def check_mk_completed_for_send(
    order_data: Dict[str, Any], cursor
) -> Dict[str, Any]:
    """Preveri, ali je MK status 'Zaključeno' — obvezen pred pošiljanjem kupcu."""
    order_number = order_data.get("order_number")
    mk_sales_order_id = order_data.get("mk_sales_order_id")
    if not mk_sales_order_id:
        mk_sales_order_id = mk_find_and_cache_sales_order_id(order_number, cursor)
    if not mk_sales_order_id:
        return {
            "ok": False,
            "category": "unknown",
            "reason": (
                "MK sales_order ni najden — pošiljanje deklaracije ni dovoljeno "
                "dokler naročilo ni vidno v MetaKocki."
            ),
        }
    mk_status_full = mk_check_sales_order_status_full(mk_sales_order_id)
    mk_category = classify_mk_status(
        mk_status_full.get("status_desc"), mk_status_full.get("status_code")
    )
    cursor.execute(
        """
        UPDATE orders SET
            mk_sales_order_id = COALESCE(mk_sales_order_id, %s),
            mk_last_status_desc = %s,
            mk_last_status_code = %s,
            mk_last_status_at = NOW()
        WHERE order_number = %s
        """,
        (
            mk_sales_order_id,
            mk_status_full.get("status_desc"),
            mk_status_full.get("status_code"),
            order_number,
        ),
    )
    if mk_category == "returned":
        return {
            "ok": False,
            "category": "returned",
            "reason": "MK status: Vračilo paketa — deklaracija se ne pošlje.",
        }
    if mk_category != "completed":
        status_label = (
            mk_status_full.get("status_code")
            or mk_status_full.get("status_desc")
            or "neznano"
        )
        return {
            "ok": False,
            "category": mk_category,
            "reason": (
                f"MK status ni 'Zaključeno' (trenutno: {status_label}). "
                f"Deklaracija se pošlje šele po zaključku naročila v MK."
            ),
        }
    return {"ok": True, "category": "completed", "reason": ""}


def validate_declaration_send_allowed(
    order_data: Dict[str, Any], cursor, *, check_pdf_batch: bool = True
) -> Optional[str]:
    """Če pošiljanje ni dovoljeno, vrne human-readable razlog (sicer None)."""
    if check_pdf_batch:
        wait, msg = should_wait_for_2100_pdf_batch(order_data)
        if wait:
            return msg
    mk = check_mk_completed_for_send(order_data, cursor)
    if not mk.get("ok"):
        return mk.get("reason") or "MK status ne dovoli pošiljanja."
    if not order_data.get("pdf_generated_at") and not order_data.get("mk_decl_uploaded_at"):
        return (
            "PDF deklaracije še ni pripravljen (pričakovano ob 21:00 batch-u). "
            "Pošiljanje ni dovoljeno."
        )
    return None

def send_declaration_via_mandrill(
    order_data: Dict[str, Any],
    pdf_path: str,
    declaration_items: List[Dict[str, Any]],
    cursor,
    *,
    force: bool = False,
    skip_log_cross_check: bool = False,
) -> Dict[str, Any]:
    """Pošlji deklaracijo kupcu prek Mandrill template API.

    Returns dict: success, message_id, status, template, reason, action.
    """
    order_number = order_data.get("order_number")
    result: Dict[str, Any] = {
        "success": False,
        "order_number": order_number,
        "message_id": None,
        "status": None,
        "template": None,
        "reason": "",
        "action": "error",
    }

    if not order_number:
        result["reason"] = "missing_order_number"
        return result

    mk_gate = check_mk_completed_for_send(order_data, cursor)
    if not mk_gate.get("ok"):
        result["action"] = "waiting_mk_completed"
        result["reason"] = mk_gate.get("reason") or "mk_not_completed"
        return result

    if not force and _mandrill_already_sent(order_data):
        result["success"] = True
        result["message_id"] = order_data.get("mandrill_safety_message_id")
        result["status"] = order_data.get("mandrill_safety_status")
        result["action"] = "already_sent"
        result["reason"] = f"že poslano: {result['message_id']}"
        return result

    country_code = (order_data.get("country_code") or "").strip().upper() or None
    target_template_name = pick_declaration_template_name(country_code)
    target_template_slug = target_template_name.replace("_", "-")
    result["template"] = target_template_name

    if not skip_log_cross_check:
        try:
            recipient_email = order_data.get("customer_email") or order_data.get("email")
            if recipient_email:
                from datetime import timedelta as _td

                cutoff_from = (datetime.now() - _td(days=14)).strftime("%Y-%m-%d")
                cutoff_to = (datetime.now() + _td(days=1)).strftime("%Y-%m-%d")
                msgs = mandrill_service.messages_search(
                    query=(
                        f"full_email:{recipient_email} AND template:{target_template_slug}"
                    ),
                    date_from=cutoff_from,
                    date_to=cutoff_to,
                    limit=20,
                )
                own_order = str(order_number).lstrip("#").strip()
                for m in msgs or []:
                    md = m.get("metadata") or {}
                    mid_order = str(md.get("order_id") or "").lstrip("#").strip()
                    if mid_order and mid_order == own_order:
                        message_id = m.get("_id")
                        cursor.execute(
                            """
                            UPDATE orders SET
                                mandrill_safety_attempted_at = COALESCE(mandrill_safety_attempted_at, NOW()),
                                mandrill_safety_message_id = %s,
                                mandrill_safety_status = %s
                              WHERE order_number = %s
                            """,
                            (message_id, "sent_externally", order_number),
                        )
                        result["success"] = True
                        result["message_id"] = message_id
                        result["status"] = "sent_externally"
                        result["action"] = "sent_externally"
                        result["reason"] = (
                            f"Mandrill log že vsebuje {target_template_slug}: {message_id}"
                        )
                        return result
        except Exception as e:
            logger.warning("Mandrill log cross-check failed for %s: %s", order_number, e)

    merge_vars = build_mandrill_merge_vars(order_data, declaration_items)
    if not pdf_path or not os.path.isfile(pdf_path):
        result["reason"] = "pdf_missing"
        return result

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    recipient_email = order_data.get("customer_email") or order_data.get("email")
    if not recipient_email:
        result["reason"] = "missing_customer_email"
        return result

    recipient_name = (
        order_data.get("customer_name")
        or _compose_name(
            order_data.get("customer_first_name"),
            order_data.get("customer_last_name"),
        )
        or recipient_email
    )

    bcc_admin = (os.environ.get("ADMIN_BCC_DECLARATION_EMAIL", "") or "").strip() or None
    order_number_clean = str(order_number or "").lstrip("#").strip()

    try:
        mandrill_resp = mandrill_service.send_template(
            template_name=target_template_name,
            to=[{"email": recipient_email, "name": recipient_name}],
            global_merge_vars=merge_vars,
            attachments=[
                {
                    "filename": f"Deklaracija_{order_number}.pdf",
                    "data": pdf_bytes,
                    "type": "application/pdf",
                }
            ],
            tags=[
                "safety-net",
                "declaration",
                target_template_name,
                f"order:{order_number_clean}",
            ],
            metadata={
                "order_id": order_number_clean,
                "country": country_code or "",
            },
            bcc_address=bcc_admin,
        )
    except Exception as e:
        logger.exception(
            "Mandrill send_template failed for %s (template=%s)",
            order_number,
            target_template_name,
        )
        result["reason"] = f"mandrill_send_failed: {e}"
        return result

    msg = (mandrill_resp or [{}])[0]
    message_id = msg.get("_id")
    status = msg.get("status", "unknown")

    cursor.execute(
        """
        UPDATE orders SET
            mandrill_safety_attempted_at = NOW(),
            mandrill_safety_message_id = %s,
            mandrill_safety_status = %s,
            email_sent_at = NOW(),
            email_recipient = %s,
            status = 'email_poslan'
        WHERE order_number = %s
        """,
        (message_id, status, recipient_email, order_number),
    )

    result["success"] = True
    result["message_id"] = message_id
    result["status"] = status
    result["action"] = "uploaded_and_mandrill"
    result["reason"] = f"mandrill sent (status={status})"
    return result


def try_smtp_declaration_fallback(
    order_data: Dict[str, Any],
    pdf_path: str,
    declaration_items: List[Dict[str, Any]],
    line_items: List[Dict[str, Any]],
    cursor,
) -> Dict[str, Any]:
    """Rezervna SMTP pot — samo če je SMTP_DECLARATION_FALLBACK=1."""
    order_number = order_data.get("order_number")
    out: Dict[str, Any] = {
        "success": False,
        "order_number": order_number,
        "channel": "smtp",
        "reason": "",
    }
    if not smtp_declaration_fallback_enabled():
        out["reason"] = "smtp_fallback_disabled"
        return out

    from services.email_service import poslji_email_s_pdf
    from flask import current_app

    recipient = order_data.get("customer_email") or order_data.get("email")
    if not recipient:
        out["reason"] = "missing_customer_email"
        return out

    shop_url = f"https://{current_app.config.get('SHOP_NAME', 'amour-parfums')}.myshopify.com"
    ok = poslji_email_s_pdf(
        recipient_email=recipient,
        order_number=order_number,
        shopify_order_id=order_data.get("shopify_order_id"),
        pdf_path=pdf_path,
        declaration_items=declaration_items,
        status_url=order_data.get("status_url"),
        shop_url=shop_url,
        country_code=order_data.get("country_code"),
        line_items=line_items,
        skip_test_redirect=True,
        allow_smtp_fallback=True,
    )
    if not ok:
        out["reason"] = "smtp_send_failed"
        return out

    cursor.execute(
        """
        UPDATE orders SET
            mandrill_safety_attempted_at = COALESCE(mandrill_safety_attempted_at, NOW()),
            mandrill_safety_status = 'legacy_smtp_sent',
            email_sent_at = NOW(),
            email_recipient = %s,
            status = 'email_poslan'
        WHERE order_number = %s
        """,
        (recipient, order_number),
    )
    out["success"] = True
    out["reason"] = "legacy_smtp_sent"
    return out


def send_declaration_email(
    order_data: Dict[str, Any],
    pdf_path: str,
    declaration_items: List[Dict[str, Any]],
    line_items: List[Dict[str, Any]],
    cursor,
    *,
    force: bool = False,
    allow_smtp_fallback: bool = True,
) -> Dict[str, Any]:
    """Primarna Mandrill pot; SMTP samo ob neuspehu (če je env vklopljen).

    NE kličite neposredno iz UI — uporabite process_one(), ki upošteva
    21:00 batch in MK status.
    """
    blocked = validate_declaration_send_allowed(order_data, cursor)
    if blocked:
        return {
            "success": False,
            "order_number": order_data.get("order_number"),
            "channel": "none",
            "reason": blocked,
            "action": "blocked",
        }

    mandrill = send_declaration_via_mandrill(
        order_data,
        pdf_path,
        declaration_items,
        cursor,
        force=force,
    )
    if mandrill.get("success"):
        mandrill["channel"] = "mandrill"
        return mandrill

    if allow_smtp_fallback and smtp_declaration_fallback_enabled():
        smtp = try_smtp_declaration_fallback(
            order_data, pdf_path, declaration_items, line_items, cursor
        )
        if smtp.get("success"):
            return smtp

    mandrill["channel"] = "none"
    return mandrill


def _compose_name(first: Optional[str], last: Optional[str]) -> Optional[str]:
    parts = [p for p in [first, last] if p]
    return " ".join(parts) if parts else None


def _parse_address(raw: Any) -> Optional[Dict[str, str]]:
    """Pretvori shipping_address (JSON ali dict) v normaliziran dict."""
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None
    if not isinstance(raw, dict):
        return None
    street = raw.get("address1") or raw.get("street") or ""
    if raw.get("address2"):
        street = f"{street}, {raw['address2']}" if street else raw["address2"]
    return {
        "street": street,
        "zip": raw.get("zip") or raw.get("postal_code") or "",
        "city": raw.get("city") or raw.get("post") or "",
        "province": raw.get("province") or raw.get("state") or "",
        "country": raw.get("country") or raw.get("country_name") or "",
    }


def _format_date(value: Any) -> str:
    """Format datum/timestamp kot 'dd.MM.yyyy'."""
    if not value:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%d.%m.%Y") if isinstance(value, date) else value.date().strftime("%d.%m.%Y")
    try:
        # ISO string
        s = str(value)[:10]
        y, m, d = s.split("-")
        return f"{d}.{m}.{y}"
    except Exception:
        return str(value)


def _build_items_summary(o: Dict[str, Any], declaration_items: List[Dict[str, Any]]) -> Tuple[str, str, str, str, List[Dict[str, Any]]]:
    """Zgradi HTML summary + product_list (handlebars style)."""
    line_items = _parse_line_items(o)

    material_lines: List[str] = []
    service_lines: List[str] = []
    sms_parts: List[str] = []
    product_list: List[Dict[str, Any]] = []

    total_material = 0.0
    for item in line_items:
        if not isinstance(item, dict):
            continue
        name = item.get("title") or item.get("name") or "?"
        qty = item.get("quantity") or 1
        price = item.get("price") or item.get("priceWithTax") or "0"
        try:
            price_f = float(price)
        except (TypeError, ValueError):
            price_f = 0.0
        sum_f = price_f * (qty or 1)
        total_material += sum_f

        # Heuristic: 'shipping' / 'gratis' / 'dostava' = service
        is_service = any(s in name.lower() for s in ("dostava", "shipping", "gratis", "pošta", "posta"))

        price_str = _format_eur(price_f)
        sum_str = _format_eur(sum_f)
        line_html = f"{qty} x <b>{name}</b> - {price_str} ({sum_str}) EUR<br>"
        if is_service:
            service_lines.append(line_html)
        else:
            material_lines.append(line_html)
        sms_parts.append(f"{qty}x {name}")

        product_list.append({
            "amount": str(qty),
            "name": name,
            "priceWithTax": price_str,
            "url_product": item.get("product_url"),
            "url_image": item.get("image_url"),
            "sumWithTax": sum_str,
            "is_service": is_service,
        })

    total_eur = _format_eur(o.get("total_price") or o.get("amount") or total_material)
    sms_parts.append(f"Skupaj {total_eur} EUR")

    summary_html = "".join(material_lines + service_lines)
    if material_lines or service_lines:
        summary_html += f"- - -<br>Skupaj: <b>{total_eur} EUR<br>"

    return (
        summary_html,
        "".join(material_lines),
        "".join(service_lines),
        ", ".join(sms_parts),
        product_list,
    )


# ---------------------------------------------------------------------------
# Process one order
# ---------------------------------------------------------------------------

def process_one(order_data: Dict[str, Any], cursor) -> Dict[str, Any]:
    """Procesiraj 1 naročilo skozi safety net.

    Returns:
        {
          'order_number': str,
          'action': 'skipped'|'blocked'|'uploaded_mk_only'|'uploaded_and_mandrill'|'error',
          'reason': str,
          'mandrill_message_id': str|None,
          'blocked_codes': list[str],
        }
    """
    order_number = order_data.get("order_number")
    result: Dict[str, Any] = {
        "order_number": order_number,
        "action": "skipped",
        "reason": "",
        "mandrill_message_id": None,
        "blocked_codes": [],
    }

    if not order_number:
        result["action"] = "error"
        result["reason"] = "missing_order_number"
        return result

    # 0. EARLY EXIT: če smo to naročilo že prej zaznali kot "Vračilo paketa",
    #    sploh ne kličemo MK API, ne tvorimo PDF-ja, ne pošljemo nič.
    if order_data.get("mk_return_detected_at"):
        result["action"] = "returned"
        result["reason"] = "mk_return_detected_at je nastavljen — paket se vrača"
        return result

    # 0b. EARLY CHECK MK STATUS: če MK kaže "Vračilo paketa", mark + abort.
    #     Ta klic je dovolj poceni (1-2s) in nam prihrani celotno PDF/upload pot.
    #     Klic naredimo SAMO če imamo cached mk_sales_order_id; sicer bomo to
    #     poskusili še kasneje (po analyze_order + mk lookup).
    mk_sales_order_id_cached = order_data.get("mk_sales_order_id")
    if mk_sales_order_id_cached:
        mk_status_full = mk_check_sales_order_status_full(mk_sales_order_id_cached)
        mk_category = classify_mk_status(
            mk_status_full.get("status_desc"), mk_status_full.get("status_code")
        )
        # Posnemi zadnji znan MK status (za UI / debug)
        cursor.execute(
            """
            UPDATE orders SET
                mk_last_status_desc = %s,
                mk_last_status_code = %s,
                mk_last_status_at   = NOW()
            WHERE order_number = %s
            """,
            (mk_status_full.get("status_desc"), mk_status_full.get("status_code"), order_number)
        )
        if mk_category == "returned":
            cursor.execute(
                """
                UPDATE orders SET
                    mk_return_detected_at = COALESCE(mk_return_detected_at, NOW())
                WHERE order_number = %s
                """,
                (order_number,)
            )
            logger.info(
                "Order %s skipped: MK status='%s/%s' = Vračilo paketa",
                order_number, mk_status_full.get("status_code"), mk_status_full.get("status_desc"),
            )
            result["action"] = "returned"
            result["reason"] = (
                f"MK status: {mk_status_full.get('status_code')} "
                f"({mk_status_full.get('status_desc')}) — paket se vrača, deklaracija se ne pošlje"
            )
            return result

    # 1. Analiza
    try:
        analysis = analyze_order(order_data, cursor)
    except Exception as e:
        logger.exception("analyze_order failed for %s", order_number)
        result["action"] = "error"
        result["reason"] = f"analyze_error: {e}"
        return result

    # 2. Če ne potrebuje deklaracije → set requires_declaration=FALSE in skip
    if not analysis["requires_declaration"]:
        cursor.execute(
            "UPDATE orders SET requires_declaration = FALSE WHERE order_number = %s",
            (order_number,)
        )
        result["action"] = "skipped"
        result["reason"] = "no_parfumov"
        return result

    # 3. Če blokiran → shrani razloge, NE retry-aj
    if analysis["blocked"]:
        cursor.execute(
            """
            UPDATE orders SET
                pdf_generation_blocked_reason = %s,
                pdf_generation_blocked_codes = %s,
                pdf_generation_blocked_parfumi = %s,
                pdf_generation_last_attempt_at = NOW()
            WHERE order_number = %s
            """,
            (
                "; ".join(analysis["missing"])[:2000],
                analysis["blocked_codes"],
                analysis["blocked_parfumi"],
                order_number,
            )
        )
        result["action"] = "blocked"
        result["reason"] = "; ".join(analysis["missing"])
        result["blocked_codes"] = analysis["blocked_codes"]

        # Instant alert za stara naročila (>7 dni) — kupec že čaka
        try:
            created = order_data.get("created_at")
            if created and isinstance(created, datetime):
                age = datetime.now(tz=created.tzinfo or timezone.utc) - created
            elif created:
                age = timedelta(days=999)  # neznano staro - tretiramo kot urgentno
            else:
                age = timedelta(days=0)

            if age > timedelta(days=7) and not order_data.get("critical_alert_sent_at"):
                try:
                    from services.email_service import poslji_safety_net_instant_alert
                    sent = poslji_safety_net_instant_alert(order_data, analysis)
                    if sent:
                        cursor.execute(
                            "UPDATE orders SET critical_alert_sent_at = NOW() WHERE order_number = %s",
                            (order_number,)
                        )
                        logger.info("Sent instant safety net alert for %s", order_number)
                except Exception as e:
                    logger.warning("Failed to send instant alert for %s: %s", order_number, e)
        except Exception as e:
            logger.warning("Age check failed for %s: %s", order_number, e)

        return result

    # 3b. PDF batch ob 21:00 — ne generiraj PDF-ja za današnja fulfilled naročila prej
    wait_batch, wait_reason = should_wait_for_2100_pdf_batch(order_data)
    if wait_batch:
        result["action"] = "waiting_2100_batch"
        result["reason"] = wait_reason
        return result

    # 4. PDF se da tvoriti — shrani declarations v DB
    try:
        from blueprints.api_routes import _shrani_deklaracijo_v_bazo
        from services.pdf_service import generate_declaration_pdf
        from services.mk_service import mk_attach_declaration_for_order

        ok = _shrani_deklaracijo_v_bazo(order_number, analysis["declaration_items"], cursor)
        if not ok:
            result["action"] = "error"
            result["reason"] = "save_declaration_failed"
            return result

        # 5. Tvori PDF (pdf_service prebere iz declarations tabele)
        pdf_path = generate_declaration_pdf(order_number)
        if not pdf_path or not os.path.isfile(pdf_path):
            result["action"] = "error"
            result["reason"] = "pdf_generation_failed"
            return result

        # 6. Resetiraj morebitne stare block flags (zdaj OK)
        cursor.execute(
            """
            UPDATE orders SET
                pdf_generation_blocked_reason = NULL,
                pdf_generation_blocked_codes = NULL,
                pdf_generation_blocked_parfumi = NULL,
                pdf_generation_last_attempt_at = NOW(),
                critical_alert_sent_at = NULL
            WHERE order_number = %s
            """,
            (order_number,)
        )

        # 7. Pridobi/poišči mk_sales_order_id (priponka MORA iti na sales_order,
        #    da MK sproži Mandrill trigger; sales_bill ne sprozi tega trigger-ja).
        mk_sales_order_id = order_data.get("mk_sales_order_id")
        if not mk_sales_order_id:
            logger.info("Searching mk_sales_order_id for %s (not cached)...", order_number)
            mk_sales_order_id = mk_find_and_cache_sales_order_id(order_number, cursor)
            if mk_sales_order_id:
                logger.info("Found and cached mk_sales_order_id=%s for %s",
                            mk_sales_order_id, order_number)

        # 8. Naloži v MK na sales_order (key change: MORA biti sales_order)
        attach = mk_attach_declaration_for_order(
            order_number,
            shopify_order_id=order_data.get("shopify_order_id"),
            mk_bill_id=order_data.get("mk_bill_id"),
            mk_bill_type=order_data.get("mk_bill_type"),
            mk_sales_order_id=mk_sales_order_id,
        )
        if not attach.get("success"):
            result["action"] = "error"
            result["reason"] = f"mk_attach_failed: {attach.get('error')}"
            return result

        # Mark MK upload done
        cursor.execute(
            "UPDATE orders SET mk_decl_uploaded_at = NOW() WHERE order_number = %s",
            (order_number,)
        )

        # Določi, na kateri doc_type je bila priponka dejansko naložena.
        # Če smo naložili na sales_bill (ker sales_order ni bil najden), MK
        # Mandrill trigger se NE bo sprožil — gremo direktno na Mandrill API.
        attached_to_sales_order = (attach.get("doc_type") == "sales_order")

        # 9. Preveri MK status z novo klasifikacijo
        mk_status_full = mk_check_sales_order_status_full(mk_sales_order_id)
        mk_category = classify_mk_status(
            mk_status_full.get("status_desc"), mk_status_full.get("status_code")
        )

        # Posnemi zadnji znan MK status
        cursor.execute(
            """
            UPDATE orders SET
                mk_last_status_desc = %s,
                mk_last_status_code = %s,
                mk_last_status_at   = NOW()
            WHERE order_number = %s
            """,
            (mk_status_full.get("status_desc"), mk_status_full.get("status_code"), order_number)
        )

        # EDGE CASE: naročilo je med upload-om prešlo v "Vračilo paketa".
        # Ne pošljemo Mandrill (paket se vrača nazaj).
        if mk_category == "returned":
            cursor.execute(
                """
                UPDATE orders SET
                    mk_return_detected_at = COALESCE(mk_return_detected_at, NOW())
                WHERE order_number = %s
                """,
                (order_number,)
            )
            result["action"] = "returned"
            result["reason"] = (
                f"MK status med upload-om: {mk_status_full.get('status_code')} "
                f"— paket se vrača, Mandrill se ne pošlje"
            )
            return result

        # Direkten Mandrill send je potreben SAMO če JE MK status 'completed'.
        # (Po dogovoru 2026-05-26: pošljemo deklaracijo SAMO ko je naročilo
        # zaključeno v MK — tj. dostavljeno + plačano.)
        # Edge case: če priponka ni bila naložena na sales_order (samo na
        # sales_bill kjer MK trigger ne deluje), pošljemo direktno tudi takrat,
        # vendar SAMO če je status completed.
        is_completed = (mk_category == "completed")

        if not is_completed:
            # Vse drugo (shipped / pending / unknown) → čakamo
            result["action"] = "uploaded_mk_only"
            result["reason"] = (
                f"mk_status={mk_status_full.get('status_code') or mk_status_full.get('status_desc') or 'unknown'} "
                f"(category={mk_category}), attached_to={attach.get('doc_type')} "
                f"— čakamo, da MK preide v 'Zaključeno'"
            )
            return result

        # 10–11. Pošlji prek Mandrill (primarno); SMTP samo ob neuspehu (env).
        line_items = _parse_line_items(order_data)
        send_res = send_declaration_email(
            order_data,
            pdf_path,
            analysis["declaration_items"],
            line_items,
            cursor,
            allow_smtp_fallback=True,
        )
        if send_res.get("success"):
            result["mandrill_message_id"] = send_res.get("message_id")
            result["mandrill_template"] = send_res.get("template")
            mk_status = mk_status_full.get("status_code") or mk_status_full.get("status_desc")
            channel = send_res.get("channel", "mandrill")
            if send_res.get("action") in ("already_sent", "sent_externally"):
                result["action"] = "uploaded_mk_only"
            elif channel == "smtp":
                result["action"] = "uploaded_and_mandrill"
            else:
                result["action"] = "uploaded_and_mandrill"
            result["reason"] = (
                f"mk_status={mk_status or 'unknown'}, attached_to={attach.get('doc_type')} "
                f"→ {channel} ({send_res.get('reason')})"
            )
            return result

        result["action"] = "error"
        result["reason"] = send_res.get("reason", "send_failed")
        return result

    except Exception as e:
        logger.exception("process_one failed for %s", order_number)
        result["action"] = "error"
        result["reason"] = f"unexpected: {e}"
        return result


# ---------------------------------------------------------------------------
# Cron entry points
# ---------------------------------------------------------------------------

def run_safety_net_job(window_days: int = 7, batch_limit: int = 200) -> Dict[str, Any]:
    """Glavni cron job: za vsa nedavna fulfilled naročila zagotovi, da je
    deklaracija (a) naložena v MK in (b) poslana kupcu prek Mandrilla.

    Po dogovoru z uporabnikom (2026-05-26): NAŠA APP je primary sender
    deklaracij. MK Mandrill trigger ostane vklopljen kot backup; idempotency
    check (mandrill_safety_message_id + Mandrill log search) prepreči duplikate.

    Kandidati:
      - requires_declaration = TRUE
      - pdf_generation_blocked_reason IS NULL (sveže ali invalidirano)
      - shopify_fulfilled_at IS NOT NULL OR fulfilled_at IS NOT NULL
      - created_at > NOW() - window_days
      - Mandrill ŠE NI poslal: mandrill_safety_message_id IS NULL
        (lahko: mk_decl_uploaded_at NOT NULL ampak mi ne vemo, ali je MK
         dejansko poslal — process_one preveri Mandrill log za potrditev)

    Args:
        window_days: koliko dni nazaj scan-amo (default 7; safety net hourly
            cron uporablja 14 da pokrije tudi zamujena naročila)
        batch_limit: max naročil v enem zagonu
    """
    db = get_db()
    cursor = db.cursor()

    stats = {
        "scanned": 0,
        "skipped_no_parfumov": 0,
        "blocked": 0,
        "uploaded_mk_only": 0,
        "uploaded_and_mandrill": 0,
        "returned": 0,
        "errors": 0,
        "details": [],
    }

    try:
        cursor.execute(
            """
            SELECT *
              FROM orders
             WHERE requires_declaration = TRUE
               AND pdf_generation_blocked_reason IS NULL
               AND mandrill_safety_message_id IS NULL
               AND mk_return_detected_at IS NULL
               AND (shopify_fulfilled_at IS NOT NULL OR fulfilled_at IS NOT NULL)
               AND created_at > NOW() - (%s || ' days')::interval
             ORDER BY shopify_fulfilled_at DESC NULLS LAST, fulfilled_at DESC NULLS LAST, created_at DESC
             LIMIT %s
            """,
            (window_days, batch_limit)
        )
        rows = cursor.fetchall()

        for row in rows:
            order_data = dict(row) if not isinstance(row, dict) else row
            stats["scanned"] += 1
            try:
                r = process_one(order_data, cursor)
                action = r.get("action", "error")
                if action == "skipped":
                    stats["skipped_no_parfumov"] += 1
                elif action == "blocked":
                    stats["blocked"] += 1
                elif action == "uploaded_mk_only":
                    stats["uploaded_mk_only"] += 1
                elif action == "uploaded_and_mandrill":
                    stats["uploaded_and_mandrill"] += 1
                elif action == "returned":
                    stats["returned"] += 1
                else:
                    stats["errors"] += 1
                stats["details"].append(r)
                db.commit()
            except Exception as e:
                logger.exception("Job error on order %s", order_data.get("order_number"))
                stats["errors"] += 1
                db.rollback()
    finally:
        cursor.close()

    logger.info("Safety net job done: %s", {k: v for k, v in stats.items() if k != "details"})
    return stats


def run_backfill_blocked_orders_job(
    window_days: int = 30,
    batch_limit: int = 200,
    only_with_codes: Optional[List[str]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Ad-hoc backfill: re-procesira naročila, ki so bila prej blokirana
    zaradi manjkajočih master podatkov (parfumi, line items, ...).

    Tipičen use-case: zaposleni je dodal manjkajoče parfume v bazo, in zdaj
    želimo re-procesirati naročila, ki so bila pred to izboljšavo blokirana.

    Razlika od `run_safety_net_job`:
      - safety_net_job exclude-a `pdf_generation_blocked_reason IS NOT NULL`
        (ker so to po definiciji "ne moremo" orders)
      - ta backfill IZRECNO loveč te, da preveri, ali je problem rešen

    Args:
        window_days: koliko dni nazaj iščemo blokirana naročila (default 30)
        batch_limit: max naročil v enem klicu
        only_with_codes: če podan, vključi samo naročila, ki imajo
            VSAJ ENO od teh code-ov v `pdf_generation_blocked_codes`.
            Primer: ['CODE_PARFUM_MISSING_DATA'] — če smo dodali manjkajoče parfume.
        dry_run: če True, samo prešteje kandidate brez procesiranja

    Returns:
        stats dict (scanned, resolved, still_blocked, uploaded_mk_only,
        uploaded_and_mandrill, errors, details)
    """
    db = get_db()
    cursor = db.cursor()

    stats: Dict[str, Any] = {
        "dry_run": dry_run,
        "window_days": window_days,
        "candidates": 0,
        "scanned": 0,
        "still_blocked": 0,
        "uploaded_mk_only": 0,
        "uploaded_and_mandrill": 0,
        "skipped_no_parfumov": 0,
        "returned": 0,
        "errors": 0,
        "details": [],
    }

    try:
        # Najdi kandidate
        query = """
            SELECT * FROM orders
            WHERE requires_declaration = TRUE
              AND pdf_generation_blocked_reason IS NOT NULL
              AND mandrill_safety_message_id IS NULL
              AND mk_return_detected_at IS NULL
              AND (shopify_fulfilled_at IS NOT NULL OR fulfilled_at IS NOT NULL)
              AND created_at > NOW() - (%s || ' days')::interval
        """
        params: List[Any] = [window_days]

        if only_with_codes:
            # PostgreSQL ARRAY overlap (zahteva, da je en code v intersekciji)
            query += " AND pdf_generation_blocked_codes && %s::text[]"
            params.append(only_with_codes)

        query += " ORDER BY created_at ASC LIMIT %s"
        params.append(batch_limit)

        cursor.execute(query, tuple(params))
        candidates = cursor.fetchall()
        stats["candidates"] = len(candidates)

        if dry_run:
            stats["details"] = [
                {
                    "order_number": (dict(r) if not isinstance(r, dict) else r).get("order_number"),
                    "blocked_codes": (dict(r) if not isinstance(r, dict) else r).get(
                        "pdf_generation_blocked_codes"
                    ),
                    "blocked_reason": (dict(r) if not isinstance(r, dict) else r).get(
                        "pdf_generation_blocked_reason"
                    ),
                }
                for r in candidates
            ]
            return stats

        # Pred re-procesiranjem počistimo blocked_* polja, da process_one
        # zazna kot "fresh" in poskusi PDF tvoriti.
        for row in candidates:
            order_data = dict(row) if not isinstance(row, dict) else row
            order_number = order_data.get("order_number")
            stats["scanned"] += 1

            try:
                # Reset blocked metadata pred poskusom
                cursor.execute(
                    """
                    UPDATE orders SET
                        pdf_generation_blocked_reason = NULL,
                        pdf_generation_blocked_codes = NULL,
                        pdf_generation_blocked_parfumi = NULL
                    WHERE order_number = %s
                    """,
                    (order_number,)
                )
                # Process
                r = process_one(order_data, cursor)
                action = r.get("action", "error")
                if action == "blocked":
                    stats["still_blocked"] += 1
                elif action == "uploaded_mk_only":
                    stats["uploaded_mk_only"] += 1
                elif action == "uploaded_and_mandrill":
                    stats["uploaded_and_mandrill"] += 1
                elif action == "skipped":
                    stats["skipped_no_parfumov"] += 1
                elif action == "returned":
                    stats["returned"] += 1
                else:
                    stats["errors"] += 1
                stats["details"].append({
                    "order_number": order_number,
                    "action": action,
                    "reason": r.get("reason", ""),
                })
                db.commit()
            except Exception as e:
                logger.exception(
                    "Backfill error on order %s", order_number
                )
                stats["errors"] += 1
                db.rollback()
                stats["details"].append({
                    "order_number": order_number,
                    "action": "error",
                    "reason": str(e)[:200],
                })

    except Exception as e:
        logger.exception("run_backfill_blocked_orders_job failed")
        db.rollback()
        stats["errors"] += 1
    finally:
        try:
            cursor.close()
        except Exception:
            pass

    return stats


def run_mandrill_log_audit_job(days_back: int = 10, batch_limit: int = 100) -> Dict[str, Any]:
    """Layer 2: Scan Mandrill log za naročila, ki "izgledajo OK" ampak NISO bila poslana.

    Cilj:
      - V Flasku misli, da je mk_decl_uploaded_at NOT NULL → upload OK
      - V resnici je MK Mandrill trigger pobegnil zaradi manjkajoče priponke
        (ker je Flask priponko dal na sales_bill_*, ne sales_order)
      - Mandrill log NIMA send-a za to naročilo
      - Stranka ni dobila deklaracije

    Algoritem:
      1. Pridobi Mandrill log za zadnjih `days_back` dni (template=deklaracije-si)
         in iz `metadata.order_id` ali `email + ts` izvleci že-poslana naročila.
      2. Pridobi DB kandidate (mk_decl_uploaded_at NOT NULL,
         mandrill_safety_message_id IS NULL, created_at v 14 dneh, fulfilled).
      3. Za vsakega, ki ni v Mandrill log set-u, sproži safety net process.

    Pomembno: ta job sproži samo `mark_missing_mandrill`, ne pa direktnega send-a.
    Send opravi `run_safety_net_job` naslednji cikel. Ločitev za varnost.

    Args:
        days_back: koliko dni nazaj scan-amo (Mandrill log retention je ~30d)
        batch_limit: max DB kandidatov, ki jih obdelamo v enem klicu

    Returns: stats dict
    """
    db = get_db()
    cursor = db.cursor()

    stats = {
        "mandrill_msgs_scanned": 0,
        "db_candidates": 0,
        "mandrill_known_sent": 0,
        "mandrill_rejected": 0,  # Layer 2b: explicit Mandrill rejections
        "candidates_missing_mandrill": 0,
        "marked_for_safety_net": 0,
        "errors": 0,
        "details": [],
        "rejected_details": [],  # explicit "rejected"/"invalid" iz Mandrill
    }

    try:
        # Step 1: pull Mandrill log
        from datetime import timedelta as _td
        date_from = (datetime.now() - _td(days=days_back)).strftime("%Y-%m-%d")
        date_to = (datetime.now() + _td(days=1)).strftime("%Y-%m-%d")

        # Hranimo po-template mape, ker je SAMI SI MK-jev "default" za vse
        # kupce; kupcu v DE/AT/HR/... velja "že poslano" le, če je bil
        # poslan ustrezen jezikovni template (`deklaracije-de`, ...).
        sent_order_ids_by_template: Dict[str, set] = {}
        sent_emails_ts_by_template: Dict[str, List[Tuple[str, int]]] = {}
        # Layer 2b: eksplicitni Mandrill rejection-i (npr. "Attachment is required,
        # mail skipped" iz MK trigger-ja). Te moramo aktivno re-sendati, ker
        # Mandrill pove jasno: ta email NI bil poslan.
        REJECTED_STATES = {"rejected", "invalid"}
        rejected_records: List[Dict[str, Any]] = []

        try:
            from services import mandrill_service as mc
            # Široko iskanje: ne filtriramo po senderju, ker MK uporablja
            # drugačno sender adreso od naše app. Filtriramo po template-u
            # v Python-u spodaj (deklaracije-*).
            # Iteriraj v paginih (Mandrill default limit ~1000)
            for page_start in range(0, 5):  # max 5000 zapisov
                msgs = mc.messages_search(
                    query="subject:deklaracij OR template:deklaracije",
                    date_from=date_from, date_to=date_to, limit=1000,
                )
                if not msgs:
                    break
                for m in msgs:
                    template = (m.get("template") or "").lower().strip()
                    subj = (m.get("subject") or "").lower()
                    if "deklaracije" not in template and "deklaracij" not in subj:
                        continue
                    stats["mandrill_msgs_scanned"] += 1
                    state = (m.get("state") or "").lower().strip()
                    # Normaliziraj template slug (npr. 'deklaracije-si').
                    tpl_key = template or "deklaracije-unknown"
                    md = m.get("metadata") or {}
                    oid = str(md.get("order_id") or "").lstrip("#").strip()
                    email = (m.get("email") or "").lower()
                    ts = m.get("ts") or 0

                    if state in REJECTED_STATES:
                        # Mandrill je zavrnil send — to je False positive!
                        # Beležimo za alert in retry.
                        stats["mandrill_rejected"] += 1
                        rejected_records.append({
                            "order_id": oid,
                            "email": email,
                            "ts": int(ts) if ts else 0,
                            "state": state,
                            "template": tpl_key,
                            "reject_reason": m.get("reject_reason") or "",
                            "subject": m.get("subject") or "",
                            "_id": m.get("_id") or "",
                        })
                        # Ne dodajamo v sent_* mape — to je smisel rejected
                        continue

                    if oid:
                        sent_order_ids_by_template.setdefault(tpl_key, set()).add(oid)
                    if email and ts:
                        sent_emails_ts_by_template.setdefault(tpl_key, []).append(
                            (email, int(ts))
                        )
                if len(msgs) < 1000:
                    break
        except Exception as e:
            logger.exception("Mandrill bulk pull failed: %s", e)
            stats["errors"] += 1
            return stats

        # Layer 2b: za vsak rejected message → marker za safety net retry.
        # Tako stranke s "Attachment is required" napako dobijo PDF preko naše
        # poti (smart retry).
        for rec in rejected_records:
            oid = rec.get("order_id") or ""
            if not oid:
                # Brez order_id ne moremo zanesljivo matchat → samo loggamo
                logger.warning(
                    "Mandrill rejected message (no order_id metadata): "
                    "email=%s state=%s reason=%s _id=%s",
                    rec.get("email"), rec.get("state"),
                    rec.get("reject_reason"), rec.get("_id"),
                )
                stats["rejected_details"].append(rec)
                continue
            try:
                # Zazri po čistem in #-prefiksanem order_number
                cursor.execute(
                    """
                    UPDATE orders SET
                        mk_decl_upload_checked_at = COALESCE(mk_decl_upload_checked_at, mk_decl_uploaded_at, NOW()),
                        mk_decl_uploaded_at = NULL,
                        mandrill_safety_status = 'mk_rejected_attachment',
                        pdf_generation_blocked_reason = NULL,
                        pdf_generation_blocked_codes = NULL,
                        pdf_generation_blocked_parfumi = NULL
                      WHERE (order_number = %s OR order_number = %s)
                        AND mandrill_safety_message_id IS NULL
                    """,
                    (oid, f"#{oid}")
                )
                if cursor.rowcount > 0:
                    stats["rejected_details"].append({
                        **rec,
                        "action": "marked_for_retry",
                        "rows_updated": cursor.rowcount,
                    })
                    logger.warning(
                        "Mandrill REJECTED %s (%s, reason=%s) → marked for safety net retry",
                        oid, rec.get("state"), rec.get("reject_reason"),
                    )
                else:
                    stats["rejected_details"].append({
                        **rec,
                        "action": "already_sent_or_not_found",
                    })
            except Exception as e:
                logger.warning("Failed to mark rejected %s for retry: %s", oid, e)
                stats["errors"] += 1

        stats["mandrill_known_sent"] = sum(
            len(s) for s in sent_order_ids_by_template.values()
        ) + sum(len(s) for s in sent_emails_ts_by_template.values())

        # Step 2: DB kandidati
        cursor.execute(
            """
            SELECT id, order_number, customer_email, country_code, fulfilled_at,
                   shopify_fulfilled_at, mk_decl_uploaded_at
              FROM orders
             WHERE requires_declaration = TRUE
               AND mk_decl_uploaded_at IS NOT NULL
               AND mandrill_safety_message_id IS NULL
               AND created_at > NOW() - (%s || ' days')::interval
               AND (shopify_fulfilled_at IS NOT NULL OR fulfilled_at IS NOT NULL)
             ORDER BY created_at DESC
             LIMIT %s
            """,
            (days_back, batch_limit)
        )
        candidates = cursor.fetchall()
        stats["db_candidates"] = len(candidates)

        # Step 3: identify missing — match po **jezikovno ustreznem** template-u
        for row in candidates:
            d = dict(row) if not isinstance(row, dict) else row
            order_no_clean = str(d["order_number"] or "").lstrip("#").strip()
            email = (d.get("customer_email") or "").lower()

            # Target template glede na državo kupca (npr. AT → deklaracije-de).
            target_tpl_name = pick_declaration_template_name(d.get("country_code"))
            target_tpl_slug = target_tpl_name.replace("_", "-")

            # Match by order_id v PRAVEM jeziku
            if order_no_clean in sent_order_ids_by_template.get(target_tpl_slug, set()):
                continue

            # Fallback: match po email + ts window (within 7d of fulfillment),
            # spet le v jezikovno ustreznem template-u
            fulfilled = d.get("shopify_fulfilled_at") or d.get("fulfilled_at")
            matched_by_email = False
            if email and fulfilled:
                try:
                    f_ts = int(fulfilled.timestamp()) if hasattr(fulfilled, "timestamp") else 0
                    for (m_email, m_ts) in sent_emails_ts_by_template.get(target_tpl_slug, []):
                        if m_email == email and abs(m_ts - f_ts) < 7 * 86400:
                            matched_by_email = True
                            break
                except Exception:
                    pass
            if matched_by_email:
                continue

            # Candidate is missing in Mandrill log
            stats["candidates_missing_mandrill"] += 1
            stats["details"].append({
                "order_number": d["order_number"],
                "email": email,
                "mk_decl_uploaded_at": str(d.get("mk_decl_uploaded_at")),
            })

            # Mark for safety net: reset mk_decl_uploaded_at so safety_net_job
            # will pick this order on next run (and send Mandrill directly).
            # Pomembno: ohranimo zgodovino z mk_decl_upload_checked_at.
            try:
                cursor.execute(
                    """
                    UPDATE orders SET
                        mk_decl_upload_checked_at = COALESCE(mk_decl_upload_checked_at, mk_decl_uploaded_at),
                        mk_decl_uploaded_at = NULL,
                        pdf_generation_blocked_reason = NULL,
                        pdf_generation_blocked_codes = NULL,
                        pdf_generation_blocked_parfumi = NULL
                      WHERE id = %s
                    """,
                    (d["id"],)
                )
                stats["marked_for_safety_net"] += 1
            except Exception as e:
                logger.warning("Failed to mark %s for safety net: %s",
                               d.get("order_number"), e)
                stats["errors"] += 1

        db.commit()
    except Exception as e:
        logger.exception("run_mandrill_log_audit_job failed")
        db.rollback()
        stats["errors"] += 1
    finally:
        cursor.close()

    logger.info("Mandrill audit job done: %s",
                {k: v for k, v in stats.items() if k != "details"})
    return stats


def run_mandrill_verify_job() -> Dict[str, Any]:
    """Vsako uro: preveri status nedavnih Mandrill safety sends.

    Pogleda naročila, kjer:
      - mandrill_safety_message_id IS NOT NULL
      - mandrill_safety_status NOT IN ('sent', 'delivered', 'opened', 'clicked')
        OR mandrill_safety_status IS NULL
      - mandrill_safety_attempted_at < NOW() - 15 minut (dovolj časa za Mandrill)
      - mandrill_safety_attempted_at > NOW() - 7 days
    """
    from services import mandrill_service as mc
    db = get_db()
    cursor = db.cursor()

    stats = {"checked": 0, "updated": 0, "failures": 0, "alerts": 0, "details": []}
    try:
        cursor.execute(
            """
            SELECT id, order_number, customer_email, mandrill_safety_message_id, mandrill_safety_status
              FROM orders
             WHERE mandrill_safety_message_id IS NOT NULL
               AND (mandrill_safety_status IS NULL
                    OR mandrill_safety_status NOT IN ('sent','delivered','opened','clicked'))
               AND mandrill_safety_attempted_at < NOW() - INTERVAL '15 minutes'
               AND mandrill_safety_attempted_at > NOW() - INTERVAL '7 days'
            """
        )
        rows = cursor.fetchall()
        for row in rows:
            d = dict(row) if not isinstance(row, dict) else row
            stats["checked"] += 1
            mid = d.get("mandrill_safety_message_id")
            old_status = d.get("mandrill_safety_status")
            try:
                info = mc.messages_info(mid)
                new_state = (info or {}).get("state") or "unknown"
                if new_state != old_status:
                    cursor.execute(
                        "UPDATE orders SET mandrill_safety_status = %s WHERE id = %s",
                        (new_state, d["id"])
                    )
                    stats["updated"] += 1
                if mc.is_failure_status(new_state):
                    stats["failures"] += 1
                    stats["details"].append({
                        "order_number": d.get("order_number"),
                        "email": d.get("customer_email"),
                        "state": new_state,
                        "info": info,
                    })
                db.commit()
            except Exception as e:
                logger.warning("messages_info failed for order %s (mid=%s): %s",
                               d.get("order_number"), mid, e)
                db.rollback()
    finally:
        cursor.close()

    logger.info("Mandrill verify job done: %s", {k: v for k, v in stats.items() if k != "details"})
    return stats


# ---------------------------------------------------------------------------
# Smart invalidation hooks
# ---------------------------------------------------------------------------

def invalidate_blocks_for_parfum(parfum_id: int, codes: Optional[List[str]] = None) -> int:
    """Sprosti block flags za vsa naročila, povezana s tem parfumom.

    Klikni iz UI / API, ko admin:
      - vnese novo serijo (code='expired_serije')
      - posodobi INCI v DB (code='missing_inci' / 'parfum_not_in_db')

    Returns: število naročil, ki so bili invalidirana.
    """
    db = get_db()
    cursor = db.cursor()
    try:
        if codes:
            cursor.execute(
                """
                UPDATE orders SET
                    pdf_generation_blocked_reason = NULL,
                    pdf_generation_blocked_codes = NULL,
                    pdf_generation_blocked_parfumi = NULL
                  WHERE %s = ANY(pdf_generation_blocked_parfumi)
                    AND pdf_generation_blocked_codes && %s
                """,
                (parfum_id, codes)
            )
        else:
            cursor.execute(
                """
                UPDATE orders SET
                    pdf_generation_blocked_reason = NULL,
                    pdf_generation_blocked_codes = NULL,
                    pdf_generation_blocked_parfumi = NULL
                  WHERE %s = ANY(pdf_generation_blocked_parfumi)
                """,
                (parfum_id,)
            )
        n = cursor.rowcount
        db.commit()
        logger.info("invalidate_blocks_for_parfum(%s, codes=%s): %d orders unblocked",
                    parfum_id, codes, n)
        return n
    except Exception as e:
        logger.exception("invalidate_blocks_for_parfum failed: %s", e)
        db.rollback()
        return 0
    finally:
        cursor.close()


def invalidate_blocks_for_shopify_product(product_no: str, proizvajalec_ime: str) -> int:
    """Ko pride Shopify products/update webhook, najdi prizadeta naročila.

    Vsa naročila, ki so blokirana z 'missing_metafields' ali 'parfum_not_in_db'
    in vsebujejo ta produkt, se invalidirajo (next cron jih retry-a).
    """
    db = get_db()
    cursor = db.cursor()
    try:
        # Resolve parfum_id iz DB
        cursor.execute(
            "SELECT p.id FROM parfumi p "
            "JOIN proizvajalci pr ON p.proizvajalec_id = pr.id "
            "WHERE p.product_no = %s AND UPPER(pr.ime) = %s",
            (product_no, (proizvajalec_ime or "").upper())
        )
        row = cursor.fetchone()
        if not row:
            return 0
        parfum_id = row[0] if not isinstance(row, dict) else row["id"]
        return invalidate_blocks_for_parfum(parfum_id)
    finally:
        cursor.close()
