def list_bill_ids_from_cash_journal(date_from_iso: str, date_to_iso: str, limit: int = 100, offset: int = 0) -> tuple[list[str], dict]:
    """Harvest bill mk_ids from cash register journal via ESHOP /search (doc_type='cash_register_journal')."""
    payload = {
        "doc_type": "cash_register_journal",
        "result_type": "doc",
        "limit": max(1, min(100, int(limit))),
        "offset": int(offset),
        "date_from": str(date_from_iso)[:10],
        "date_to": str(date_to_iso)[:10],
        "order_by": "date",
        "order": "desc",
    }
    dj = _http_post("/search", payload)
    ids: list[str] = []
    rows = dj if isinstance(dj, list) else (dj.get('result') or dj.get('rows') or dj.get('documents') or [])
    for rr in rows or []:
        sid = (
            (rr.get('bill_mk_id') if isinstance(rr, dict) else None)
            or (rr.get('document_mk_id') if isinstance(rr, dict) else None)
            or (((rr.get('linked_document') or {}) if isinstance(rr, dict) else {}).get('mk_id'))
            or (rr.get('mk_id') if isinstance(rr, dict) else None)
            or (rr.get('id') if isinstance(rr, dict) else None)
        )
        if sid:
            try:
                ids.append(str(sid))
            except Exception:
                pass
    meta = {
        'count': (dj.get('result_count') if isinstance(dj, dict) else None) or len(ids),
        'offset': offset,
        'limit': max(1, min(100, int(limit))),
    }
    try:
        current_app.logger.info({"evt": "cash_journal_window", "from": str(date_from_iso), "to": str(date_to_iso), "off": offset, "lim": limit, "sample": ids[:10]})
    except Exception:
        pass
    return ids, meta
import os
import time
import base64
import requests
import re
import unicodedata
from typing import Optional, Dict, Any, Iterable, List, Tuple

# Minimal self-test helpers for is_retail_bill
def _test_is_retail_bill() -> None:
    """Lightweight checks for is_retail_bill logic."""
    sample1 = {
        'mk_id': '123',
        'bill_type': 'sales_bill_retail',
        'document_info': {'is_retail': False}
    }
    sample2 = {
        'mk_id': '124',
        'furs_zoi': 'ABCDEF',
        'document_info': {}
    }
    assert is_retail_bill(sample1) is True, 'Expected True due to bill_type retail'
    assert is_retail_bill(sample2) is True, 'Expected True due to furs_zoi'
from datetime import datetime, timedelta, timezone
import json as _json
from flask import current_app
from database import get_db
# Config for retail search
DOC_TYPES_RETAIL_SEARCH = (
    os.getenv("MK_RETAIL_DOC_TYPES", "sales_bill_retail").replace(" ", "").split(",")
)
MAX_PAGE_SIZE = 100
# Panic switch to import all bills ignoring retail filter (default false: retail filter enforced)
IMPORT_ALL_BILLS_IGNORE_RETAIL = os.getenv("IMPORT_ALL_BILLS_IGNORE_RETAIL", "false").strip().lower() == "true"

# === Presentation policy (what Global Actions should SHOW) ===
# Modes:
#  - retail_only (default): show only bills detected as retail via `is_retail_bill` OR doc_type in MK_PRESENT_DOC_TYPES
#  - doc_types:            show only bills whose doc_type is in MK_PRESENT_DOC_TYPES
#  - all:                  show everything
MK_PRESENT_MODE = os.getenv("MK_PRESENT_MODE", "retail_only").strip().lower()
MK_PRESENT_DOC_TYPES = [
    t.strip() for t in (os.getenv("MK_PRESENT_DOC_TYPES", "sales_bill_retail").split(",")) if t.strip()
]

def should_present_bill(doc: dict) -> bool:
    """Return True if a bill should be shown in Global Actions UI per presentation policy.
    - retail_only: use `is_retail_bill(doc)` OR doc_type in MK_PRESENT_DOC_TYPES
    - doc_types:   only doc_type in MK_PRESENT_DOC_TYPES
    - all:         always True
    """
    try:
        mode = MK_PRESENT_MODE
        dt = (doc.get("doc_type") or doc.get("document_type") or "").strip()
        if mode == "all":
            return True
        if mode == "doc_types":
            return dt in MK_PRESENT_DOC_TYPES
        # retail_only (default)
        if dt in MK_PRESENT_DOC_TYPES:
            return True
        return is_retail_bill(doc)
    except Exception:
        # Be conservative: hide on error when not in 'all'
        return MK_PRESENT_MODE == "all"

def filter_bills_for_presentation(bills: list[dict]) -> list[dict]:
    """Filter a list of bill dicts for UI display according to presentation policy."""
    try:
        return [b for b in bills if should_present_bill(b)]
    except Exception:
        return bills if MK_PRESENT_MODE == "all" else []

def _panic_import_all() -> bool:
    try:
        # Allow runtime override via Flask config
        v = current_app.config.get('IMPORT_ALL_BILLS_IGNORE_RETAIL')
        if isinstance(v, bool):
            return v
    except Exception:
        pass
    return IMPORT_ALL_BILLS_IGNORE_RETAIL


# --- ESHOP retail helpers (strict) ---
def _mk_base_url() -> str:
    base_callable = globals().get("_mk_base", None)
    if callable(base_callable):
        try:
            return base_callable()  # type: ignore[misc]
        except Exception:
            pass
    return (
        globals().get("_mk_base")  # type: ignore[return-value]
        or os.getenv("MK_API_BASE")
        or "https://main.metakocka.si/rest/eshop/v1"
    )


def _with_auth(payload: dict) -> dict:
    company_id = os.getenv("MK_COMPANY_ID")
    secret = os.getenv("MK_API_KEY") or os.getenv("MK_SECRET_KEY")
    return {**payload, "company_id": company_id, "secret": secret, "secret_key": secret}


def _http_post(path: str, payload: dict) -> dict:
    base = _mk_base_url()
    url = base.rstrip("/") + path
    r = requests.post(url, json=_with_auth(payload), timeout=45)
    r.raise_for_status()
    data = r.json()
    try:
        oc = int(data.get("opr_code", 0)) if isinstance(data, dict) and "opr_code" in data else 0
    except Exception:
        oc = 0
    if oc and oc > 0:
        raise RuntimeError(f"MK error {oc}: {data.get('opr_desc')}")
    return data


def _http_post_document(path: str, payload: dict) -> dict:
    base = _mk_document_base()
    url = base.rstrip("/") + path
    r = requests.post(url, json=_with_auth(payload), timeout=45)
    r.raise_for_status()
    data = r.json()
    try:
        oc = int(data.get("opr_code", 0)) if isinstance(data, dict) and "opr_code" in data else 0
    except Exception:
        oc = 0
    if oc and oc > 0:
        raise RuntimeError(f"MK error {oc}: {data.get('opr_desc')}")
    return data


def _flatten_to_dict(x, max_steps: int = 12):
    obj = x
    for _ in range(max_steps):
        if isinstance(obj, dict):
            if isinstance(obj.get("doc"), dict):
                obj = obj["doc"]; continue
            if isinstance(obj.get("result"), list) and obj["result"]:
                obj = obj["result"][0]; continue
            return obj
        if isinstance(obj, (list, tuple)):
            if not obj:
                return {}
            obj = obj[0]; continue
        return {}
    return obj if isinstance(obj, dict) else {}


def _bill_items(bill: dict) -> list:
    return (
        bill.get("item_list")
        or bill.get("rows")
        or bill.get("document_rows")
        or bill.get("product_list")
        or []
    )

# Publish timestamp helper (UTC-aware)
def _as_utc_publish_ts(d: dict):
    ts = d.get("publish_ts") or ((d.get("head") or {}).get("publish_ts") if isinstance(d.get("head"), dict) else None)
    from datetime import timezone as _tz
    try:
        s = str(ts).replace("Z", "+00:00")
        return _parse_iso(s)
    except Exception:
        return None


# --- Strict retail-only helpers ---
def search_retail_bills(date_from: str, date_to: str, limit: int = 100, offset: int = 0) -> list[dict]:
    """
    Retail search via ESHOP API z ekskluzivno uporabo query_advance datumskih filtrov.
    Vrednosti datumov morajo biti oblike YYYY-MM-DD+02:00.
    """
    limit = max(1, min(int(limit), 100))
    dfrom = f"{str(date_from)[:10]}+02:00"
    dto = f"{str(date_to)[:10]}+02:00"
    payload = {
        "doc_type": "sales_bill_retail",
        "result_type": "doc",
        "limit": limit,
        "offset": int(offset),
        "order_by": "publish_ts",
        "order": "desc",
        "query_advance": [
            {"type": "doc_date_from", "value": dfrom},
            {"type": "doc_date_to",   "value": dto},
        ],
    }
    resp = _http_post("/search", payload)
    return resp.get("doc_list") or resp.get("docs") or resp.get("result") or []


def fetch_retail_bill(doc_id: str) -> dict:
    """Fetch a single retail bill using doc_type='sales_bill_retail' and DOC ID (not mk_id)."""
    payload = {
        "doc_type": "sales_bill_retail",
        "doc_id": str(doc_id),
        "return_publish_ts": True,
        "return_status_desc": True,
        "return_method_of_payment": True,
        "return_document_info": True,
        "return_product_compound": True,
        "return_allocated_cost_list": True,
        "show_tax_factor": True,
    }
    raw = _http_post("/get_document", payload)
    bill = _flatten_to_dict(raw)
    if not isinstance(bill, dict):
        raise RuntimeError("Unexpected payload for get_document (retail)")
    return bill


def import_retail_window(date_from: str, date_to: str) -> Dict[str, Any]:
    """Uvozi vse retail račune v [date_from, date_to] (YYYY-MM-DD) s paginacijo po 100 in upsertom.

    - Vedno začne z offset=0
    - Lokalno filtrira publish_ts v [date_from, date_to]
    - Upošteva anchor (MK_RETAIL_ANCHOR_TS/MK_RETAIL_ANCHOR_ID)
    - Ustavi, ko batch_min_ts < window_from (ker je order desc)
    - Vrne next_anchor_ts/next_anchor_id za naslednji zagon
    """
    logger = getattr(current_app, 'logger', None)
    total_found = 0
    fetched = 0
    fetch_calls = 0
    upserted = 0
    skipped_out_of_window = 0
    skipped_anchor = 0
    offsets = 0
    seen_ids: set[str] = set()
    in_window = 0
    early_break = False
    journal_ids = 0
    journal_processed = 0

    # Window bounds (UTC date-only)
    window_from = datetime.strptime(str(date_from)[:10], '%Y-%m-%d').date()
    window_to = datetime.strptime(str(date_to)[:10], '%Y-%m-%d').date()

    # Optional anchor
    anchor_ts = _parse_iso(os.getenv('MK_RETAIL_ANCHOR_TS') or '')
    anchor_id = os.getenv('MK_RETAIL_ANCHOR_ID') or ''

    # Force sample diagnostic
    try:
        force_sample = int(os.getenv('RETAIL_FORCE_SAMPLE', '0') or '0')
    except Exception:
        force_sample = 0

    def _newer_than_anchor(ts: Optional[datetime], mkid: Any) -> bool:
        if not anchor_ts:
            return True
        if not ts:
            return False
        if ts > anchor_ts:
            return True
        if ts == anchor_ts and str(mkid) > str(anchor_id):
            return True
        return False

    # Track next anchor (max ts/id seen)
    next_anchor_ts: Optional[datetime] = anchor_ts
    next_anchor_id: str = anchor_id

    last_batch_min_ts: Optional[datetime] = None
    last_batch_max_ts: Optional[datetime] = None

    tail_jump_done = True
    saw_in_window = False
    # --- Tail-first start fallback (initially try query_advance to get total; fallback to top-level if needed) ---
    total = 0
    try:
        resp0 = _http_post("/search", {
            "doc_type": "sales_bill_retail",
            "result_type": "doc",
            "limit": 1,
            "offset": 0,
            "order_by": "publish_ts",
            "order": "desc",
            "query_advance": [
                {"type": "doc_date_from", "value": f"{str(date_from)[:10]}+02:00"},
                {"type": "doc_date_to",   "value": f"{str(date_to)[:10]}+02:00"},
            ],
        })
        total = int(resp0.get("result_all_records") or 0)
        # if advance returns 0 total, we will rely on tail-first fallback logic below regardless
    except Exception:
        try:
            resp0 = _http_post("/search", {
                "doc_type": "sales_bill_retail",
                "result_type": "doc",
                "limit": 1,
                "offset": 0,
                "order_by": "publish_ts",
                "order": "desc",
            })
            total = int(resp0.get("result_all_records") or 0)
        except Exception:
            total = 0
    offsets = max(total - 100, 0) if total > 0 else 0
    step = -100
    try:
        if logger: logger.info({"evt": "retail_import_tail_start", "total": total, "offset": offsets})
    except Exception:
        pass

    while True:
        docs = search_retail_bills(date_from, date_to, limit=100, offset=offsets)
        count = len(docs)
        total_found += count
        try:
            if logger: logger.info({"evt": "retail_search_batch", "offset": offsets, "count": count})
        except Exception:
            pass
        if not docs:
            # Fallback: if query_advance returned nothing on first two batches, perform one page WITHOUT date filters (tail-first) and apply local filter
            if offsets in (0, max(total - 100, 0)):
                try:
                    resp_top = _http_post("/search", {
                        "doc_type": "sales_bill_retail",
                        "result_type": "doc",
                        "limit": 100,
                        "offset": int(offsets),
                        "order_by": "publish_ts",
                        "order": "desc",
                    })
                    docs = resp_top.get("doc_list") or resp_top.get("docs") or resp_top.get("result") or []
                    count = len(docs)
                    total_found += count
                except Exception:
                    docs = []
            if not docs:
                break

        # Compute min/max ts in this batch for early stop and process docs
        batch_min_ts: Optional[datetime] = None
        batch_max_ts: Optional[datetime] = None

        # Force-sample on first batch: prove get_document works without filtering/upsert
        if offsets == 0 and force_sample > 0:
            try:
                sample_ids: list[str] = []
                for d in docs:
                    mid = d.get("mk_id") or d.get("id") or ((d.get("head") or {}).get("mk_id") if isinstance(d.get("head"), dict) else None)
                    if mid:
                        sample_ids.append(str(mid))
                    if len(sample_ids) >= force_sample:
                        break
                for sid in sample_ids:
                    bill = fetch_retail_bill_strict(str(sid))
                    fetch_calls += 1
                    pub = bill.get("publish_ts") or ((bill.get("head") or {}).get("publish_ts") if isinstance(bill.get("head"), dict) else None)
                    items_len = len(bill.get("product_list") or bill.get("item_list") or bill.get("rows") or bill.get("document_rows") or [])
                    if logger:
                        logger.debug({"evt": "diag.force_fetch", "mk_id": sid, "publish_ts": pub, "items_len": items_len})
            except Exception:
                pass
        for d in docs:
            mkid = d.get("mk_id") or d.get("id") or ((d.get("head") or {}).get("mk_id") if isinstance(d.get("head"), dict) else None)
            if not mkid:
                continue
            if mkid in seen_ids:
                continue
            ts = _as_utc_publish_ts(d)
            if ts:
                ddate = ts.date()
                # update batch min
                if batch_min_ts is None or ts < batch_min_ts:
                    batch_min_ts = ts
                if batch_max_ts is None or ts > batch_max_ts:
                    batch_max_ts = ts
                # window filter
                if ddate < window_from or ddate > window_to:
                    skipped_out_of_window += 1
                    continue
                # anchor filter
                if not _newer_than_anchor(ts, mkid):
                    skipped_anchor += 1
                    continue
            else:
                # no timestamp -> skip (can't assert window)
                skipped_out_of_window += 1
                continue

            seen_ids.add(str(mkid))

            bill = fetch_retail_bill_strict(str(mkid))
            fetch_calls += 1
            fetched += 1
            # re-evaluate on full bill if header had no ts (rare)
            if not ts:
                ts = _as_utc_publish_ts(bill)
                if not ts:
                    skipped_out_of_window += 1
                    continue
                ddate = ts.date()
                if ddate < window_from or ddate > window_to or (not _newer_than_anchor(ts, mkid)):
                    skipped_out_of_window += 1
                    continue

            # mark that we found at least one within window
            saw_in_window = True
            # update next anchor
            if (not next_anchor_ts) or ts > next_anchor_ts or (ts == next_anchor_ts and str(mkid) > str(next_anchor_id)):
                next_anchor_ts = ts
                next_anchor_id = str(mkid)

            # upsert
            try:
                dry_run = False
                try:
                    dry_run = bool(current_app.config.get('DRY_RUN_IMPORTS'))
                except Exception:
                    dry_run = False
                if dry_run:
                    if logger: logger.info({"evt": "retail_would_upsert", "mk_id": mkid})
                else:
                    from database import get_db
                    db = get_db(); c = db.cursor()
                    mk_upsert_bill(c, bill)
                    try:
                        mk_upsert_bill_items(c, bill)
                    except Exception:
                        pass
                    db.commit(); c.close()
                    upserted += 1
            except Exception as e:
                try:
                    current_app.logger.error(f"retail upsert error: {e}")
                except Exception:
                    pass

        # capture batch stats for output
        last_batch_min_ts = batch_min_ts
        last_batch_max_ts = batch_max_ts

        # tail jump logic not needed; we already started from tail

        # early stop if we've reached older than window start (only after we have seen at least one in-window doc)
        if saw_in_window and batch_min_ts and batch_min_ts.date() < window_from:
            early_break = True
            offsets = -1  # sentinel to end after increment logic

        # advance offset in chosen direction
        offsets = offsets + step
        if offsets < 0:
            break

    stats = {
        "window_from": str(date_from)[:10],
        "window_to": str(date_to)[:10],
        "found_docs": total_found,
        "unique_ids": len(seen_ids),
        "fetched_docs": fetched,
        "upserted": upserted,
        "skipped_out_of_window": skipped_out_of_window,
        "next_anchor_ts": (next_anchor_ts.isoformat() if next_anchor_ts else None),
        "next_anchor_id": next_anchor_id or None,
        "batch_min_ts": (last_batch_min_ts.isoformat() if last_batch_min_ts else None),
        "batch_max_ts": (last_batch_max_ts.isoformat() if last_batch_max_ts else None),
        "fetch_calls": fetch_calls,
        "skipped_anchor": skipped_anchor,
        "early_break": early_break,
        "in_window": int(saw_in_window),
    }
    try:
        if logger: logger.info({"evt": "retail_import_done", **stats})
    except Exception:
        pass
    return stats



def _mk_base() -> str:
    # Privzeti base, če ni nastavljen v configu/okolju
    base = os.environ.get('MK_API_BASE') or current_app.config.get('MK_API_BASE', 'https://main.metakocka.si/rest/eshop/v1')
    return base.rstrip('/')


def _mk_eshop_root_base() -> str:
    base = _mk_base().rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base.rstrip("/")


# Helper for Document API base (used by mk_get_document_bill)
def _mk_document_base() -> str:
    base = os.environ.get('MK_DOCUMENT_API_BASE') or 'https://main.metakocka.si/rest/document/v1'
    return base.rstrip('/')


def _mk_company_id() -> str:
    return os.environ.get('MK_COMPANY_ID') or str(current_app.config.get('MK_COMPANY_ID', ''))


def _mk_secret_key() -> str:
    # Podpri obe imeni: MK_API_KEY in MK_SECRET_KEY
    return (
        os.environ.get('MK_API_KEY')
        or os.environ.get('MK_SECRET_KEY')
        or current_app.config.get('MK_API_KEY', '')
        or current_app.config.get('MK_SECRET_KEY', '')
    )


def _mk_sales_doc_types():
    """Return list of MK sales document types to scan/import.

    Configurable via MK_SALES_DOC_TYPES (comma-separated), defaults to common types.
    """
    # Only valid doc types; exclude unsupported 'sales_bill'
    default_types = ['sales_bill_foreign','sales_bill_domestic','sales_bill_retail','sales_bill_prepaid','sales_bill_credit_note']
    try:
        cfg = os.environ.get('MK_SALES_DOC_TYPES') or current_app.config.get('MK_SALES_DOC_TYPES')
        if cfg:
            # Normalize and filter to allowed types
            allowed = set(t.lower() for t in default_types)
            items = [s.strip() for s in str(cfg).split(',') if str(s).strip()]
            items = [t for t in items if t.lower() in allowed]
            if items:
                # Ensure default essentials are included at the end, preserve user order
                seen = set(x.lower() for x in items)
                for dt in default_types:
                    if dt.lower() not in seen:
                        items.append(dt)
                        seen.add(dt.lower())
                return items
    except Exception:
        pass
    return default_types


def _mk_limit_for_doc_type(doc_type: str, requested_limit: int) -> int:
    """MK /search caps limit to 100 for sales bill endpoints; apply cap defensively."""
    try:
        return max(1, min(int(requested_limit), 100))
    except Exception:
        return 100


def mk_get_document(doc_type: str, doc_id: str, extra: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Call MetaKocka get_document for bills.

    Args:
        doc_type: e.g., 'sales_bill_domestic'
        doc_id: MK document id (mk_id)
        extra: additional flags like {'show_payment_detail': 'true'}
    Returns: dict response on success or None
    """
    base = _mk_base()
    company_id = _mk_company_id()
    secret = _mk_secret_key()
    if not base or not company_id or not secret:
        current_app.logger.error('MK config missing (MK_API_BASE / MK_COMPANY_ID / MK_API_KEY)')
        return None

    url = f"{base}/get_document"
    # Always include both secret and secret_key for compatibility
    payload = {
        'company_id': str(company_id),
        'secret': str(secret),
        'secret_key': str(secret),
        'doc_type': doc_type,
        'doc_id': str(doc_id),
        'show_product_list': 'true'
    }
    if extra:
        payload.update(extra)
    try:
        # READ op (get_document) — manj agresivni retry, ker:
        #   - če dokumenta NI, MK vrne hitro permanent napako (non-transient detect)
        #   - če je MK down, raje hitro pademo in skip-amo, kot da blokiramo
        #     cron jobs za 30s/orderno
        # Worst-case backoff: 1 + 2 + 4 = 7 s (vs prej 31 s).
        dj = _mk_post_json_with_retry(url, payload, max_attempts=3, min_backoff=1.0, max_backoff=8.0)
        return dj
    except Exception as e:
        current_app.logger.error(f"MK get_document error: {e}")
        return None


def mk_get_document_bill(doc_id: str) -> Optional[Dict[str, Any]]:
    """Call MetaKocka get_document_bill for any bill type by mk_id.

    According to API docs, this endpoint returns the full bill regardless of sales subtype.
    """
    base = _mk_document_base()
    company_id = _mk_company_id()
    secret = _mk_secret_key()
    if not base or not company_id or not secret:
        try:
            current_app.logger.error('MK config missing (base/company_id/secret) for get_document_bill')
        except Exception:
            pass
        return None

    url = f"{base}/get_document_bill"
    payload = {
        'company_id': str(company_id),
        'secret': str(secret),
        'secret_key': str(secret),
        'doc_id': str(doc_id),
        'show_product_list': 'true'
    }
    try:
        timeout = int(current_app.config.get('MK_TIMEOUT', 15))
        resp = requests.post(url, json=payload, timeout=timeout)
        if not resp.ok:
            current_app.logger.warning(f"MK get_document_bill HTTP {resp.status_code}: {resp.text[:300]}")
            return None
        return resp.json()
    except Exception as e:
        try:
            current_app.logger.error(f"MK get_document_bill error: {e}")
        except Exception:
            pass
        return None

def _matches_order_ref(doc: Dict[str, Any], order_ref: str) -> bool:
    """Strictly match order reference to document title or buyer_order.

    - Trims and strips leading '#'
    - Also compares digits-only variants to tolerate minor decorations
    """
    try:
        def _norm_basic(x: str) -> str:
            return (x or '').strip().lstrip('#')
        def _digits_only(x: str) -> str:
            return ''.join(ch for ch in (x or '') if ch.isdigit())

        target_basic = _norm_basic(order_ref)
        title_basic = _norm_basic(doc.get('title') or '')
        buyer_basic = _norm_basic(doc.get('buyer_order') or '')
        if title_basic == target_basic or buyer_basic == target_basic:
            return True

        target_digits = _digits_only(order_ref)
        if not target_digits:
            return False
        if _digits_only(title_basic) == target_digits or _digits_only(buyer_basic) == target_digits:
            return True
        # Preveri tudi count_code (npr. KP-MK-11766)
        count_code = (doc.get('count_code') or '').strip()
        if count_code:
            cc_digits = _digits_only(count_code)
            if cc_digits == target_digits:
                return True
            if count_code.endswith(f"-{_norm_basic(order_ref)}"):
                return True
        return False
    except Exception:
        return False


def _normalize_name_tokens(name: str) -> list[str]:
    try:
        raw = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode('ascii')
    except Exception:
        raw = str(name or '')
    # Keep only letters and spaces for tokenization
    cleaned = re.sub(r'[^a-zA-Z ]+', ' ', raw).lower()
    tokens = [t for t in cleaned.split() if t]
    return tokens


def _extract_doc_customer_name(doc: Dict[str, Any]) -> str:
    if not isinstance(doc, dict):
        return ''

    def _from_val(val: Any) -> str:
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, dict):
            for subkey in ('name', 'full_name', 'company_name', 'buyer_name', 'customer', 'partner_name'):
                subval = val.get(subkey)
                if isinstance(subval, str) and subval.strip():
                    return subval.strip()
        return ''

    def _scan_dict(d: Dict[str, Any]) -> str:
        for key in (
            'partner_name', 'buyer', 'buyer_name', 'customer_name', 'customer',
            'recipient_name', 'name', 'company_name', 'partner', 'recipient',
        ):
            val = d.get(key)
            out = _from_val(val)
            if out:
                return out
        return ''

    # Try top-level, then common nested containers
    for container in (
        doc,
        doc.get('doc') if isinstance(doc.get('doc'), dict) else None,
        doc.get('document') if isinstance(doc.get('document'), dict) else None,
        doc.get('head') if isinstance(doc.get('head'), dict) else None,
        doc.get('document_info') if isinstance(doc.get('document_info'), dict) else None,
    ):
        if isinstance(container, dict):
            out = _scan_dict(container)
            if out:
                return out
            # check nested head inside doc/document_info
            head = container.get('head')
            if isinstance(head, dict):
                out = _scan_dict(head)
                if out:
                    return out
    return ''


def mk_doc_matches_customer(doc: Dict[str, Any], customer_name: str) -> bool:
    """Return True when document buyer/customer matches provided customer name."""
    try:
        cust_tokens = _normalize_name_tokens(customer_name or '')
        if not cust_tokens:
            return True
        doc_name = _extract_doc_customer_name(doc)
        doc_tokens = _normalize_name_tokens(doc_name)
        if not doc_tokens:
            return False
        return all(t in doc_tokens for t in cust_tokens)
    except Exception:
        return False


def _build_recent_order_refs(days: int) -> tuple[set[str], set[str]]:
    """Return sets of recent order references from local DB for the last `days`.

    Returns (basic_set, digits_set) where basic_set contains refs like '12345' (without '#'),
    and digits_set contains only digits extracted from the same refs. Also includes count_code
    suffix (e.g., KP-MK-12345 => '12345').
    """
    try:
        from database import get_db
        db = get_db(); c = db.cursor()
        c.execute(
            """
            SELECT order_number, shopify_order_id
            FROM orders
            WHERE COALESCE(fulfilled_at, created_at) > NOW() - make_interval(days => %s)
            """,
            (int(days),)
        )
        rows = c.fetchall() or []
        try:
            c.close()
        except Exception:
            pass
        basic: set[str] = set()
        digits: set[str] = set()

        def _norm_basic(x: str) -> str:
            return (x or '').strip().lstrip('#')
        def _digits_only(x: str) -> str:
            return ''.join(ch for ch in (x or '') if ch.isdigit())

        for r in rows:
            if isinstance(r, dict):
                order_num = _norm_basic(str(r.get('order_number') or ''))
                shop_id = _norm_basic(str(r.get('shopify_order_id') or ''))
            else:
                order_num = _norm_basic(str(r[0] or ''))
                shop_id = _norm_basic(str(r[1] or ''))
            for ref in (order_num, shop_id):
                if ref:
                    basic.add(ref)
                    d = _digits_only(ref)
                    if d:
                        digits.add(d)
        return basic, digits
    except Exception:
        return set(), set()


def _doc_matches_any_order_ref(doc: Dict[str, Any], basic_refs: set[str], digit_refs: set[str]) -> bool:
    """Check if doc's potential references (title, buyer_order, count_code) match given order ref sets."""
    try:
        def _norm_basic(x: str) -> str:
            return (x or '').strip().lstrip('#')
        def _digits_only(x: str) -> str:
            return ''.join(ch for ch in (x or '') if ch.isdigit())

        cands = [
            _norm_basic(str(doc.get('title') or '')),
            _norm_basic(str(doc.get('buyer_order') or '')),
        ]
        count_code = (doc.get('count_code') or '').strip()
        if count_code:
            cands.append(count_code)

        for cand in cands:
            if not cand:
                continue
            if cand in basic_refs:
                return True
            d = _digits_only(cand)
            if d and d in digit_refs:
                return True
        return False
    except Exception:
        return False

def mk_find_bill_by_title(doc_type: str, title: str) -> Optional[Dict[str, Any]]:
    """Locate bill by Shopify order number mapped to MetaKocka title or buyer_order.

    Strategy:
    1) Try direct get_document with doc_id == title
    2) Search via /search by title, then buyer_order
    3) If not found for given doc_type, try other sales bill types as fallback
    """
    base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
    if not base or not company_id or not secret:
        current_app.logger.error('MK config missing (base/company_id/secret).')
        return None

    # Doc types fallback list
    sales_types = [doc_type] + [t for t in _mk_sales_doc_types() if t != doc_type]
    tried_types = set()

    def _try_for_type(dt: str) -> Optional[Dict[str, Any]]:
        # 1) direct get by id (skip when title is plain order number)
        t_str = str(title or '').strip()
        t_clean = t_str.lstrip('#')
        if t_clean and not t_clean.isdigit():
            d = mk_get_document(dt, str(title))
            if d and d.get('mk_id'):
                return d
        # 2) search
        url = f"{base}/search"
        for mode in ('title', 'buyer_order'):
            offset = 0
            limit = 100
            scanned = 0
            while scanned < 1000:
                payload = {
                    'company_id': str(company_id),
                    'secret_key': str(secret),
                    'doc_type': dt,
                    mode: str(title),
                    'offset': offset,
                    'limit': limit
                }
                try:
                    timeout = int(current_app.config.get('MK_TIMEOUT', 20))
                    resp = requests.post(url, json=payload, timeout=timeout)
                    if not resp.ok:
                        current_app.logger.warning(f"MK search({dt},{mode}) HTTP {resp.status_code}: {resp.text[:200]}")
                        break
                    data = resp.json()
                    rows = []
                    if isinstance(data, list):
                        rows = data
                    elif isinstance(data, dict):
                        rows = data.get('rows') or data.get('result') or data.get('documents') or []
                    if not rows:
                        break
                    for r in rows:
                        mk_id = r.get('mk_id') or r.get('id') or r.get('doc_id')
                        if not mk_id:
                            continue
                        doc = mk_get_document(dt, str(mk_id))
                        if not doc:
                            continue
                        if _matches_order_ref(doc, title):
                            return doc
                    scanned += len(rows)
                    if len(rows) < limit:
                        break
                    offset += limit
                except Exception as e:
                    current_app.logger.error(f"MK search({dt},{mode}) error: {e}")
                    break
        return None

    # Try primary type then fallbacks
    for dt in sales_types:
        if dt in tried_types:
            continue
        tried_types.add(dt)
        found = _try_for_type(dt)
        if found:
            if dt != doc_type:
                current_app.logger.info(f"MK bill found under different type {dt} for title {title}")
            return found

    current_app.logger.error(f"MK find bill: not found for title {title} across {sales_types}")
    return None

def _collect_attachment_candidates(doc: Optional[Dict[str, Any]]) -> list[dict]:
    if not isinstance(doc, dict):
        return []
    candidates: list[dict] = []
    for key in (
        'attachments',
        'attachment_list',
        'attachment',
        'files',
        'documents',
        'doc_attachments',
    ):
        val = doc.get(key)
        if isinstance(val, list):
            candidates.extend([v for v in val if isinstance(v, dict)])
        elif isinstance(val, dict):
            if isinstance(val.get('rows'), list):
                candidates.extend([v for v in val.get('rows') if isinstance(v, dict)])
            else:
                candidates.append(val)
    info = doc.get('document_info')
    if isinstance(info, dict):
        for key in ('attachments', 'attachment_list', 'files'):
            val = info.get(key)
            if isinstance(val, list):
                candidates.extend([v for v in val if isinstance(v, dict)])
            elif isinstance(val, dict):
                candidates.append(val)
    return candidates

def _attachment_matches_order(att: dict, order_number: str) -> bool:
    order_token = str(order_number or '').replace('#', '').strip()
    hay = " ".join(
        str(att.get(k, '') or '')
        for k in (
            'filename', 'file_name', 'name', 'title', 'description',
            'url', 'path', 'source_url', 'file_url', 'download_url',
        )
    ).lower()
    if order_token and order_token in hay:
        return True
    if 'amourparfumsdeclaration' in hay:
        return True
    if 'declaration' in hay or 'deklaracij' in hay:
        return True
    return False

def _attachment_ts(att: dict) -> Optional[datetime]:
    for k in ('created_at', 'uploaded_at', 'date', 'timestamp', 'ts'):
        v = att.get(k)
        if not v:
            continue
        try:
            if isinstance(v, (int, float)):
                return datetime.fromtimestamp(v, tz=timezone.utc)
            if isinstance(v, str):
                return datetime.fromisoformat(v.replace('Z', '+00:00'))
        except Exception:
            continue
    return None

def mk_find_declaration_attachment_ts(doc: Optional[Dict[str, Any]], order_number: str) -> Optional[datetime]:
    """Return attachment timestamp if a declaration attachment exists for order."""
    for att in _collect_attachment_candidates(doc):
        if _attachment_matches_order(att, order_number):
            return _attachment_ts(att) or datetime.now(timezone.utc)
    return None


def mk_add_attachment(
    doc_type: str,
    doc_id: str,
    file_name: str,
    *,
    base64_data: Optional[str] = None,
    source_url: Optional[str] = None,
    content_type: str = "application/pdf",
) -> Optional[Dict[str, Any]]:
    """Add attachment to MK document using base64 or a source URL."""
    if not doc_type or not doc_id:
        return None
    attempts: list[tuple[str, dict]] = []
    if source_url:
        attempts.append((
            "source_url",
            {
                "doc_type": str(doc_type),
                "mk_id": str(doc_id),
                "attachment_list": [
                    {
                        "file_name": str(file_name),
                        "source_url": str(source_url),
                    }
                ],
            },
        ))
    if base64_data:
        attempts.append((
            "data_b64",
            {
                "doc_type": str(doc_type),
                "mk_id": str(doc_id),
                "attachment_list": [
                    {
                        "file_name": str(file_name),
                        "data_b64": str(base64_data),
                    }
                ],
            },
        ))
    eshop_root = _mk_eshop_root_base()
    for label, payload in attempts:
        try:
            url = f"{eshop_root}/add_attachment"
            r = requests.post(url, json=_with_auth(payload), timeout=45)
            r.raise_for_status()
            data = r.json()
            try:
                oc = int(data.get("opr_code", 0)) if isinstance(data, dict) and "opr_code" in data else 0
            except Exception:
                oc = 0
            if oc and oc > 0:
                raise RuntimeError(f"MK error {oc}: {data.get('opr_desc')}")
            return data
        except Exception as e:
            try:
                current_app.logger.warning(f"MK add_attachment failed ({label}) for {doc_type}/{doc_id}: {e}")
            except Exception:
                pass
    return None


def mk_attach_declaration_for_order(
    order_number: str,
    *,
    shopify_order_id: Optional[str] = None,
    mk_bill_id: Optional[str] = None,
    mk_bill_type: Optional[str] = None,
    mk_sales_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach declaration PDF to MK document for given order.

    Vrstni red iskanja MK target dokumenta:
      1) `mk_sales_order_id` (najnovejši, najhitrejši — Next.js cache iz cron+webhook).
         MK support: prilogo nalagamo na `sales_order`, ne na `sales_bill_*`.
      2) `mk_bill_id` + `mk_bill_type` iz lokalne DB.
      3) `mk_bills` cache tabela.
      4) Drag MK search (mk_find_bill_*, mk_find_sales_order_by_title) — počasno.
    """
    order_ref = str(order_number or "").strip()
    order_ref_clean = order_ref.lstrip("#")
    result = {"success": False, "mk_id": None, "doc_type": None, "error": None}

    doc_type: Optional[str] = None
    mk_id: Optional[str] = None

    # 1) Next.js cache: mk_sales_order_id (priporočena pot per MK support).
    if mk_sales_order_id:
        sid = str(mk_sales_order_id).strip()
        if sid and sid.lower() not in ('null', 'none'):
            mk_id = sid
            doc_type = 'sales_order'

    # 2) Lokalno polje mk_bill_id (starejši mehanizem).
    if not mk_id:
        doc_type = mk_bill_type
        mk_id = mk_bill_id
        try:
            if mk_id and _is_probably_order_number(mk_id, order_ref):
                mk_id = None
                doc_type = None
        except Exception:
            pass

    # CRITICAL: MK Mandrill trigger 'deklaracije_si' pošlje samo, če je priponka
    # na sales_order. Priponke na sales_bill_* ne sprožijo trigger-ja, kar pomeni
    # da kupec NE dobi deklaracije. Zato VEDNO najprej preverimo sales_order.
    #
    # Prej je bila prioriteta: mk_sales_order_id → mk_bill_id → mk_bills cache
    # → mk_find_bill_any (poišče sales_bill) → ... → sales_order kot LAST RESORT.
    # To je povzročilo, da je za ~100 naročil v zadnjih 10 dneh priponka
    # pristala na sales_bill_foreign in Mandrill trigger nikoli ni stekel.
    #
    # Nova prioriteta: mk_sales_order_id → search sales_order → šele potem bills.

    # 3) Search sales_order po title (počasno ~10-30s, ampak nujno za Mandrill).
    if not mk_id or doc_type != 'sales_order':
        try:
            so = mk_find_sales_order_by_title(order_ref_clean or order_ref)
            if not so and order_ref_clean:
                so = mk_find_sales_order_by_title(order_ref)
            if so:
                doc_type = 'sales_order'
                mk_id = (
                    so.get('mk_id')
                    or so.get('id')
                    or so.get('doc_id')
                    or _pick_mk_doc_id(so, order_ref)
                )
        except Exception as e:
            try:
                current_app.logger.warning(f"sales_order search failed for {order_ref}: {e}")
            except Exception:
                pass

    # 4) Cache mk_bills tabela (fallback, če sales_order ni najden).
    if not mk_id or not doc_type:
        db_hit = mk_find_bill_in_db(order_ref)
        if not db_hit and order_ref_clean:
            db_hit = mk_find_bill_in_db(order_ref_clean)
        if db_hit:
            mk_id = db_hit.get("mk_id")
            doc_type = db_hit.get("doc_type")

    # 5) Drag MK search za bills (zadnji fallback).
    bill = None
    if not mk_id or not doc_type:
        bill = mk_find_bill_any(order_ref_clean or order_ref)
        if not bill and order_ref_clean:
            bill = mk_find_bill_any(order_ref)
        if not bill and order_ref_clean:
            try:
                bill = mk_find_bill_quick("sales_bill_foreign", order_ref_clean, limit=200)
            except Exception:
                bill = None
        if not bill and order_ref_clean:
            try:
                bill = mk_find_bill_by_title("sales_bill_foreign", order_ref_clean)
            except Exception:
                bill = None
        if not bill and shopify_order_id:
            bill = mk_find_bill_any(str(shopify_order_id))
        if bill:
            doc_type = doc_type or bill.get("_doc_type") or bill.get("doc_type")
            mk_id = mk_id or _pick_mk_doc_id(bill, order_ref)

    if not mk_id or not doc_type:
        result["error"] = "bill_not_found"
        return result

    try:
        from services.pdf_service import generiraj_pdf_za_order
        pdf_bytes = generiraj_pdf_za_order(order_ref_clean or order_ref)
    except Exception as e:
        pdf_bytes = None
        result["error"] = f"pdf_error:{e}"
    if not pdf_bytes:
        result["error"] = result["error"] or "pdf_missing"
        return result

    try:
        b64 = base64.b64encode(pdf_bytes).decode("ascii")
    except Exception as e:
        result["error"] = f"pdf_base64_error:{e}"
        return result

    filename = f"declaration_{order_ref_clean or order_ref}.pdf"
    resp = mk_add_attachment(doc_type, mk_id, filename, base64_data=b64)
    if not resp:
        result["error"] = "mk_add_attachment_failed"
        return result

    result["success"] = True
    result["mk_id"] = str(mk_id)
    result["doc_type"] = str(doc_type)
    return result

def _is_probably_order_number(mk_bill_id: Optional[str], order_number: str) -> bool:
    if not mk_bill_id:
        return False
    try:
        mk_str = str(mk_bill_id).strip().lstrip('#')
        ord_str = str(order_number or '').strip().lstrip('#')
        return mk_str == ord_str and mk_str.isdigit()
    except Exception:
        return False

def _mk_has_error(doc: Optional[Dict[str, Any]]) -> bool:
    try:
        if not doc or not isinstance(doc, dict):
            return False
        oc = doc.get('opr_code')
        if oc is None:
            return False
        try:
            return int(str(oc).strip() or "0") > 0
        except Exception:
            return bool(oc)
    except Exception:
        return False

def sync_mk_declaration_uploads(days_back: int = 7, limit: int = 200, include_already: bool = False, order_numbers: Optional[List[str]] = None) -> dict:
    """Sync mk_decl_uploaded_at for recent closed orders by inspecting MK attachments.

    NOTE: Knows MK API calls are slow (seconds each). Uses *short* transactions to avoid
    holding a `idle in transaction` connection while doing external HTTP work, which would
    starve the Postgres connection pool.
    """
    db = get_db()
    cursor = db.cursor()
    updated: list[str] = []
    checked = 0
    rows: list = []
    try:
        # 1) Ensure schema (DDL) and immediately commit so we don't carry a transaction.
        try:
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS mk_decl_uploaded_at TIMESTAMP NULL")
            cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS mk_decl_upload_checked_at TIMESTAMP NULL")
            db.commit()
        except Exception:
            db.rollback()
            raise

        # 2) Read candidate orders, then COMMIT to release the read transaction.
        if order_numbers:
            normalized = []
            for on in order_numbers:
                if not on:
                    continue
                s = str(on).strip()
                normalized.append(s)
                if s.startswith('#'):
                    normalized.append(s.lstrip('#'))
                else:
                    normalized.append(f"#{s}")
            q_marks = ','.join(['%s'] * len(normalized)) if normalized else ''
            cursor.execute(
                f"""
                SELECT o.order_number, o.mk_bill_id, o.mk_bill_type, o.shopify_order_id
                FROM orders o
                WHERE o.order_number IN ({q_marks})
                """,
                (*normalized,),
            )
        else:
            where = ["o.created_at >= NOW() - (%s * INTERVAL '1 day')"]
            params = [days_back]
            if not include_already:
                where.append("o.mk_decl_uploaded_at IS NULL")
            where.append("o.closed_at IS NOT NULL")
            where_clause = "WHERE " + " AND ".join(where)

            cursor.execute(
                f"""
                SELECT o.order_number, o.mk_bill_id, o.mk_bill_type, o.shopify_order_id
                FROM orders o
                {where_clause}
                ORDER BY o.created_at DESC
                LIMIT %s
                """,
                (*params, limit),
            )
        rows = cursor.fetchall() or []
        # Release transaction held by the SELECT before doing any external HTTP work.
        try:
            db.commit()
        except Exception:
            db.rollback()
    finally:
        # We don't need the cursor for a long time during HTTP calls.
        try:
            cursor.close()
        except Exception:
            pass

    # 3) For each row, do MK HTTP calls *outside* a DB transaction, then write back
    #    in a fresh short transaction. Errors on a single row don't leak a connection.
    for row in rows:
        checked += 1
        try:
            order_number = row['order_number'] if isinstance(row, dict) else row[0]
            mk_bill_id = row['mk_bill_id'] if isinstance(row, dict) else row[1]
            mk_bill_type = row['mk_bill_type'] if isinstance(row, dict) else row[2]
            shopify_order_id = row['shopify_order_id'] if isinstance(row, dict) else row[3]

            doc = None
            if mk_bill_id and mk_bill_type and not _is_probably_order_number(mk_bill_id, order_number):
                doc = mk_get_document(
                    mk_bill_type,
                    str(mk_bill_id),
                    extra={
                        'show_attachment_list': 'true',
                        'show_files': 'true',
                        'show_attachments': 'true',
                    },
                )
                if doc and not _mk_has_error(doc):
                    doc['_doc_type'] = mk_bill_type
                else:
                    doc = None
            if not doc:
                ord_clean = str(order_number or '').replace('#', '').strip()
                doc = mk_find_bill_any(ord_clean)
                if not doc and shopify_order_id:
                    doc = mk_find_bill_any(str(shopify_order_id))
            if doc and doc.get('mk_id') and doc.get('_doc_type'):
                doc = mk_get_document(
                    doc.get('_doc_type'),
                    str(doc.get('mk_id')),
                    extra={
                        'show_attachment_list': 'true',
                        'show_files': 'true',
                        'show_attachments': 'true',
                    },
                ) or doc
                if _mk_has_error(doc):
                    doc = None
            if not doc and mk_bill_id and not _is_probably_order_number(mk_bill_id, order_number):
                doc = mk_get_document_bill(str(mk_bill_id))

            ts = mk_find_declaration_attachment_ts(doc, str(order_number or ''))

            # Short write transaction (open cursor, execute, commit, close).
            wcur = db.cursor()
            try:
                if ts:
                    wcur.execute(
                        """
                        UPDATE orders
                        SET mk_decl_uploaded_at = %s,
                            mk_decl_upload_checked_at = NOW()
                        WHERE order_number = %s OR order_number = %s
                        """,
                        (ts, order_number, f"#{str(order_number).replace('#','')}"),
                    )
                    updated.append(str(order_number))
                else:
                    wcur.execute(
                        """
                        UPDATE orders
                        SET mk_decl_upload_checked_at = NOW()
                        WHERE order_number = %s OR order_number = %s
                        """,
                        (order_number, f"#{str(order_number).replace('#','')}"),
                    )
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                try:
                    wcur.close()
                except Exception:
                    pass
        except Exception as e:
            try:
                from flask import current_app as _ca
                _ca.logger.warning(f"sync_mk_declaration_uploads: row failed for order_number={row}: {e}")
            except Exception:
                pass
            # Continue with next row; never let one failure poison the whole batch.
            continue

    return {"checked": checked, "updated": len(updated), "orders": updated}


def _mk_bool_env(name: str, default: bool = False) -> bool:
    try:
        v = os.environ.get(name)
        if v is None:
            return default
        return str(v).strip().lower() in ('1', 'true', 'yes', 'y', 'on')
    except Exception:
        return default


def _is_non_transient_mk_error(err_msg: str) -> bool:
    """Razlikuj med transient (network, 5xx, throttling) in permanent (bad input,
    not-found, schema) napakami. Permanent napake ne smemo retry-ati, ker bomo
    samo zapravljali čas (5 attempts × eksponentni backoff = 30+ sekund po nepotrebnem).

    Primeri permanent napak iz MK API:
      - "Cannot find document type X with id=..." — dokument ne obstaja
      - "Cannot find document type X with doc_id = null" — manjkajoč input
      - "doc_id is required" — manjkajoč input
      - "Invalid doc_type" — schema napaka
      - "Permission denied" / "Access denied" — auth (404/403)
    """
    if not err_msg:
        return False
    m = err_msg.lower()
    non_transient_markers = (
        "cannot find document",
        "document not found",
        "is required",
        "= null",
        "invalid doc_type",
        "invalid document",
        "permission denied",
        "access denied",
        "http 404",
        "http 400",
        "http 401",
        "http 403",
    )
    return any(mk in m for mk in non_transient_markers)


def _mk_post_json_with_retry(url: str, payload: Dict[str, Any], *, max_attempts: int = 5, min_backoff: float = 1.0, max_backoff: float = 20.0, timeout: Optional[int] = None) -> Dict[str, Any]:
    """POST JSON with exponential backoff and basic jitter. Raises on final failure.

    - Logs concise errors without secrets
    - Non-transient errors (npr. "Cannot find document type X") so DETECTED in
      preskoči retry-je — vržemo takoj.
    """
    attempt = 0
    last_err: Optional[Exception] = None
    to = timeout or int(current_app.config.get('MK_TIMEOUT', 15))
    safe_payload = {k: ('***' if 'secret' in k.lower() else v) for k, v in (payload or {}).items()}
    while attempt < max_attempts:
        attempt += 1
        try:
            # Auto-include both secret and secret_key when company_id/secret are available and not present
            try:
                base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
                if company_id and secret:
                    if 'company_id' not in payload:
                        payload['company_id'] = str(company_id)
                    # If either secret or secret_key appears, ensure both are present
                    has_secret = any(k for k in payload.keys() if k == 'secret')
                    has_secret_key = any(k for k in payload.keys() if k == 'secret_key')
                    if has_secret and not has_secret_key:
                        payload['secret_key'] = str(secret)
                    if has_secret_key and not has_secret:
                        payload['secret'] = str(secret)
                    if not has_secret and not has_secret_key:
                        payload['secret'] = str(secret)
                        payload['secret_key'] = str(secret)
            except Exception:
                pass
            resp = requests.post(url, json=payload, timeout=to)
            if not resp.ok:
                current_app.logger.error(f"MK POST {url} HTTP {resp.status_code} (attempt {attempt}): {resp.text[:200]}")
                raise RuntimeError(f"HTTP {resp.status_code}")
            dj = resp.json() if resp.headers.get('Content-Type','').startswith('application/json') else {}
            # MetaKocka errors often include opr_code / opr_desc
            if isinstance(dj, dict) and int(str(dj.get('opr_code') or 0)) > 0:
                desc = dj.get('opr_desc') or 'MK error'
                raise RuntimeError(f"MK error: {desc}")
            return dj
        except Exception as e:
            last_err = e
            # Non-transient napake ne retry-amo — vržemo takoj.
            err_str = str(e)
            if _is_non_transient_mk_error(err_str):
                current_app.logger.info(
                    f"MK POST {url} non-transient error (skip retry): {err_str[:200]}"
                )
                raise
            if attempt >= max_attempts:
                break
            sleep_s = min(max_backoff, min_backoff * (2 ** (attempt - 1)))
            # small jitter
            sleep_s = sleep_s * (0.8 + 0.4 * (os.urandom(1)[0] / 255.0))
            current_app.logger.warning(f"MK POST retry in {sleep_s:.1f}s for {url} with {safe_payload} due to: {e}")
            time.sleep(sleep_s)
    raise RuntimeError(f"MK POST failed after {max_attempts} attempts: {last_err}")


def mk_get_document_bill_via_get_document(doc_id: str) -> Optional[Dict[str, Any]]:
    """Fetch bill via generic get_document(doc_type='bill') with extended fields.

    Uses ESHOP /get_document endpoint and may not work on some tenants.
    Payload per docs: return_publish_ts, return_status_desc, return_method_of_payment,
    return_document_info, return_product_compound, return_allocated_cost_list, show_tax_factor.
    """
    base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
    if not base or not company_id or not secret:
        current_app.logger.error('MK config missing (MK_API_BASE / MK_COMPANY_ID / MK_API_KEY) for get_document bill')
        return None
    url = f"{base}/get_document"
    payload = {
        'company_id': str(company_id),
        'secret': str(secret),
        'secret_key': str(secret),
        'doc_type': 'bill',
        'doc_id': str(doc_id),
        'return_publish_ts': True,
        'return_status_desc': True,
        'return_method_of_payment': True,
        'return_document_info': True,
        'return_product_compound': True,
        'return_allocated_cost_list': True,
        'show_tax_factor': True,
    }
    try:
        # READ op — manj agresivni retry (3 attempts, 8s max backoff)
        dj = _mk_post_json_with_retry(url, payload, max_attempts=3, min_backoff=1.0, max_backoff=8.0)
        return dj
    except Exception as e:
        current_app.logger.error(f"mk_get_document_bill_via_get_document failed for {doc_id}: {e}")
        return None


def mk_search_bill_ids(date_from: datetime, date_to: datetime, *, page: int = 1, page_size: int = 200, doc_type_override: Optional[str] = None) -> Tuple[List[str], bool, Optional[int]]:
    """Search bill ids in date range using /search with pagination hints.

    Returns: (mk_ids, has_next, next_page)
    """
    base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
    url = f"{base}/search"
    # Try page/page_size style first, then fallback to offset/limit
    def _collect_ids(dobj: Any) -> List[str]:
        res: List[str] = []
        try:
            for key in ('id_list', 'mk_id_list', 'document_id_list'):
                if isinstance(dobj.get(key), list):
                    return [str(x) for x in dobj[key] if str(x).strip()]
        except Exception:
            pass
        rows = dobj if isinstance(dobj, list) else (dobj.get('rows') or dobj.get('result') or dobj.get('documents') or [])
        for rr in rows or []:
            sid = rr.get('mk_id') or rr.get('id') or rr.get('doc_id') or rr.get('document_id')
            if sid:
                res.append(str(sid))
        return res

    # Strategy A: page/page_size
    dt_search = (doc_type_override or 'bill')
    payload_a = {
        'company_id': str(company_id),
        'secret': str(secret),
        'doc_type': dt_search,
        'page': int(page),
        'page_size': max(1, min(100, int(page_size))),
        'result_type': 'id',
        'order_by': 'publish_ts',
        'order': 'desc',
        'query_advance': [
            {'type': 'doc_date_from', 'value': date_from.replace(tzinfo=timezone.utc).isoformat()},
            {'type': 'doc_date_to',   'value': date_to.replace(tzinfo=timezone.utc).isoformat()},
        ],
    }
    try:
        # READ op (bill search) — manj retry-jev
        dj = _mk_post_json_with_retry(url, payload_a, max_attempts=3, min_backoff=1.0, max_backoff=8.0)
        ids = _collect_ids(dj)
        if ids:
            has_next = bool(dj.get('has_next_page') or (dj.get('next_page') and dj.get('total_pages') and dj.get('next_page') <= dj.get('total_pages')))
            next_page = dj.get('next_page') if has_next else None
            return ids, has_next, (int(next_page) if next_page else None)
    except Exception as e:
        current_app.logger.warning(f"mk_search_bill_ids page-style failed: {e}")

    # Strategy B: offset/limit
    try:
        offset = (int(page) - 1) * max(1, min(100, int(page_size)))
        payload_b = {
            'company_id': str(company_id),
            'secret': str(secret),
            'doc_type': dt_search,
            'limit': max(1, min(100, int(page_size))),
            'offset': int(offset),
            'order_by': 'publish_ts',
            'order': 'desc',
            'result_type': 'doc',
            # Some servers expect publish_ts_from/to keys
            'publish_ts_from': date_from.replace(tzinfo=timezone.utc).isoformat(),
            'publish_ts_to': date_to.replace(tzinfo=timezone.utc).isoformat(),
            # Also include date filters via query_advance for compatibility
            'query_advance': [
                {'type': 'doc_date_from', 'value': date_from.replace(tzinfo=timezone.utc).isoformat()},
                {'type': 'doc_date_to',   'value': date_to.replace(tzinfo=timezone.utc).isoformat()},
            ],
        }
        # READ op — manj retry-jev
        dj2 = _mk_post_json_with_retry(url, payload_b, max_attempts=3, min_backoff=1.0, max_backoff=8.0)
        ids2 = _collect_ids(dj2)
        # Infer has_next by count
        has_next2 = len(ids2) >= int(page_size)
        next_page2 = int(page) + 1 if has_next2 else None
        return ids2, has_next2, next_page2
    except Exception as e2:
        current_app.logger.error(f"mk_search_bill_ids offset-style error: {e2}")
        return [], False, None


def mk_search_bill_ids_range(date_from: datetime, date_to: datetime, *, page_size: int = 200, max_pages: int = 100) -> Iterable[str]:
    """Generator yielding mk_id for bills in [date_from, date_to].

    Note: If server does not support doc_type='bill' for /search, call with doc_type_override='sales_order'
    using mk_search_bill_ids directly.
    """
    page = 1
    pages_scanned = 0
    while pages_scanned < int(max_pages):
        ids, has_next, next_page = mk_search_bill_ids(date_from, date_to, page=page, page_size=max(1, min(100, int(page_size))))
        if not ids:
            break
        for sid in ids:
            yield sid
        pages_scanned += 1
        if has_next and next_page:
            page = int(next_page)
            continue
        break


def is_retail_bill(payload: Dict[str, Any]) -> bool:
    """Detect retail bills robustly.

    Returns True if any of the following holds (in order):
      a) document_info.is_retail == True
      b) any of keys ('bill_type','sales_type','doc_sub_type','document_type','doc_type',
         'document_info.bill_type','document_info.sales_type') contains 'retail' (case-insensitive)
      c) fiscal indicators present: furs_zoi or furs_eor
      d) cash register indicators present: document_info.cash_register_id or .cash_register_name

    Fallback is preserved to previous checks.
    """
    try:
        doc_info = payload.get('document_info') or {}
        if isinstance(doc_info, dict) and bool(doc_info.get('is_retail')):
            return True
    except Exception:
        pass

    # Helper to get nested values like 'document_info.bill_type'
    def _get(path: str) -> str:
        try:
            cur: Any = payload
            for part in path.split('.'):
                if not isinstance(cur, dict):
                    return ''
                cur = cur.get(part)
            return '' if cur is None else str(cur)
        except Exception:
            return ''

    # b) textual markers containing 'retail'
    text_keys = [
        'bill_type', 'sales_type', 'doc_sub_type', 'document_type', 'doc_type',
        'document_info.bill_type', 'document_info.sales_type',
    ]
    for key in text_keys:
        val = _get(key).strip().lower()
        if 'retail' in val and val:
            return True

    # c) fiscal indicators
    try:
        if payload.get('furs_zoi') or payload.get('furs_eor'):
            return True
    except Exception:
        pass

    # d) cash register indicators
    try:
        if isinstance(doc_info, dict) and (doc_info.get('cash_register_id') or doc_info.get('cash_register_name')):
            return True
    except Exception:
        pass

    # Fallback to original logic
    try:
        dt = (payload.get('doc_type') or payload.get('document_type') or '').strip().lower()
        if 'retail' in dt:
            return True
    except Exception:
        pass
    return False


def _retail_diag_fields(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Extract diagnostic fields for retail detection, without sensitive data."""
    try:
        di = doc.get('document_info') or {}
        return {
            'mk_id': doc.get('mk_id'),
            'doc_type': doc.get('doc_type'),
            'document_type': doc.get('document_type'),
            'document_info.is_retail': (di or {}).get('is_retail'),
            'document_info.bill_type': (di or {}).get('bill_type'),
            'document_info.sales_type': (di or {}).get('sales_type'),
            'document_info.cash_register_id': (di or {}).get('cash_register_id'),
            'document_info.cash_register_name': (di or {}).get('cash_register_name'),
            'furs_zoi': doc.get('furs_zoi'),
            'furs_eor': doc.get('furs_eor'),
            'publish_ts': doc.get('publish_ts'),
        }
    except Exception:
        return {'mk_id': doc.get('mk_id')}


def mk_find_bill_recent(doc_type: str, title: str, window: int = 500) -> Optional[Dict[str, Any]]:
    """Scan the most recent documents for a title/buyer_order match when filters don't work.

    window: number of last documents to scan.
    """
    try:
        base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
        if not base or not company_id or not secret:
            return None
        url = f"{base}/search"
        # First call to get totals
        payload0 = {
            'company_id': str(company_id),
            'secret_key': str(secret),
            'doc_type': doc_type,
            'offset': 0,
            'limit': 1
        }
        resp0 = requests.post(url, json=payload0, timeout=int(current_app.config.get('MK_TIMEOUT', 15)))
        if not resp0.ok:
            return None
        data0 = resp0.json() if resp0.headers.get('Content-Type','').startswith('application/json') else {}
        total = 0
        if isinstance(data0, dict):
            try:
                total = int(data0.get('result_all_records') or 0)
            except Exception:
                total = 0
        start = max(total - window, 0)
        limit = 100
        offset = start
        while offset < total:
            payload = {
                'company_id': str(company_id),
                'secret_key': str(secret),
                'doc_type': doc_type,
                'offset': offset,
                'limit': limit
            }
            resp = requests.post(url, json=payload, timeout=int(current_app.config.get('MK_TIMEOUT', 20)))
            if not resp.ok:
                break
            data = resp.json() if resp.headers.get('Content-Type','').startswith('application/json') else {}
            rows = []
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = data.get('rows') or data.get('result') or data.get('documents') or []
            if not rows:
                break
            for r in rows:
                mk_id = _pick_mk_doc_id(r, title)
                d = None
                if mk_id and not _is_title_id(mk_id, title):
                    d = mk_get_document(doc_type, str(mk_id))
                else:
                    d = mk_get_document_bill_via_get_document(str(title))
                if d and _matches_order_ref(d, title):
                    return d
            offset += len(rows)
        return None
    except Exception:
        return None


def mk_is_published(bill: Dict[str, Any]) -> bool:
    """Return True if bill has publish_ts / is confirmed/published."""
    if not bill:
        return False
    def _has_publish_ts(d: Dict[str, Any]) -> bool:
        if not isinstance(d, dict):
            return False
        if d.get('publish_ts') or d.get('published_at') or d.get('publish_date'):
            return True
        try:
            if _as_utc_publish_ts(d):
                return True
        except Exception:
            pass
        return False

    for container in (
        bill,
        bill.get('doc') if isinstance(bill.get('doc'), dict) else None,
        bill.get('document') if isinstance(bill.get('document'), dict) else None,
        bill.get('head') if isinstance(bill.get('head'), dict) else None,
        bill.get('document_info') if isinstance(bill.get('document_info'), dict) else None,
    ):
        if isinstance(container, dict):
            if _has_publish_ts(container):
                return True
            head = container.get('head')
            if isinstance(head, dict) and _has_publish_ts(head):
                return True

    status_desc = str(bill.get('status_desc') or '').strip().lower()
    status = str(bill.get('status') or '').strip().lower()
    if status_desc in ('published', 'confirmed', 'confirmed_by_customer'):
        return True
    if status in ('published', 'confirmed', 'confirmed_by_customer'):
        return True
    if bill.get('is_published') is True or bill.get('published') is True:
        return True
    return False



def mk_search_bills(doc_types, title: str, per_mode_limit: int = 50, max_scan: int = 200):
    """Diagnostic search: return minimal info for bills matching title/buyer_order across types (also tries query).

    per_mode_limit: number of rows per page
    max_scan: max rows to scan per (doc_type, mode)
    """
    base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
    results = []
    if not base or not company_id or not secret:
        return results
    if not isinstance(doc_types, (list, tuple)):
        doc_types = [str(doc_types)]
    url = f"{base}/search"
    for dt in doc_types:
        for mode in ('query', 'title', 'buyer_order'):
            offset = 0
            limit = int(per_mode_limit)
            scanned = 0
            while scanned < int(max_scan):
                payload = {
                    'company_id': str(company_id),
                    'secret_key': str(secret),
                    'doc_type': dt,
                    'result_type': 'doc',
                    'offset': offset,
                    'limit': limit
                }
                if mode == 'query':
                    payload['query'] = str(title)
                else:
                    payload[mode] = str(title)
                try:
                    timeout = int(current_app.config.get('MK_TIMEOUT', 15))
                    resp = requests.post(url, json=payload, timeout=timeout)
                    if not resp.ok:
                        break
                    data = resp.json()
                    rows = []
                    if isinstance(data, list):
                        rows = data
                    elif isinstance(data, dict):
                        rows = data.get('rows') or data.get('result') or data.get('documents') or []
                    if not rows:
                        break
                    for r in rows:
                        mk_id = r.get('mk_id') or r.get('id') or r.get('doc_id')
                        if not mk_id:
                            continue
                        d = mk_get_document(dt, str(mk_id)) or {}
                        if not d:
                            # try generic bill fetch
                            d = mk_get_document_bill(str(mk_id)) or {}
                        results.append({
                            'doc_type': dt,
                            'mk_id': d.get('mk_id') or mk_id,
                            'title': d.get('title'),
                            'buyer_order': d.get('buyer_order'),
                            'count_code': d.get('count_code'),
                            'publish_ts': d.get('publish_ts')
                        })
                    scanned += len(rows)
                    if len(rows) < limit:
                        break
                    offset += limit
                except Exception:
                    break
    return results

def _pick_mk_doc_id(row: Dict[str, Any], title: str) -> Optional[str]:
    """Pick the best document id from search row.
    Avoid using the order number as doc_id when it matches the title.
    """
    try:
        title_clean = str(title or '').lstrip('#').strip()
    except Exception:
        title_clean = ''
    candidates = [
        row.get('mk_id'),
        row.get('id'),
        row.get('doc_id'),
        row.get('document_id'),
    ]
    cleaned = []
    for c in candidates:
        if not c:
            continue
        try:
            cleaned.append(str(c).strip())
        except Exception:
            continue
    # Prefer ids that are not equal to order number
    for c in cleaned:
        if title_clean and c.lstrip('#') == title_clean:
            continue
        return c
    # If all candidates equal the title, skip (avoid invalid doc_id calls)
    return None

def _is_title_id(doc_id: Optional[str], title: str) -> bool:
    try:
        if not doc_id:
            return False
        return str(doc_id).lstrip('#').strip() == str(title or '').lstrip('#').strip()
    except Exception:
        return False


def mk_find_bill_quick(doc_type: str, title: str, limit: int = 10) -> Optional[Dict[str, Any]]:
    """Fast check using supported 'query' with strict post-filter; falls back to legacy title/buyer_order filters."""
    base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
    if not base or not company_id or not secret:
        current_app.logger.error('MK quick: missing config')
        return None

    def _matches(doc: Dict[str, Any], t: str) -> bool:
        def _norm(x: str) -> str:
            return (x or '').strip().lstrip('#')
        tt = _norm(t)
        title_val = _norm(doc.get('title') or '')
        buyer_val = _norm(doc.get('buyer_order') or '')
        return title_val == tt or buyer_val == tt

    # 1) direct get by provided value only when title is not a plain order number
    title_str = str(title or '').strip()
    title_clean = title_str.lstrip('#')
    if title_clean and not title_clean.isdigit():
        doc = mk_get_document(doc_type, str(title))
        if doc and doc.get('mk_id') and _matches(doc, title):
            doc['_doc_type'] = doc_type
            return doc

    url = f"{base}/search"

    # 2) supported query search + strict post-filter
    payload_query = {
        'company_id': str(company_id),
        'secret_key': str(secret),
        'doc_type': doc_type,
        'query': str(title),
        'offset': 0,
        'limit': int(limit)
    }
    try:
        resp_q = requests.post(url, json=payload_query, timeout=int(current_app.config.get('MK_TIMEOUT', 10)))
        if resp_q.ok:
            data = resp_q.json()
            rows = []
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = data.get('rows') or data.get('result') or data.get('documents') or []
            for r in rows:
                mk_id = _pick_mk_doc_id(r, title)
                d = None
                if mk_id and not _is_title_id(mk_id, title):
                    d = mk_get_document(doc_type, str(mk_id))
                else:
                    # Fallback: try generic bill by title
                    d = mk_get_document_bill_via_get_document(str(title))
                if d and _matches_order_ref(d, title):
                    d['_doc_type'] = doc_type
                    return d
    except Exception:
        pass

    # 3) compatibility one-page search by explicit fields + strict filter
    for mode in ('title', 'buyer_order'):
        payload = {
            'company_id': str(company_id),
            'secret_key': str(secret),
            'doc_type': doc_type,
            mode: str(title),
            'offset': 0,
            'limit': int(limit)
        }
        try:
            resp = requests.post(url, json=payload, timeout=int(current_app.config.get('MK_TIMEOUT', 10)))
            if not resp.ok:
                continue
            data = resp.json()
            rows = []
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = data.get('rows') or data.get('result') or data.get('documents') or []
            for r in rows:
                mk_id = _pick_mk_doc_id(r, title)
                d = None
                if mk_id and not _is_title_id(mk_id, title):
                    d = mk_get_document(doc_type, str(mk_id))
                else:
                    d = mk_get_document_bill_via_get_document(str(title))
                if d and _matches_order_ref(d, title):
                    d['_doc_type'] = doc_type
                    return d
        except Exception:
            continue
    return None


def mk_find_bill_query_paginated(doc_type: str, title: str, max_scan: int = 5000, page_size: int = 200) -> Optional[Dict[str, Any]]:
    """Scan multiple pages with 'query' parameter and strict post-filter to find exact title/buyer_order match.

    Stops early on first exact match.
    """
    base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
    if not base or not company_id or not secret:
        return None
    url = f"{base}/search"
    scanned = 0
    offset = 0
    while scanned < max_scan:
        payload = {
            'company_id': str(company_id),
            'secret_key': str(secret),
            'doc_type': doc_type,
            'query': str(title),
            'offset': int(offset),
            'limit': int(page_size)
        }
        try:
            resp = requests.post(url, json=payload, timeout=int(current_app.config.get('MK_TIMEOUT', 15)))
            if not resp.ok:
                break
            data = resp.json()
            rows = []
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = data.get('rows') or data.get('result') or data.get('documents') or []
            if not rows:
                break
            for r in rows:
                mk_id = _pick_mk_doc_id(r, title)
                d = None
                if mk_id and not _is_title_id(mk_id, title):
                    d = mk_get_document(doc_type, str(mk_id))
                else:
                    d = mk_get_document_bill_via_get_document(str(title))
                if d and _matches_order_ref(d, title):
                    d['_doc_type'] = doc_type
                    return d
            scanned += len(rows)
            if len(rows) < page_size:
                break
            offset += page_size
        except Exception:
            break
    return None

def mk_find_bill_any(title: str) -> Optional[Dict[str, Any]]:
    """Try all sales bill types using query+strict filter first, then paginated query, then recent-scan as fallback."""
    types = _mk_sales_doc_types()
    # 1) quick attempts via query
    for dt in types:
        d = mk_find_bill_quick(dt, title, limit=50)
        if d:
            return d
    # 1b) paginated query across many matches with strict post-filter
    for dt in types:
        d = mk_find_bill_query_paginated(dt, title, max_scan=10000, page_size=200)
        if d:
            d['_doc_type'] = dt
            return d
    # 2) recent-scan fallback
    for dt in types:
        d = mk_find_bill_recent(dt, title, window=5000)
        if d:
            d['_doc_type'] = dt
            return d
    return None


def mk_find_sales_order_by_title(title: str) -> Optional[Dict[str, Any]]:
    """Locate sales_order by title or buyer_order using MK /search."""
    base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
    if not base or not company_id or not secret:
        current_app.logger.error('MK config missing (base/company_id/secret).')
        return None

    doc_type = 'sales_order'
    url = f"{base}/search"
    for mode in ('title', 'buyer_order'):
        offset = 0
        limit = 100
        scanned = 0
        while scanned < 1000:
            payload = {
                'company_id': str(company_id),
                'secret_key': str(secret),
                'doc_type': doc_type,
                mode: str(title),
                'offset': offset,
                'limit': limit
            }
            try:
                timeout = int(current_app.config.get('MK_TIMEOUT', 20))
                resp = requests.post(url, json=payload, timeout=timeout)
                if not resp.ok:
                    current_app.logger.warning(f"MK search({doc_type},{mode}) HTTP {resp.status_code}: {resp.text[:200]}")
                    break
                data = resp.json()
                rows = []
                if isinstance(data, list):
                    rows = data
                elif isinstance(data, dict):
                    rows = data.get('rows') or data.get('result') or data.get('documents') or []
                if not rows:
                    break
                for r in rows:
                    mk_id = r.get('mk_id') or r.get('id') or r.get('doc_id')
                    if not mk_id:
                        continue
                    doc = mk_get_document(doc_type, str(mk_id))
                    if not doc:
                        continue
                    if _matches_order_ref(doc, title):
                        doc['_doc_type'] = doc_type
                        return doc
                scanned += len(rows)
                if len(rows) < limit:
                    break
                offset += limit
            except Exception as e:
                current_app.logger.error(f"MK search({doc_type},{mode}) error: {e}")
                break
    return None


def mk_change_document_status(
    *,
    status_code: str,
    doc_type: str = 'sales_order',
    mk_id: Optional[str] = None,
    buyer_order: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """POST na MK `change_document_status` (programski preklic naročila).

    MK identificira dokument po `mk_id` (prednostno) ALI `buyer_order` (št. naročila).
    `status_code` MORA biti točen "description" preklicanega statusa iz MK registra
    (nastavljen prek env MK_CANCEL_STATUS_CODE — tukaj ga NE ugibamo/hardcodamo).

    Returns dict odgovora MK (vrže izjemo le ob HTTP/MK napaki prek retry helperja).
    """
    base = _mk_base()
    company_id = _mk_company_id()
    secret = _mk_secret_key()
    if not base or not company_id or not secret:
        raise RuntimeError('MK config missing (base/company_id/secret) for change_document_status')
    if not (mk_id or buyer_order):
        raise RuntimeError('mk_change_document_status: manjka mk_id ali buyer_order')

    url = f"{base}/change_document_status"
    payload: Dict[str, Any] = {
        'company_id': str(company_id),
        'secret': str(secret),
        'secret_key': str(secret),
        'doc_type': doc_type,
        'status_code': str(status_code),
    }
    if mk_id:
        payload['mk_id'] = str(mk_id)
    if buyer_order:
        payload['buyer_order'] = str(buyer_order)

    # WRITE op — zmeren retry (kot drugi MK write klici).
    return _mk_post_json_with_retry(url, payload, max_attempts=3, min_backoff=1.0, max_backoff=8.0, timeout=timeout)


def mk_cancel_sales_order_if_unshipped(order_number: str) -> Dict[str, Any]:
    """Best-effort programski preklic MK sales_order, ČE še ni odpremljen.

    Flow (vse non-blocking, vrne diagnostični dict; klicalec dodatno ovije v try):
      1. GATING: če MK_CANCEL_STATUS_CODE ni nastavljen → preskoči (no-op).
      2. Najdi MK sales_order po številki naročila in preberi trenuten status.
      3. Če je status shipped/completed/returned → preskoči (prepozno / ni smiselno).
      4. Sicer nastavi status na preklic (change_document_status).
    """
    status_code = (os.environ.get('MK_CANCEL_STATUS_CODE') or '').strip()
    if not status_code:
        try:
            current_app.logger.info("MK cancel skipped (MK_CANCEL_STATUS_CODE not set)")
        except Exception:
            pass
        return {'skipped': True, 'reason': 'MK_CANCEL_STATUS_CODE not set'}

    if not order_number:
        return {'skipped': True, 'reason': 'no order_number'}

    clean = str(order_number).lstrip('#').strip()
    try:
        doc = mk_find_sales_order_by_title(clean) or mk_find_sales_order_by_title(str(order_number))
    except Exception as e:
        return {'skipped': True, 'reason': f'MK lookup failed: {e}'}
    if not doc:
        return {'skipped': True, 'reason': 'MK sales_order not found'}

    from services.declaration_safety_net import classify_mk_status
    category = classify_mk_status(doc.get('status_desc'), doc.get('status_code'))
    if category in ('shipped', 'completed', 'returned'):
        return {
            'skipped': True,
            'reason': f'MK status={category} (že odpremljeno/zaključeno/vračilo) — preklic ne izvedem',
            'mk_status_code': doc.get('status_code'),
            'mk_status_desc': doc.get('status_desc'),
        }

    mk_id = doc.get('mk_id') or doc.get('id') or doc.get('doc_id')
    try:
        resp = mk_change_document_status(
            status_code=status_code,
            doc_type='sales_order',
            mk_id=str(mk_id) if mk_id else None,
            buyer_order=clean,
        )
        return {
            'ok': True,
            'cancelled': True,
            'mk_id': str(mk_id) if mk_id else None,
            'prev_status': category,
            'response': resp,
        }
    except Exception as e:
        return {'ok': False, 'reason': f'change_document_status failed: {e}'}


def mk_print_bill_pdf(doc_type: str, mk_id: str, timeout: int = 45, *, locale: str | None = None, country: str | None = None) -> Optional[bytes]:
    """Request official PDF from MetaKocka using /report with dump params.

    Note: doc_type is ignored here per support. Required fields:
    - secret_key, company_id, mk_id, report_id, params
    Response with application/pdf is the PDF; JSON means error.
    """
    try:
        base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
        if not base or not company_id or not secret:
            current_app.logger.error('MK print: missing config (base/company_id/secret_key)')
            return None
        url = f"{base}/report"

        # report_id: default 38 as per support, overridable by env/config
        report_id = (
            current_app.config.get('MK_REPORT_ID')
            or os.environ.get('MK_REPORT_ID')
            or '38'
        )

        # Params from dump_for_report_rest (either a list or an object with params: [])
        raw_params_json = (
            current_app.config.get('MK_REPORT_PARAMS_JSON')
            or os.environ.get('MK_REPORT_PARAMS_JSON')
        )
        params_list = []
        if raw_params_json:
            try:
                parsed = _json.loads(raw_params_json)
                if isinstance(parsed, list):
                    params_list = parsed
                elif isinstance(parsed, dict) and isinstance(parsed.get('params'), list):
                    params_list = parsed['params']
            except Exception as e:
                current_app.logger.warning(f"MK print: could not parse MK_REPORT_PARAMS_JSON, using minimal params: {e}")
                params_list = []

        # Ensure mandatory entries exist
        def ensure_param(params_arr, key, value):
            try:
                for p in params_arr:
                    if isinstance(p, dict) and p.get('type') == key:
                        return
            except Exception:
                pass
            params_arr.append({'type': key, 'value': value})

        ensure_param(params_list, 'REPORT_TYPE', 'PDF')

        # Optional locale/country hints can be carried via params as per support
        # Locale/country per request has priority; else fallback to config/env
        req_locale = (locale or '').strip() or current_app.config.get('MK_PRINT_LOCALE') or os.environ.get('MK_PRINT_LOCALE')
        req_country = (country or '').strip() or current_app.config.get('MK_PRINT_COUNTRY') or os.environ.get('MK_PRINT_COUNTRY')
        if req_locale:
            ensure_param(params_list, 'ADD_ATT_HIDDEN_DEFAULT_LOCALE', str(req_locale))
        if req_country:
            ensure_param(params_list, 'ADD_ATT_HIDDEN_MK_COUNTRY', str(req_country).lower())

        payload = {
            'secret_key': str(secret),
            'company_id': str(company_id),
            'mk_id': str(mk_id),
            'report_id': str(report_id),
            'params': params_list,
        }

        resp = requests.post(url, json=payload, timeout=timeout)
        if not resp.ok:
            current_app.logger.error(f"MK print HTTP {resp.status_code}: {resp.text[:300]}")
            return None
        ctype = (resp.headers.get('Content-Type') or '').lower()
        if 'application/pdf' in ctype:
            return resp.content
        # JSON means error description
        try:
            err = resp.json()
            current_app.logger.error(f"MK print returned JSON instead of PDF: {err}")
        except Exception:
            current_app.logger.error(f"MK print unexpected content-type {ctype}")
        return None
    except Exception as e:
        current_app.logger.error(f"MK print error for {mk_id}: {e}")
        return None


# ===================== BILL IMPORT/SYNC =====================

def _ensure_mk_bills_table():
    try:
        from database import get_db
        db = get_db(); c = db.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS mk_bills (
                mk_id TEXT PRIMARY KEY,
                doc_type TEXT,
                title TEXT,
                buyer_order TEXT,
                count_code TEXT,
                publish_ts TIMESTAMP NULL,
                furs_zoi TEXT,
                furs_eor TEXT,
                total NUMERIC NULL,
                created_ts TIMESTAMP NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_mk_bills_buyer_order ON mk_bills(buyer_order)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_mk_bills_count_code ON mk_bills(count_code)")
        db.commit(); c.close()
    except Exception as e:
        current_app.logger.error(f"mk_bills ensure table error: {e}")

# --- Presentation convenience: fetch last N presentable bills from mk_bill ---
def mk_fetch_presentable_bills(limit: int = 100) -> list[dict]:
    """Return last N bills from mk_bill filtered by presentation policy.
    Falls back to in-Python filtering when SQL-side retail detection is needed.
    """
    try:
        _ensure_mk_bill_tables()
        from database import get_db
        db = get_db(); c = db.cursor()
        # Fetch more than needed to allow Python-side retail detection when mode=retail_only
        take = max(100, int(limit) * 3)
        c.execute(
            """
            SELECT mk_id, document_number, publish_ts, currency_code, sum_eur, raw_json
            FROM mk_bill
            ORDER BY COALESCE(publish_ts, updated_at, NOW()) DESC
            LIMIT %s
            """,
            (take,)
        )
        rows = c.fetchall() or []
        try:
            c.close()
        except Exception:
            pass
        # Map to dicts uniformly (support psycopg2 tuples)
        bills: list[dict] = []
        for r in rows:
            try:
                if isinstance(r, dict):
                    jj = r.get('raw_json') or {}
                    doc = jj if isinstance(jj, dict) else (_json.loads(jj) if isinstance(jj, str) else {})
                    base = {
                        'mk_id': r.get('mk_id'),
                        'publish_ts': r.get('publish_ts'),
                        'sum_eur': r.get('sum_eur'),
                        'document_number': r.get('document_number'),
                    }
                else:
                    doc = {}
                    base = {
                        'mk_id': r[0],
                        'document_number': r[1],
                        'publish_ts': r[2],
                        'currency_code': r[3],
                        'sum_eur': r[4],
                    }
                merged = {**doc, **base}
                bills.append(merged)
            except Exception:
                continue
        pres = filter_bills_for_presentation(bills)
        return pres[:int(limit)]
    except Exception as e:
        try:
            current_app.logger.error(f"mk_fetch_presentable_bills error: {e}")
        except Exception:
            pass
        return []


def _ensure_mk_stock_events_table():
    """Create table to store MK stock webhook events (idempotent)."""
    try:
        from database import get_db
        db = get_db(); c = db.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS mk_stock_events (
                id SERIAL PRIMARY KEY,
                received_at TIMESTAMP DEFAULT NOW(),
                sku TEXT,
                quantity_delta NUMERIC NULL,
                warehouse TEXT NULL,
                doc_type TEXT NULL,
                mk_id TEXT NULL,
                payload JSONB
            );
            """
        )
        db.commit(); c.close()
    except Exception as e:
        current_app.logger.error(f"mk_stock_events ensure table error: {e}")


def mk_log_stock_event(payload: Dict[str, Any]) -> None:
    try:
        _ensure_mk_stock_events_table()
        from database import get_db
        db = get_db(); c = db.cursor()
        sku = str(payload.get('code') or payload.get('sku') or payload.get('product_code') or '').strip() or None
        qty = payload.get('quantity_delta') or payload.get('delta') or payload.get('change')
        wh = payload.get('warehouse') or payload.get('warehouse_code')
        doc_type = payload.get('doc_type') or None
        mk_id = payload.get('mk_id') or None
        c.execute(
            """
            INSERT INTO mk_stock_events (sku, quantity_delta, warehouse, doc_type, mk_id, payload)
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (sku, qty, wh, doc_type, mk_id, _json.dumps(payload))
        )
        db.commit(); c.close()
    except Exception as e:
        current_app.logger.error(f"mk_log_stock_event error: {e}")


def _import_by_skus_for_type(norm_skus: set[str], dt: str, days: int, page_size: int, max_scan: int) -> int:
    """Internal: import by SKUs for a single doc_type."""
    try:
        _ensure_mk_bills_table()
        from database import get_db
        db = get_db(); c = db.cursor()
        imported = 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
        url = f"{base}/search"
        # get total
        try:
            init = {
                'company_id': str(company_id), 'secret_key': str(secret), 'doc_type': dt,
                'offset': 0, 'limit': _mk_limit_for_doc_type(dt, 1), 'result_type': 'doc'
            }
            r0 = requests.post(url, json=init, timeout=int(current_app.config.get('MK_TIMEOUT', 15)))
            total = 0
            if r0.ok and r0.headers.get('Content-Type','').startswith('application/json'):
                d0 = r0.json() or {}
                try:
                    total = int(d0.get('result_all_records') or 0)
                except Exception:
                    total = 0
        except Exception:
            total = 0
        start = max((total or 0) - int(max_scan), 0)
        offset = start
        while offset < (total or (start + max_scan)):
            payload = {
                'company_id': str(company_id), 'secret_key': str(secret), 'doc_type': dt,
                'offset': int(offset), 'limit': _mk_limit_for_doc_type(dt, page_size), 'result_type': 'doc'
            }
            r = requests.post(url, json=payload, timeout=int(current_app.config.get('MK_TIMEOUT', 20)))
            if not r.ok:
                break
            data = r.json() if r.headers.get('Content-Type','').startswith('application/json') else {}
            rows = []
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                rows = data.get('rows') or data.get('result') or data.get('documents') or []
            if not rows:
                break
            for rrow in rows:
                mk_id = rrow.get('mk_id') or rrow.get('id') or rrow.get('doc_id')
                if not mk_id:
                    continue
                d = mk_get_document(dt, str(mk_id)) or {}
                ts_ref = _extract_bill_ts(d)
                if not ts_ref or ts_ref < cutoff:
                    continue
                # look for SKU in product_list
                plist = d.get('product_list') or []
                found = False
                for pit in plist:
                    code = str((pit.get('code') or pit.get('sku') or '')).strip()
                    if code and code in norm_skus:
                        found = True
                        break
                if not found:
                    continue
                pub_ts = _parse_iso(d.get('publish_ts'))
                created_ts = _parse_iso(d.get('created_ts') or d.get('created_at'))
                c.execute(
                    """
                    INSERT INTO mk_bills (mk_id, doc_type, title, buyer_order, count_code, publish_ts, furs_zoi, furs_eor, total, created_ts, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                    ON CONFLICT (mk_id) DO UPDATE SET
                      doc_type = EXCLUDED.doc_type,
                      title = EXCLUDED.title,
                      buyer_order = EXCLUDED.buyer_order,
                      count_code = EXCLUDED.count_code,
                      publish_ts = COALESCE(EXCLUDED.publish_ts, mk_bills.publish_ts),
                      furs_zoi = COALESCE(EXCLUDED.furs_zoi, mk_bills.furs_zoi),
                      furs_eor = COALESCE(EXCLUDED.furs_eor, mk_bills.furs_eor),
                      total = COALESCE(EXCLUDED.total, mk_bills.total),
                      created_ts = COALESCE(EXCLUDED.created_ts, mk_bills.created_ts),
                      updated_at = NOW()
                    """,
                    (
                        str(d.get('mk_id') or mk_id), dt,
                        d.get('title'), d.get('buyer_order'), d.get('count_code'),
                        pub_ts, d.get('furs_zoi'), d.get('furs_eor'), d.get('total'), created_ts
                    )
                )
                # Apply procurement increments for webhook-driven imports as well (non-MISTRAL/FLORGARDEN only)
                try:
                    _apply_procurement_from_bill(c, d)
                    try:
                        app_log('procurement.apply', 'info', 'Applied procurement from MK bill', {
                            'mk_id': d.get('mk_id'),
                            'doc_type': dt,
                            'buyer_order': d.get('buyer_order'),
                            'count_code': d.get('count_code')
                        })
                    except Exception:
                        pass
                except Exception as _pe:
                    current_app.logger.error(f"procurement apply (webhook import) error: {_pe}")
                imported += 1
            db.commit()
            offset += len(rows)
            if offset - start >= max_scan:
                break
        c.close()
        return imported
    except Exception as e:
        current_app.logger.error(f"_import_by_skus_for_type({dt}) error: {e}")
        return 0


def mk_import_by_skus(skus: list[str], days: int = 3, page_size: int = 100, max_scan: int = 2000, doc_types: list[str] | None = None) -> int:
    """Import recent sales bills that include any of the provided SKUs, across specified types.

    Defaults to all sales bill types; scans tail pages with result_type=doc and filters by SKU and recency.
    """
    if not skus:
        return 0
    norm_skus = {str(s).strip() for s in skus if str(s).strip()}
    if not norm_skus:
        return 0
    types = list(doc_types) if doc_types else _mk_sales_doc_types()
    total_imported = 0
    for dt in types:
        total_imported += _import_by_skus_for_type(norm_skus, dt, days, page_size, max_scan)
    return total_imported


def mk_import_retail_by_skus(skus: list[str], days: int = 3, page_size: int = 100, max_scan: int = 2000) -> int:
    """Backward-compat wrapper: only retail."""
    return mk_import_by_skus(skus, days=days, page_size=page_size, max_scan=max_scan, doc_types=['sales_bill_retail'])
def _ensure_procurement_tables(c=None):
    """Ensure procurement tables for non-MISTRAL/FLORGARDEN SKU-based items exist.

    Mirrors definitions in API routes to avoid import cycles.
    """
    try:
        if c is None:
            from database import get_db
            db = get_db(); c = db.cursor()
            owns_cursor = True
        else:
            owns_cursor = False
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS proc_suppliers (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL
            );
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS proc_products (
                id SERIAL PRIMARY KEY,
                supplier_id INTEGER NOT NULL REFERENCES proc_suppliers(id) ON DELETE CASCADE,
                sku TEXT NOT NULL,
                name TEXT NOT NULL,
                unit TEXT DEFAULT 'kos',
                price NUMERIC(12,2) DEFAULT 0,
                min_on_hand INTEGER DEFAULT 0,
                on_hand INTEGER DEFAULT 0,
                pending INTEGER DEFAULT 0,
                committed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(supplier_id, sku)
            );
            """
        )
        if owns_cursor:
            c.connection.commit(); c.close()
    except Exception as e:
        current_app.logger.error(f"procurement ensure tables error: {e}")


def _ensure_proc_applied_table(c=None):
    """Idempotency table to track which (mk_id, sku) were applied to procurement."""
    try:
        if c is None:
            from database import get_db
            db = get_db(); c = db.cursor()
            owns_cursor = True
        else:
            owns_cursor = False
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS proc_applied_from_mk (
                mk_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                qty INTEGER NOT NULL,
                applied_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (mk_id, sku)
            );
            """
        )
        if owns_cursor:
            c.connection.commit(); c.close()
    except Exception as e:
        current_app.logger.error(f"proc_applied_from_mk ensure table error: {e}")


def _to_int_quantity(val) -> int:
    try:
        if val is None:
            return 0
        # MK often provides amounts as strings
        return int(round(float(str(val).replace(',', '.'))))
    except Exception:
        return 0


def _apply_procurement_from_bill(c, bill: Dict[str, Any]):
    """Decrement procurement on_hand by bill product amounts for non MISTRAL/FLORGARDEN SKUs.

    - Uses proc_products.sku to match imported items
    - Excludes suppliers named MISTRAL or FLORGARDEN (perfumes use perfumes_stock)
    - Idempotent via proc_applied_from_mk (mk_id, sku)
    - Writes audit entry to proc_stock_movements via services.proc_stock helper
    """
    try:
        # Only apply for published bills
        if not mk_is_published(bill):
            return
        mk_id = str(bill.get('mk_id') or '').strip()
        if not mk_id:
            return
        # Optional cutoff date for applying procurement from retail bills
        cutoff_str = os.getenv('PROCUREMENT_APPLY_FROM_DATE') or ''
        if cutoff_str:
            try:
                cutoff_date = datetime.strptime(cutoff_str[:10], '%Y-%m-%d').date()
                pub_ts = _as_utc_publish_ts(bill)
                if pub_ts and pub_ts.date() < cutoff_date:
                    return
            except Exception:
                pass
        items = bill.get('product_list') or []
        if not items:
            return

        # Savepoint: morebitna napaka pri procurementu (npr. manjkajoča tabela
        # proc_stock_movements) NE sme prekiniti zunanje transakcije (uvoz
        # računov v mk_bills). Brez tega bi en sam fail aborti-ral cel scan.
        with c.connection.transaction():
            _ensure_procurement_tables(c)
            _ensure_proc_applied_table(c)

            # Aggregate quantities per SKU within the bill
            sku_to_qty: Dict[str, int] = {}
            for it in items:
                # MK polja za SKU se razlikujejo med tipi; pokrij več variant
                sku = str((it.get('product_code') or it.get('code') or it.get('count_code') or it.get('sku') or '')).strip().upper()
                if not sku:
                    try:
                        app_log('procurement.apply', 'info', 'SKU missing on bill item', {'mk_id': mk_id, 'item': str(it)[:160]})
                    except Exception:
                        pass
                    continue
                raw_qty = _to_int_quantity(it.get('quantity') or it.get('qty') or it.get('amount'))
                qty = int(raw_qty)
                if qty <= 0:
                    continue
                sku_to_qty[sku] = sku_to_qty.get(sku, 0) + qty

            if not sku_to_qty:
                return

            from services.proc_stock import apply_decrement

            for sku, qty in sku_to_qty.items():
                c.execute("SELECT 1 FROM proc_applied_from_mk WHERE mk_id = %s AND sku = %s", (mk_id, sku))
                if c.fetchone():
                    continue
                res = apply_decrement(
                    c, sku, int(qty),
                    source='mk_bill', source_ref=mk_id,
                    note=f"bill {mk_id}"
                )
                if not res.get('applied'):
                    continue
                c.execute(
                    """
                    INSERT INTO proc_applied_from_mk (mk_id, sku, qty)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (mk_id, sku) DO NOTHING
                    """,
                    (mk_id, sku, int(qty))
                )
                try:
                    app_log('procurement.apply', 'info', 'on_hand decrement (mk_bill)', {
                        'mk_id': mk_id,
                        'sku': sku,
                        'qty': int(qty),
                        'on_hand_before': res.get('on_hand_before'),
                        'on_hand_after': res.get('on_hand_after'),
                        'pending_before': res.get('pending_before'),
                        'pending_after': res.get('pending_after'),
                    })
                except Exception:
                    pass
    except Exception as e:
        current_app.logger.error(f"apply procurement from MK bill error: {e}")


def mk_apply_procurement_from_stock_list(stock_list):
    """Apply procurement on_hand decrement directly from MK stock webhook stock_list.

    - Only applies when amount < 0 (stock decrease / sale)
    - Matches on `proc_products.sku`
    - Skips suppliers MISTRAL and FLORGARDEN (perfumes use perfumes_stock)
    - Idempotent by (mk_id, sku) using `proc_applied_from_mk`
    - Writes audit entry to proc_stock_movements via services.proc_stock helper
    Returns number of products decremented.
    """
    try:
        if not isinstance(stock_list, list) or not stock_list:
            return 0
        from database import get_db
        from services.proc_stock import apply_decrement
        db = get_db(); c = db.cursor()
        _ensure_procurement_tables(c)
        _ensure_proc_applied_table(c)
        total_updates = 0
        for it in stock_list:
            if not isinstance(it, dict):
                continue
            sku = str((it.get('code') or it.get('count_code') or '')).strip()
            if not sku:
                continue
            raw = _to_int_quantity(it.get('amount'))
            if raw >= 0:
                continue
            qty = abs(int(raw))
            if qty <= 0:
                continue
            mk_id = str(it.get('mk_id') or '').strip()
            if mk_id:
                c.execute("SELECT 1 FROM proc_applied_from_mk WHERE mk_id = %s AND sku = %s", (mk_id, sku))
                if c.fetchone():
                    continue
            res = apply_decrement(
                c, sku, int(qty),
                source='mk_stock_webhook', source_ref=mk_id or None,
                note='mk stock webhook'
            )
            if not res.get('applied'):
                continue
            total_updates += 1
            if mk_id:
                c.execute(
                    """
                    INSERT INTO proc_applied_from_mk (mk_id, sku, qty)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (mk_id, sku) DO NOTHING
                    """,
                    (mk_id, sku, int(qty))
                )
            try:
                app_log('procurement.apply', 'info', 'on_hand decrement (mk_stock_webhook)', {
                    'mk_id': mk_id,
                    'sku': sku,
                    'qty': int(qty),
                    'on_hand_before': res.get('on_hand_before'),
                    'on_hand_after': res.get('on_hand_after'),
                    'pending_before': res.get('pending_before'),
                    'pending_after': res.get('pending_after'),
                })
            except Exception:
                pass
        db.commit(); c.close()
        return total_updates
    except Exception as e:
        try:
            current_app.logger.error(f"mk_apply_procurement_from_stock_list error: {e}")
        except Exception:
            pass
        return 0


def mk_apply_procurement_from_mk_ids(stock_list):
    """Fetch bills by mk_id from stock_list and apply procurement using exact product_list quantities.

    Args:
        stock_list: list of dicts from webhook payload (expects mk_id field per item)

    Returns:
        Number of bills successfully processed (applied or already idempotent)
    """
    try:
        if not isinstance(stock_list, list) or not stock_list:
            return 0
        mk_ids = []
        for it in stock_list:
            if not isinstance(it, dict):
                continue
            sid = str(it.get('mk_id') or '').strip()
            if sid:
                mk_ids.append(sid)
        uniq_ids = list(dict.fromkeys(mk_ids))
        if not uniq_ids:
            return 0
        from database import get_db
        db = get_db(); c = db.cursor()
        _ensure_procurement_tables(c)
        _ensure_proc_applied_table(c)
        types = _mk_sales_doc_types()
        processed = 0
        for mk_id in uniq_ids:
            bill = None
            bill_type = None
            for dt in types:
                try:
                    d = mk_get_document(dt, str(mk_id)) or {}
                except Exception:
                    d = {}
                if d and d.get('product_list'):
                    bill = d
                    bill_type = dt
                    break
            if not bill:
                continue
            # Upsert into mk_bills so retail bills also appear in UI
            try:
                _ensure_mk_bills_table()
                pub_ts = _parse_iso(bill.get('publish_ts'))
                created_ts = _parse_iso(bill.get('created_ts') or bill.get('created_at'))
                c.execute(
                    """
                    INSERT INTO mk_bills (mk_id, doc_type, title, buyer_order, count_code, publish_ts, furs_zoi, furs_eor, total, created_ts, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                    ON CONFLICT (mk_id) DO UPDATE SET
                      doc_type = EXCLUDED.doc_type,
                      title = EXCLUDED.title,
                      buyer_order = EXCLUDED.buyer_order,
                      count_code = EXCLUDED.count_code,
                      publish_ts = COALESCE(EXCLUDED.publish_ts, mk_bills.publish_ts),
                      furs_zoi = COALESCE(EXCLUDED.furs_zoi, mk_bills.furs_zoi),
                      furs_eor = COALESCE(EXCLUDED.furs_eor, mk_bills.furs_eor),
                      total = COALESCE(EXCLUDED.total, mk_bills.total),
                      created_ts = COALESCE(EXCLUDED.created_ts, mk_bills.created_ts),
                      updated_at = NOW()
                    """,
                    (
                        str(bill.get('mk_id') or mk_id), bill_type or bill.get('doc_type'),
                        bill.get('title'), bill.get('buyer_order'), bill.get('count_code'),
                        pub_ts, bill.get('furs_zoi'), bill.get('furs_eor'), bill.get('total'), created_ts
                    )
                )
            except Exception as _up:
                try:
                    current_app.logger.warning(f"mk_bills upsert by mk_id failed: {_up}")
                except Exception:
                    pass
            try:
                _apply_procurement_from_bill(c, bill)
                processed += 1
                try:
                    app_log('procurement.apply', 'info', 'Applied from bill by mk_id', {
                        'mk_id': mk_id,
                        'has_items': bool(bill.get('product_list'))
                    })
                except Exception:
                    pass
            except Exception:
                continue
        db.commit(); c.close()
        return processed
    except Exception as e:
        try:
            current_app.logger.error(f"mk_apply_procurement_from_mk_ids error: {e}")
        except Exception:
            pass
        return 0

def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    s = str(ts).strip()
    if not s:
        return None
    try:
        # Support epoch timestamps (ms or seconds)
        if s.lstrip('-').isdigit():
            try:
                val = int(s)
                # Heuristic: >= 10^12 -> milliseconds
                if abs(val) >= 10**12:
                    return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
                # else treat as seconds
                return datetime.fromtimestamp(val, tz=timezone.utc)
            except Exception:
                pass
        # Normalize 'Z' suffix
        s2 = s.replace('Z', '+00:00')
        # If there's a timezone offset but no time component (e.g., '2025-08-22+02:00'), inject midnight
        if ('+' in s2 or '-' in s2[10:]) and 'T' not in s2 and len(s2) >= 16 and s2[4] == '-' and s2[7] == '-':
            # split at last +/- occurrence after the date
            # find offset start (first + or - after index 10)
            off_idx = max(s2.find('+', 10), s2.find('-', 10))
            if off_idx > 0:
                date_part = s2[:10]
                off_part = s2[off_idx:]
                s2 = f"{date_part}T00:00:00{off_part}"
        # If only date provided, add midnight
        if len(s2) == 10 and s2[4] == '-' and s2[7] == '-':
            s2 = s2 + 'T00:00:00'
        return datetime.fromisoformat(s2)
    except Exception:
        # Try replacing space with 'T'
        try:
            return datetime.fromisoformat(s.replace(' ', 'T'))
        except Exception:
            return None


def _extract_bill_ts(d: Dict[str, Any]) -> Optional[datetime]:
    """Extract best available timestamp for bill recency filtering.

    For retail reliability, prefer publish_ts/created_* and ignore doc_date/service_to_date.
    """
    # Extended support for MK variants (epoch/alt fields): ts, time, created, updated_at, modified_ts
    def _to_utc(tsv: Optional[datetime]) -> Optional[datetime]:
        try:
            if not tsv:
                return None
            if tsv.tzinfo is None:
                return tsv.replace(tzinfo=timezone.utc)
            return tsv.astimezone(timezone.utc)
        except Exception:
            return None

    candidate_keys = [
        'publish_ts',
        'created_ts', 'created_at',
        # intentionally skip doc_date/service_to_date for recency decisions
        'ts', 'time', 'created', 'updated_at', 'modified_ts'
    ]
    for key in candidate_keys:
        try:
            val = d.get(key)
        except Exception:
            val = None
        ts = _parse_iso(val) if val is not None else None
        if ts:
            return _to_utc(ts)
    return None


def mk_sync_bills(days: int = 1, max_scan_per_type: int = 3000, page_size: int = 200, doc_types: list[str] | None = None, seed_mk_ids: list[str] | None = None) -> int:
    """Import recent bills into mk_bills by scanning MetaKocka search and fetching full docs.

    Scans across doc types and upserts by mk_id. Filters by publish_ts/created_ts in the last `days`.
    Returns: number of bills upserted.
    """
    try:
        _ensure_mk_bills_table()
        from database import get_db
        db = get_db(); c = db.cursor()
        imported = 0
        types = list(doc_types) if doc_types else _mk_sales_doc_types()
        counts_by_type = {t: 0 for t in types}
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
        url = f"{base}/search"
        # Precompute recent local order refs for retail filtering
        recent_basic_refs: set[str] = set()
        recent_digit_refs: set[str] = set()
        try:
            rb, rd = _build_recent_order_refs(days)
            recent_basic_refs, recent_digit_refs = rb, rd
        except Exception:
            recent_basic_refs, recent_digit_refs = set(), set()

        for dt in types:
            try:
                # Najprej pridobi total število zapisov
                payload0 = {
                    'company_id': str(company_id),
                    'secret_key': str(secret),
                    'doc_type': dt,
                    'offset': 0,
                    'limit': _mk_limit_for_doc_type(dt, 1)
                }
                # Some tenants/types (notably retail) may not support result_type=doc reliably
                if dt not in ('sales_bill_retail', 'bill'):
                    payload0['result_type'] = 'doc'
                resp0 = requests.post(url, json=payload0, timeout=int(current_app.config.get('MK_TIMEOUT', 15)))
                if not resp0.ok:
                    current_app.logger.warning(f"MK search init HTTP {resp0.status_code} for {dt}: {resp0.text[:200]}")
                    continue
                data0 = resp0.json() if resp0.headers.get('Content-Type','').startswith('application/json') else {}
                total = 0
                if isinstance(data0, dict):
                    try:
                        total = int(data0.get('result_all_records') or 0)
                    except Exception:
                        total = 0
                # Diagnostics for retail
                try:
                    if dt == 'sales_bill_retail':
                        app_log('diag.retail_search_init', 'info', 'Retail search init', {
                            'total': total,
                            'has_rows_key': bool(data0.get('rows')) if isinstance(data0, dict) else None,
                            'keys': list(data0.keys())[:10] if isinstance(data0, dict) else None
                        })
                except Exception:
                    pass

                # Robust tail finder: exponential probe then binary search to last non-empty page
                def _find_tail_start() -> int:
                    try:
                        def has_rows(at_offset: int) -> bool:
                            pld = {
                                'company_id': str(company_id),
                                'secret_key': str(secret),
                                'doc_type': dt,
                                'offset': int(at_offset),
                                'limit': _mk_limit_for_doc_type(dt, page_size)
                            }
                            if dt not in ('sales_bill_retail', 'bill'):
                                pld['result_type'] = 'doc'
                            r = requests.post(url, json=pld, timeout=int(current_app.config.get('MK_TIMEOUT', 15)))
                            if not r.ok:
                                return False
                            djson = r.json() if r.headers.get('Content-Type','').startswith('application/json') else {}
                            if isinstance(djson, list):
                                return len(djson) > 0
                            if isinstance(djson, dict):
                                rows_probe = djson.get('rows') or djson.get('result') or djson.get('documents') or []
                                return bool(rows_probe)
                            return False

                        # Ensure starting point
                        lo = 0
                        if not has_rows(lo):
                            return 0
                        # Exponential growth to find an upper bound with no rows
                        step = page_size * 4
                        hi = step
                        tries = 0
                        while has_rows(hi) and tries < 64 and (hi - lo) <= (max_scan_per_type * 8):
                            lo = hi
                            hi += step
                            tries += 1
                        # Binary search between lo (non-empty) and hi (empty or far)
                        left = lo
                        right = hi
                        while right - left > page_size:
                            mid = left + ((right - left) // 2)
                            if has_rows(mid):
                                left = mid
                            else:
                                right = mid
                        last_page_offset = left
                        return max(0, last_page_offset - max_scan_per_type)
                    except Exception:
                        return 0

                # For retail, request newest first by opr_time and start from 0
                if dt == 'sales_bill_retail':
                    start = 0
                else:
                    if total <= 0:
                        start = _find_tail_start()
                    else:
                        start = max(total - max_scan_per_type, 0)
                offset = start
                try:
                    current_app.config['MK_SYNC_PROGRESS'] = {
                        'phase': 'tail_scan',
                        'doc_type': dt,
                        'total_records': total,
                        'start_offset': start,
                        'offset': offset,
                        'page_size': int(page_size),
                        'imported': imported
                    }
                except Exception:
                    pass
                scanned_rows = 0
                # Track whether we actually imported any recent retail bills
                retail_recent_found = False
                # Če total znan: pogojuj z njim, sicer skeniraj do max_scan_per_type
                while (total > 0 and offset < total) or (total <= 0 and scanned_rows < int(max_scan_per_type)):
                    # Cancel check
                    if current_app.config.get('MK_SYNC_CANCEL'):
                        return imported
                    payload = {
                        'company_id': str(company_id),
                        'secret_key': str(secret),
                        'doc_type': dt,
                        'offset': int(offset),
                        'limit': _mk_limit_for_doc_type(dt, page_size)
                    }
                    # Retail: ask for newest first by opr_time (best-effort; API may ignore unknown keys)
                    if dt == 'sales_bill_retail':
                        payload.update({'order_by': 'opr_time', 'order': 'desc', 'sort': 'opr_time', 'sort_dir': 'desc'})
                    if dt not in ('sales_bill_retail', 'bill'):
                        payload['result_type'] = 'doc'
                    resp = requests.post(url, json=payload, timeout=int(current_app.config.get('MK_TIMEOUT', 20)))
                    if not resp.ok:
                        current_app.logger.warning(f"MK search page HTTP {resp.status_code} for {dt} (offset={offset}): {resp.text[:200]}")
                        break
                    data = resp.json() if resp.headers.get('Content-Type','').startswith('application/json') else {}
                    rows = []
                    if isinstance(data, list):
                        rows = data
                    elif isinstance(data, dict):
                        rows = data.get('rows') or data.get('result') or data.get('documents') or []
                    if not rows:
                        # no rows on this page; end if total is known; else stop if nothing returned
                        break
                    # Retail diagnostics: log the first page structure once
                    try:
                        if dt == 'sales_bill_retail' and offset == start:
                            sample = rows[0] if rows else {}
                            app_log('diag.retail_search_page', 'info', 'Retail search page sample', {
                                'offset': int(offset), 'limit': _mk_limit_for_doc_type(dt, page_size),
                                'row_keys': list(sample.keys())[:20] if isinstance(sample, dict) else None
                            })
                        
                    except Exception:
                        pass
                    for r in rows:
                        mk_id = r.get('mk_id') or r.get('id') or r.get('doc_id') or r.get('document_id')
                        if not mk_id:
                            continue
                        # Retail: use row-level opr_time for faster/accurate recency when available
                        if dt == 'sales_bill_retail':
                            try:
                                row_opr = _parse_iso(r.get('opr_time'))
                            except Exception:
                                row_opr = None
                            if row_opr and row_opr < cutoff:
                                continue
                        # Cancel check (tudi med get_document)
                        if current_app.config.get('MK_SYNC_CANCEL'):
                            return imported
                        d = mk_get_document(dt, str(mk_id)) or {}
                        try:
                            if dt == 'sales_bill_retail' and d and not d.get('product_list'):
                                app_log('diag.retail_get_document', 'warning', 'Retail get_document returned without product_list', {
                                    'mk_id': mk_id,
                                    'doc_type': dt,
                                    'doc_doc_type': d.get('doc_type')
                                })
                        except Exception:
                            pass
                        # Parse timestamps
                        publish_ts = _parse_iso(d.get('publish_ts'))
                        created_ts = _parse_iso(d.get('created_ts') or d.get('created_at'))
                        # Advanced cutoff: also consider doc_date/service_to_date for retail where publish/created missing
                        ts_ref = _extract_bill_ts(d)
                        if dt != 'sales_bill_retail':
                            if not ts_ref or ts_ref < cutoff:
                                continue
                        else:
                            # retail: require either doc ts >= cutoff or row_opr >= cutoff; otherwise skip
                            recent_ok = False
                            if ts_ref and ts_ref >= cutoff:
                                recent_ok = True
                            else:
                                try:
                                    if 'row_opr' in locals() and row_opr and row_opr >= cutoff:
                                        recent_ok = True
                                except Exception:
                                    pass
                            if not recent_ok:
                                continue
                        # For retail, import all recent docs (no Shopify order matching required)
                        c.execute(
                            """
                            INSERT INTO mk_bills (mk_id, doc_type, title, buyer_order, count_code, publish_ts, furs_zoi, furs_eor, total, created_ts, updated_at)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                            ON CONFLICT (mk_id) DO UPDATE SET
                              doc_type = EXCLUDED.doc_type,
                              title = EXCLUDED.title,
                              buyer_order = EXCLUDED.buyer_order,
                              count_code = EXCLUDED.count_code,
                              publish_ts = COALESCE(EXCLUDED.publish_ts, mk_bills.publish_ts),
                              furs_zoi = COALESCE(EXCLUDED.furs_zoi, mk_bills.furs_zoi),
                              furs_eor = COALESCE(EXCLUDED.furs_eor, mk_bills.furs_eor),
                              total = COALESCE(EXCLUDED.total, mk_bills.total),
                              created_ts = COALESCE(EXCLUDED.created_ts, mk_bills.created_ts),
                              updated_at = NOW()
                            """,
                            (
                                str(d.get('mk_id') or mk_id), dt,
                                d.get('title'), d.get('buyer_order'), d.get('count_code'),
                                publish_ts, d.get('furs_zoi'), d.get('furs_eor'), d.get('total'), created_ts
                            )
                        )
                        # Mark recent retail detection to avoid missing fresh records due to legacy fields
                        try:
                            if dt == 'sales_bill_retail':
                                recent_cutoff_detect = datetime.now(timezone.utc) - timedelta(days=max(3, int(current_app.config.get('MK_RETAIL_RECENT_DAYS', 7))))
                                if ts_ref >= recent_cutoff_detect:
                                    retail_recent_found = True
                        except Exception:
                            pass
                        # Apply procurement pending increments for non-MISTRAL/FLORGARDEN SKUs (idempotent)
                        try:
                            _apply_procurement_from_bill(c, d)
                        except Exception as _pe:
                            current_app.logger.error(f"procurement apply hook error: {_pe}")
                        imported += 1
                        counts_by_type[dt] = counts_by_type.get(dt, 0) + 1
                        try:
                            prog = current_app.config.get('MK_SYNC_PROGRESS', {}) or {}
                            prog.update({'offset': offset, 'imported': imported, 'doc_type': dt, 'counts_by_type': counts_by_type})
                            current_app.config['MK_SYNC_PROGRESS'] = prog
                        except Exception:
                            pass
                    db.commit()
                    rows_count = len(rows)
                    offset += rows_count
                    scanned_rows += rows_count
            except Exception as e:
                current_app.logger.error(f"mk_sync_bills scan error for {dt}: {e}")
            # Retail fallback: če nismo uvozili nobenega NEDAVNEGA retail računa, prisilno preglej zadnjih ~1000 zapisov in vzemi tiste v zadnjih 7 dneh
            try:
                if dt == 'sales_bill_retail' and not retail_recent_found:
                    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=max(3, int(current_app.config.get('MK_RETAIL_RECENT_DAYS', 7))))
                    tail_start = max((total or 0) - 1000, 0)
                    off2 = tail_start
                    fetched = 0
                    while fetched < 1000:
                        payload = {
                            'company_id': str(company_id),
                            'secret_key': str(secret),
                            'doc_type': dt,
                            'offset': int(off2),
                            'limit': _mk_limit_for_doc_type(dt, page_size)
                        }
                        # Avoid forcing result_type for retail fallback as some tenants omit it
                        r2 = requests.post(url, json=payload, timeout=int(current_app.config.get('MK_TIMEOUT', 20)))
                        if not r2.ok:
                            break
                        data = r2.json() if r2.headers.get('Content-Type','').startswith('application/json') else {}
                        rows2 = []
                        if isinstance(data, list):
                            rows2 = data
                        elif isinstance(data, dict):
                            rows2 = data.get('rows') or data.get('result') or data.get('documents') or []
                        if not rows2:
                            break
                        for r in rows2:
                            mk_id = r.get('mk_id') or r.get('id') or r.get('doc_id') or r.get('document_id')
                            if not mk_id:
                                continue
                            # Retail generic fallback: use row-level opr_time if present
                            try:
                                row_opr = _parse_iso(r.get('opr_time'))
                            except Exception:
                                row_opr = None
                            if row_opr and row_opr < recent_cutoff:
                                continue
                            d = mk_get_document(dt, str(mk_id)) or {}
                            ts_ref = _extract_bill_ts(d)
                            if not ts_ref:
                                pass
                            if ts_ref < recent_cutoff:
                                continue
                            # For retail, import all recent docs (no Shopify order matching required)
                            pub_ts = _parse_iso(d.get('publish_ts'))
                            created_ts = _parse_iso(d.get('created_ts') or d.get('created_at'))
                            c.execute(
                                """
                                INSERT INTO mk_bills (mk_id, doc_type, title, buyer_order, count_code, publish_ts, furs_zoi, furs_eor, total, created_ts, updated_at)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                                ON CONFLICT (mk_id) DO UPDATE SET
                                  doc_type = EXCLUDED.doc_type,
                                  title = EXCLUDED.title,
                                  buyer_order = EXCLUDED.buyer_order,
                                  count_code = EXCLUDED.count_code,
                                  publish_ts = COALESCE(EXCLUDED.publish_ts, mk_bills.publish_ts),
                                  furs_zoi = COALESCE(EXCLUDED.furs_zoi, mk_bills.furs_zoi),
                                  furs_eor = COALESCE(EXCLUDED.furs_eor, mk_bills.furs_eor),
                                  total = COALESCE(EXCLUDED.total, mk_bills.total),
                                  created_ts = COALESCE(EXCLUDED.created_ts, mk_bills.created_ts),
                                  updated_at = NOW()
                                """,
                                (
                                    str(d.get('mk_id') or mk_id), dt,
                                    d.get('title'), d.get('buyer_order'), d.get('count_code'),
                                    pub_ts, d.get('furs_zoi'), d.get('furs_eor'), d.get('total'), created_ts
                                )
                            )
                            imported += 1
                            counts_by_type[dt] = counts_by_type.get(dt, 0) + 1
                        db.commit()
                        fetched += len(rows2)
                        off2 += len(rows2)
            except Exception as e:
                current_app.logger.error(f"mk_sync_bills retail fallback error: {e}")
            # Retail ultimate fallback: scan recent by mk_id using get_document_bill
            try:
                if dt == 'sales_bill_retail' and counts_by_type.get(dt, 0) == 0:
                    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
                    # Determine starting mk_id(s)
                    start_candidates: list[int] = []
                    seed_set = set(str(s) for s in (seed_mk_ids or []))
                    # include seed ids if provided
                    try:
                        for sid in (seed_mk_ids or []):
                            if str(sid).isdigit():
                                start_candidates.append(int(str(sid)))
                    except Exception:
                        pass
                    start_id = None
                    try:
                        c.execute("SELECT MAX((mk_id)::bigint) FROM mk_bills WHERE mk_id ~ '^[0-9]+'")
                        row = c.fetchone()
                        max_db = int(row[0]) if row and row[0] is not None else None
                    except Exception:
                        max_db = None
                    try:
                        c.execute("SELECT MAX((mk_id)::bigint) FROM mk_stock_events WHERE mk_id ~ '^[0-9]+'")
                        row2 = c.fetchone()
                        max_ev = int(row2[0]) if row2 and row2[0] is not None else None
                    except Exception:
                        max_ev = None
                    for x in (max_db, max_ev):
                        if isinstance(x, int):
                            start_candidates.append(x)
                    start_id = max(start_candidates) if start_candidates else None
                    # If still unknown, fetch first page of generic 'bill' ordered by newest
                    if start_id is None:
                        try:
                            base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
                            urlg = f"{base}/search"
                            payloadg = {
                                'company_id': str(company_id), 'secret_key': str(secret), 'doc_type': 'bill',
                                'offset': 0, 'limit': 100, 'order_by': 'opr_time', 'order': 'desc', 'sort': 'opr_time', 'sort_dir': 'desc'
                            }
                            rg = requests.post(urlg, json=payloadg, timeout=int(current_app.config.get('MK_TIMEOUT', 15)))
                            if rg.ok:
                                dj = rg.json() if rg.headers.get('Content-Type','').startswith('application/json') else {}
                                rowsg = []
                                if isinstance(dj, list):
                                    rowsg = dj
                                elif isinstance(dj, dict):
                                    rowsg = dj.get('rows') or dj.get('result') or dj.get('documents') or []
                                for rr in rowsg:
                                    try:
                                        sid = rr.get('mk_id') or rr.get('id') or rr.get('doc_id') or rr.get('document_id')
                                        val = int(str(sid)) if str(sid).isdigit() else None
                                        if isinstance(val, int):
                                            start_id = val if start_id is None else max(start_id, val)
                                    except Exception:
                                        continue
                        except Exception:
                            pass
                    if start_id is not None:
                        window = int(current_app.config.get('MK_RETAIL_ID_SCAN_BACK', 500))
                        scanned = 0
                        # Build unique list of ids to scan: around each seed and the start_id tail
                        ids_to_scan: list[int] = []
                        anchor_ids = sorted(set([start_id] + [v for v in start_candidates if isinstance(v, int)]), reverse=True)
                        for anchor in anchor_ids:
                            for delta in range(0, window):
                                mkid = anchor - delta
                                if mkid <= 0:
                                    break
                                ids_to_scan.append(mkid)
                        # dedupe preserving order
                        seen = set()
                        uniq_ids_scan = []
                        for i in ids_to_scan:
                            if i in seen:
                                continue
                            seen.add(i); uniq_ids_scan.append(i)
                        for mkid in uniq_ids_scan:
                            if mkid <= 0:
                                break
                            d = mk_get_document_bill(str(mkid)) or {}
                            if not d or not d.get('mk_id'):
                                # try explicit retail get_document as fallback
                                try:
                                    d = mk_get_document('sales_bill_retail', str(mkid), extra={'show_product_list': 'true'}) or {}
                                except Exception:
                                    d = {}
                            try:
                                app_log('diag.retail_seed', 'info', 'Seed fetch result', {
                                    'mk_id': str(mkid),
                                    'found': bool(d and d.get('mk_id')),
                                    'doc_type': d.get('doc_type') if isinstance(d, dict) else None,
                                })
                            except Exception:
                                pass
                            if not d:
                                continue
                            doc_type_val = (d.get('doc_type') or '').lower()
                            if 'retail' not in doc_type_val and doc_type_val != 'sales_bill_retail':
                                continue
                            ts_ref = _extract_bill_ts(d)
                            # If seed ids provided, import retail regardless of timestamp to surface in UI
                            if not seed_set:
                                if not ts_ref or ts_ref < recent_cutoff:
                                    continue
                            pub_ts = _parse_iso(d.get('publish_ts'))
                            created_ts = _parse_iso(d.get('created_ts') or d.get('created_at'))
                            c.execute(
                                """
                                INSERT INTO mk_bills (mk_id, doc_type, title, buyer_order, count_code, publish_ts, furs_zoi, furs_eor, total, created_ts, updated_at)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                                ON CONFLICT (mk_id) DO UPDATE SET
                                  doc_type = EXCLUDED.doc_type,
                                  title = EXCLUDED.title,
                                  buyer_order = EXCLUDED.buyer_order,
                                  count_code = EXCLUDED.count_code,
                                  publish_ts = COALESCE(EXCLUDED.publish_ts, mk_bills.publish_ts),
                                  furs_zoi = COALESCE(EXCLUDED.furs_zoi, mk_bills.furs_zoi),
                                  furs_eor = COALESCE(EXCLUDED.furs_eor, mk_bills.furs_eor),
                                  total = COALESCE(EXCLUDED.total, mk_bills.total),
                                  created_ts = COALESCE(EXCLUDED.created_ts, mk_bills.created_ts),
                                  updated_at = NOW()
                                """,
                                (
                                    str(d.get('mk_id') or mkid), 'sales_bill_retail',
                                    d.get('title'), d.get('buyer_order'), d.get('count_code'),
                                    pub_ts, d.get('furs_zoi'), d.get('furs_eor'), d.get('total'), created_ts
                                )
                            )
                            try:
                                _apply_procurement_from_bill(c, d)
                            except Exception:
                                pass
                            imported += 1
                            counts_by_type['sales_bill_retail'] = counts_by_type.get('sales_bill_retail', 0) + 1
                            scanned += 1
                            if scanned >= 200:
                                break
                        db.commit()
            except Exception as e:
                current_app.logger.error(f"mk_sync_bills retail by id fallback error: {e}")
            # Retail generic fallback: if still nothing, scan generic 'bill' tail and resolve mk_id by trying types
            try:
                if dt == 'sales_bill_retail' and counts_by_type.get(dt, 0) == 0:
                    generic_total = 0
                    try:
                        payloadg0 = {
                            'company_id': str(company_id),
                            'secret_key': str(secret),
                            'doc_type': 'bill',
                            'offset': 0,
                            'limit': _mk_limit_for_doc_type('bill', 1)
                        }
                        rg0 = requests.post(url, json=payloadg0, timeout=int(current_app.config.get('MK_TIMEOUT', 15)))
                        if rg0.ok and rg0.headers.get('Content-Type','').startswith('application/json'):
                            dj0 = rg0.json() or {}
                            try:
                                generic_total = int(dj0.get('result_all_records') or 0)
                            except Exception:
                                generic_total = 0
                    except Exception:
                        generic_total = 0
                    tail_start = max((generic_total or 0) - 1000, 0)
                    offg = tail_start
                    fetched = 0
                    type_candidates = ['sales_bill_retail','sales_bill_domestic','sales_bill_foreign','sales_bill_prepaid','sales_bill','bill']
                    while fetched < 1000:
                        payloadg = {
                            'company_id': str(company_id),
                            'secret_key': str(secret),
                            'doc_type': 'bill',
                            'offset': int(offg),
                            'limit': _mk_limit_for_doc_type('bill', page_size)
                        }
                        # Prefer newest first for generic bill too (if API supports)
                        payloadg.update({'order_by': 'opr_time', 'order': 'desc', 'sort': 'opr_time', 'sort_dir': 'desc'})
                        rg = requests.post(url, json=payloadg, timeout=int(current_app.config.get('MK_TIMEOUT', 20)))
                        if not rg.ok:
                            break
                        dj = rg.json() if rg.headers.get('Content-Type','').startswith('application/json') else {}
                        rowsg = []
                        if isinstance(dj, list):
                            rowsg = dj
                        elif isinstance(dj, dict):
                            rowsg = dj.get('rows') or dj.get('result') or dj.get('documents') or []
                        if not rowsg:
                            break
                        for rr in rowsg:
                            mk_id = rr.get('mk_id') or rr.get('id') or rr.get('doc_id') or rr.get('document_id')
                            if not mk_id:
                                continue
                            # Resolve actual doc by trying candidate types
                            doc = None
                            real_type = None
                            for cand in type_candidates:
                                try:
                                    dtry = mk_get_document(cand, str(mk_id)) or {}
                                except Exception:
                                    dtry = {}
                                # Accept document even without product_list; we'll detect retail via doc_type
                                if dtry and (dtry.get('mk_id') or dtry.get('doc_type')):
                                    doc = dtry
                                    real_type = cand
                                    break
                            if not doc:
                                # try generic bill endpoint
                                dtry = mk_get_document_bill(str(mk_id)) or {}
                                if dtry and (dtry.get('mk_id') or dtry.get('doc_type')):
                                    doc = dtry
                                    real_type = (dtry.get('doc_type') or '').lower()
                            # Consider any document whose doc_type contains 'retail' as retail
                            if not doc:
                                continue
                            doc_doc_type = (doc.get('doc_type') or '').lower()
                            if real_type != 'sales_bill_retail' and 'retail' not in doc_doc_type:
                                continue
                            try:
                                if not doc.get('product_list'):
                                    app_log('diag.retail_generic_detect', 'info', 'Retail doc detected without product_list', {
                                        'mk_id': mk_id,
                                        'real_type': real_type,
                                        'doc_doc_type': doc.get('doc_type')
                                    })
                            except Exception:
                                pass
                            try:
                                app_log('diag.retail_generic_detect', 'info', 'Detected retail via generic bill scan', {
                                    'mk_id': mk_id,
                                    'real_type': real_type,
                                    'doc_doc_type': doc.get('doc_type')
                                })
                            except Exception:
                                pass
                            ts_ref = _extract_bill_ts(doc)
                            # For retail generic fallback: ignore recency entirely
                            pub_ts = _parse_iso(doc.get('publish_ts'))
                            created_ts = _parse_iso(doc.get('created_ts') or doc.get('created_at'))
                            c.execute(
                                """
                                INSERT INTO mk_bills (mk_id, doc_type, title, buyer_order, count_code, publish_ts, furs_zoi, furs_eor, total, created_ts, updated_at)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                                ON CONFLICT (mk_id) DO UPDATE SET
                                  doc_type = EXCLUDED.doc_type,
                                  title = EXCLUDED.title,
                                  buyer_order = EXCLUDED.buyer_order,
                                  count_code = EXCLUDED.count_code,
                                  publish_ts = COALESCE(EXCLUDED.publish_ts, mk_bills.publish_ts),
                                  furs_zoi = COALESCE(EXCLUDED.furs_zoi, mk_bills.furs_zoi),
                                  furs_eor = COALESCE(EXCLUDED.furs_eor, mk_bills.furs_eor),
                                  total = COALESCE(EXCLUDED.total, mk_bills.total),
                                  created_ts = COALESCE(EXCLUDED.created_ts, mk_bills.created_ts),
                                  updated_at = NOW()
                                """,
                                (
                                    str(doc.get('mk_id') or mk_id), 'sales_bill_retail',
                                    doc.get('title'), doc.get('buyer_order'), doc.get('count_code'),
                                    pub_ts, doc.get('furs_zoi'), doc.get('furs_eor'), doc.get('total'), created_ts
                                )
                            )
                            try:
                                _apply_procurement_from_bill(c, doc)
                            except Exception as _pe:
                                current_app.logger.error(f"procurement apply (generic retail fallback) error: {_pe}")
                            imported += 1
                            counts_by_type['sales_bill_retail'] = counts_by_type.get('sales_bill_retail', 0) + 1
                        db.commit()
                        step = len(rowsg)
                        fetched += step
                        offg += step
            except Exception as e:
                current_app.logger.error(f"mk_sync_bills retail generic fallback error: {e}")
        try:
            # Expose summary counts for status endpoint consumers
            current_app.config['MK_SYNC_PROGRESS'] = {
                'phase': 'tail_scan_finished',
                'imported': imported,
                'counts_by_type': counts_by_type
            }
        except Exception:
            pass
        try:
            c.close()
        except Exception:
            pass
        return imported
    except Exception as e:
        current_app.logger.error(f"mk_sync_bills fatal error: {e}")
        return 0


def mk_find_bill_in_db(order_ref: str) -> Optional[Dict[str, Any]]:
    """Find a bill in mk_bills for given order reference using same matching rules (title/buyer_order/count_code).
    Returns: {'mk_id': str, 'doc_type': str} or None.
    """
    try:
        from database import get_db
        db = get_db(); c = db.cursor()
        # Fetch candidates limiting to recent entries
        c.execute(
            """
            SELECT mk_id, doc_type, title, buyer_order, count_code, publish_ts
            FROM mk_bills
            WHERE publish_ts IS NULL OR publish_ts > NOW() - INTERVAL '365 days'
            ORDER BY publish_ts DESC NULLS LAST
            LIMIT 2000
            """
        )
        rows = c.fetchall() or []
        for r in rows:
            rd = r if isinstance(r, dict) else {
                'mk_id': r[0], 'doc_type': r[1], 'title': r[2], 'buyer_order': r[3], 'count_code': r[4], 'publish_ts': r[5]
            }
            if _matches_order_ref(rd, order_ref):
                return {'mk_id': str(rd.get('mk_id')), 'doc_type': rd.get('doc_type')}
        return None
    except Exception as e:
        current_app.logger.error(f"mk_find_bill_in_db error: {e}")
        return None


def mk_backfill_orders_bill_ids(days: int = 60) -> int:
    """Poveži že sinhronizirane MK račune (mk_bills) z naročili.

    Zapiše `orders.mk_bill_id` + `mk_bill_type` za naročila, ki ga še nimajo,
    z ujemanjem po title/buyer_order (skladno z `_matches_order_ref`). Čista
    SQL operacija — brez MK API klicev — zato je status MK računa znan takoj
    (brez potrebe po kliku/odpiranju PDF-ja). Ob več zadetkih izbere najnovejši
    račun (po publish_ts). Vrne število posodobljenih naročil.
    """
    try:
        from database import get_db
        db = get_db(); c = db.cursor()
        # Brez ALTER TABLE na pogosti poti (job teče vsakih 30 min) — stolpca sta
        # del sheme; ACCESS EXCLUSIVE lock bi povzročil lock pileup.
        c.execute(
            """
            WITH ranked AS (
                SELECT o.order_number AS onum,
                       b.mk_id AS mk_id,
                       b.doc_type AS doc_type,
                       ROW_NUMBER() OVER (
                           PARTITION BY o.order_number
                           ORDER BY b.publish_ts DESC NULLS LAST
                       ) AS rn
                FROM orders o
                JOIN mk_bills b
                  ON trim(both '#' from btrim(o.order_number)) =
                       trim(both '#' from btrim(COALESCE(b.title, '')))
                  OR trim(both '#' from btrim(o.order_number)) =
                       trim(both '#' from btrim(COALESCE(b.buyer_order, '')))
                WHERE o.mk_bill_id IS NULL
                  AND b.mk_id IS NOT NULL
                  AND trim(both '#' from btrim(o.order_number)) <> ''
                  AND COALESCE(o.fulfilled_at, o.created_at) > NOW() - make_interval(days => %s)
            )
            UPDATE orders o
            SET mk_bill_id = r.mk_id,
                mk_bill_type = NULLIF(r.doc_type, '')
            FROM ranked r
            WHERE o.order_number = r.onum AND r.rn = 1
            """,
            (int(days),),
        )
        updated = c.rowcount or 0
        db.commit()
        try:
            current_app.logger.info(
                f"mk_backfill_orders_bill_ids: povezanih {updated} naročil z MK računi"
            )
        except Exception:
            pass
        return updated
    except Exception as e:
        try:
            current_app.logger.error(f"mk_backfill_orders_bill_ids error: {e}")
        except Exception:
            pass
        return 0


def mk_bill_from_sales_order(mk_sales_order_id: str) -> Tuple[Optional[str], Optional[str]]:
    """Razreši povezan prodajni račun (sales_bill_*) iz MK prodajnega naloga.

    Zanesljiva pot za #SI naročila: MK `/search` NE filtrira po title/buyer_order
    (vrne generičen seznam), zato iskanja računa po referenci ne moremo uporabiti.
    Prodajni nalog (sales_order) pa v `doc_link_list` vsebuje povezan račun, npr.:
        {"mk_id": "481000409636", "doc_type": "sales_bill_foreign"}

    Vrne (bill_mk_id, bill_doc_type) ali (None, None). Prednost: foreign → domestic
    → prepaid/retail/bill; dobropisi (credit_note) se izpustijo.
    """
    sid = str(mk_sales_order_id or '').strip()
    if not sid:
        return None, None
    try:
        doc = mk_get_document('sales_order', sid)
    except Exception as e:
        try:
            current_app.logger.warning(f"mk_bill_from_sales_order get_document {sid}: {e}")
        except Exception:
            pass
        return None, None
    if not isinstance(doc, dict):
        return None, None
    links = doc.get('doc_link_list') or []
    if not isinstance(links, list):
        return None, None
    candidates: List[Tuple[str, str]] = []
    for ln in links:
        if not isinstance(ln, dict):
            continue
        dt = str(ln.get('doc_type') or '')
        mid = ln.get('mk_id')
        if mid and dt.startswith('sales_bill') and 'credit' not in dt:
            candidates.append((str(mid), dt))
    if not candidates:
        return None, None
    for pref in ('sales_bill_foreign', 'sales_bill_domestic', 'sales_bill', 'sales_bill_prepaid', 'sales_bill_retail'):
        for mid, dt in candidates:
            if dt == pref:
                return mid, dt
    return candidates[0]


def _mk_auto_credit_note_enabled() -> bool:
    """Master stikalo za avtomatsko izdajo dobropisa ob preklicu (privzeto OFF).

    Vklop prek MK_AUTO_CREDIT_NOTE ∈ {1,true,yes,on} (case-insensitive). Privzeto
    izklopljeno, da lahko status→Storno + alert plasti varno gredo v produkcijo
    pred polno aktivacijo dobropisov.
    """
    val = (os.environ.get('MK_AUTO_CREDIT_NOTE') or '').strip().lower()
    return val in ('1', 'true', 'yes', 'on')


def _mk_today_doc_date() -> str:
    """Datum za MK put_document (format 'YYYY-MM-DD+TZ', kot v MK primerih).

    MK primeri uporabljajo npr. '2021-11-05+02:00'. Lokalni čas Slovenije je
    privzeto +01:00/+02:00; uporabimo lokalni tz offset, da se ujema z UI.
    """
    try:
        now = datetime.now().astimezone()
        return now.strftime('%Y-%m-%d%z')[:-2] + ':' + now.strftime('%z')[-2:]
    except Exception:
        # Varni fallback — samo datum (MK ga sprejme).
        return datetime.now().strftime('%Y-%m-%d')


def _mk_sales_order_has_credit_note(sales_order_doc: Dict[str, Any]) -> bool:
    """Ali ima prodajni nalog v doc_link_list že povezan dobropis?"""
    try:
        links = sales_order_doc.get('doc_link_list') or []
        if not isinstance(links, list):
            return False
        for ln in links:
            if isinstance(ln, dict) and 'credit' in str(ln.get('doc_type') or '').lower():
                return True
    except Exception:
        pass
    return False


def _mk_bill_already_credited(bill_mk_id: str, bill_doc_type: str) -> bool:
    """Ali račun že ima dobropis? Preverimo `sum_creditnote` (show_last_payment_date)
    in `doc_link_list` na samem računu.
    """
    try:
        bill = mk_get_document(bill_doc_type, str(bill_mk_id), {'show_last_payment_date': 'true'})
    except Exception:
        bill = None
    if not isinstance(bill, dict):
        return False
    try:
        scn = str(bill.get('sum_creditnote') or '').strip()
        if scn:
            # nonzero (toleriramo decimalno vejico/piko)
            num = float(scn.replace(',', '.'))
            if abs(num) > 0:
                return True
    except Exception:
        pass
    try:
        links = bill.get('doc_link_list') or []
        if isinstance(links, list):
            for ln in links:
                if isinstance(ln, dict) and 'credit' in str(ln.get('doc_type') or '').lower():
                    return True
    except Exception:
        pass
    return False


def _mk_copy_invoice_product_list(bill_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Prekopiraj postavke originalnega računa VERBATIM za dobropis (goods).

    Ohranimo `code`, `amount`, `price` (ali `price_with_tax`), `discount`, `tax`,
    `name`/`name_desc` — vključno z vrstico COD (Plačilo po povzetju). Tax kod NE
    preračunavamo (odvisen je od države dostave — kopiramo, kot ga je MK zapisal
    na računu).
    """
    out: List[Dict[str, Any]] = []
    items = bill_doc.get('product_list') or []
    if not isinstance(items, list):
        return out
    keep_keys = ('code', 'amount', 'price', 'price_with_tax', 'discount', 'tax', 'name', 'name_desc', 'doc_desc')
    for it in items:
        if not isinstance(it, dict):
            continue
        line: Dict[str, Any] = {}
        for k in keep_keys:
            v = it.get(k)
            if v is not None and str(v) != '':
                line[k] = v
        # Vrstica je smiselna le, če ima vsaj ceno in tax.
        if 'price' in line or 'price_with_tax' in line:
            out.append(line)
    return out


def mk_create_goods_credit_note_for_order(order_number: str) -> Dict[str, Any]:
    """Ob preklicu naročila ustvari finančni/blagovni DOBROPIS na povezanem računu.

    Privzeta pot (uporabnikova dejanska praksa na tem MK računu):
      credit_note_type="goods" — postavke dobropisa so VERBATIM kopija postavk
      originalnega računa (vključno z COD vrstico in per-vrstico tax kodi, ki so
      odvisni od države dostave). MK na podlagi teh postavk sam izračuna sume in
      vrne zalogo.

    Flow (non-blocking; vrne diagnostični dict; klicalec dodatno ovije v try):
      1. MASTER GATE: MK_AUTO_CREDIT_NOTE mora biti vklopljen (privzeto OFF).
      2. Najdi MK sales_order po številki naročila.
      3. IDEMPOTENTNOST: če nalog/račun že ima povezan dobropis → preskoči.
      4. Razreši povezan račun (mk_bill_from_sales_order) in preberi njegov
         count_code + product_list prek get_document.
      5. Sestavi dobropis (kopija postavk) in ga ustvari prek put_document.
    """
    if not _mk_auto_credit_note_enabled():
        try:
            current_app.logger.info("MK credit note skipped (MK_AUTO_CREDIT_NOTE not enabled)")
        except Exception:
            pass
        return {'skipped': True, 'reason': 'MK_AUTO_CREDIT_NOTE not enabled'}

    if not order_number:
        return {'skipped': True, 'reason': 'no order_number'}

    credit_note_type = (os.environ.get('MK_CREDIT_NOTE_TYPE') or 'goods').strip().lower() or 'goods'
    clean = str(order_number).lstrip('#').strip()

    # 1) Prodajni nalog
    try:
        so = mk_find_sales_order_by_title(clean) or mk_find_sales_order_by_title(str(order_number))
    except Exception as e:
        return {'skipped': True, 'reason': f'MK sales_order lookup failed: {e}'}
    if not so:
        return {'skipped': True, 'reason': 'MK sales_order not found'}

    so_mk_id = so.get('mk_id') or so.get('id') or so.get('doc_id')

    # 2) Idempotentnost — nalog že povezan z dobropisom?
    if _mk_sales_order_has_credit_note(so):
        return {'skipped': True, 'reason': 'credit note already linked on sales_order'}

    # 3) Razreši povezan račun
    if not so_mk_id:
        return {'skipped': True, 'reason': 'sales_order has no mk_id'}
    try:
        bill_mk_id, bill_doc_type = mk_bill_from_sales_order(str(so_mk_id))
    except Exception as e:
        return {'skipped': True, 'reason': f'bill resolution failed: {e}'}
    if not bill_mk_id or not bill_doc_type:
        return {'skipped': True, 'reason': 'no linked invoice (sales_bill) found for order'}

    # 4) Idempotentnost — račun že kreditiran?
    if _mk_bill_already_credited(str(bill_mk_id), str(bill_doc_type)):
        return {
            'skipped': True,
            'reason': 'invoice already has a credit note (sum_creditnote/doc_link_list)',
            'bill_mk_id': str(bill_mk_id),
        }

    # 5) Preberi original račun (count_code + product_list)
    try:
        bill_doc = mk_get_document(str(bill_doc_type), str(bill_mk_id))
    except Exception as e:
        return {'skipped': True, 'reason': f'invoice get_document failed: {e}'}
    if not isinstance(bill_doc, dict):
        return {'skipped': True, 'reason': 'invoice get_document returned no document'}

    invoice_count_code = (bill_doc.get('count_code') or '').strip()
    if not invoice_count_code:
        return {'skipped': True, 'reason': 'invoice has no count_code (cannot link credit note)'}

    product_list = _mk_copy_invoice_product_list(bill_doc)
    if not product_list:
        return {'skipped': True, 'reason': 'invoice product_list empty (nothing to credit)'}

    # 6) Sestavi in ustvari dobropis prek put_document
    base = _mk_base()
    doc_date = _mk_today_doc_date()
    payload: Dict[str, Any] = {
        'doc_type': 'sales_bill_credit_note',
        'credit_note_type': credit_note_type,
        'credit_note_bill': invoice_count_code,
        'doc_date': doc_date,
        'service_to_date': doc_date,
        'duo_payment': doc_date,
        'product_list': product_list,
    }
    url = f"{base}/put_document"
    try:
        resp = _mk_post_json_with_retry(url, payload, max_attempts=3, min_backoff=1.0, max_backoff=8.0)
        cn_mk_id = None
        if isinstance(resp, dict):
            cn_mk_id = resp.get('mk_id') or resp.get('doc_id') or resp.get('id')
        try:
            current_app.logger.info(
                f"MK credit note created order={clean} bill={invoice_count_code} "
                f"type={credit_note_type} lines={len(product_list)} cn_mk_id={cn_mk_id}"
            )
        except Exception:
            pass
        return {
            'ok': True,
            'created': True,
            'credit_note_type': credit_note_type,
            'bill_mk_id': str(bill_mk_id),
            'bill_doc_type': str(bill_doc_type),
            'invoice_count_code': invoice_count_code,
            'lines': len(product_list),
            'credit_note_mk_id': str(cn_mk_id) if cn_mk_id else None,
            'response': resp,
        }
    except Exception as e:
        return {'ok': False, 'reason': f'put_document credit_note failed: {e}'}


def mk_link_orders_missing_bills(days: int = 21, limit: int = 25, per_order_budget_s: float = 15.0) -> int:
    """Za nedavna fulfilled naročila brez `mk_bill_id` razreši MK račun v živo
    in zapiše `orders.mk_bill_id` + `mk_bill_type`.

    MK račun obstaja že ob fulfillmentu, a bulk date-scan (mk_sync_bills) pri
    tem MK računu ne doseže nedavnih računov — per-order iskanje (mk_find_bill_*)
    pa jih zanesljivo najde. Zato to uporabljamo za sprotno polnjenje, da je
    status MK računa viden skoraj takoj (brez klika na PDF).

    Omejeno z `limit` (št. naročil na klic) in `per_order_budget_s` (wall-clock
    na naročilo), da ne preobremenimo MK API. Najnovejša naročila se obdelajo
    najprej. Vrne število povezanih naročil.
    """
    try:
        import time as _t
        from database import get_db
        db = get_db(); c = db.cursor()
        # Opomba: stolpca mk_bill_id / mk_bill_type sta del sheme (migracije).
        # ALTER TABLE tukaj NE izvajamo — vsak klic bi zahteval ACCESS EXCLUSIVE
        # lock na vroči tabeli `orders` in ob soobstoju z idle-in-transaction
        # background jobi povzroči lock pileup (cron 504).
        c.execute(
            """
            SELECT order_number, shopify_order_id, mk_sales_order_id
            FROM orders
            WHERE mk_bill_id IS NULL
              AND COALESCE(fulfilled_at, shopify_fulfilled_at) IS NOT NULL
              AND COALESCE(fulfilled_at, created_at) > NOW() - make_interval(days => %s)
            ORDER BY COALESCE(fulfilled_at, created_at) DESC
            LIMIT %s
            """,
            (int(days), int(limit)),
        )
        rows = c.fetchall() or []
        types = _mk_sales_doc_types()
        linked = 0
        for r in rows:
            od = r if isinstance(r, dict) else {'order_number': r[0], 'shopify_order_id': r[1], 'mk_sales_order_id': r[2]}
            on = str(od.get('order_number') or '').strip()
            if not on:
                continue
            mk_id = None
            doc_type = None
            try:
                # 1) Najzanesljivejša pot: prek prodajnega naloga → povezan račun.
                #    MK /search ne filtrira po referenci, zato je za #SI naročila to
                #    edina zanesljiva pot.
                so_id = od.get('mk_sales_order_id')
                if so_id:
                    b_id, b_type = mk_bill_from_sales_order(str(so_id))
                    if b_id:
                        mk_id, doc_type = b_id, b_type
                if not mk_id:
                    hit = mk_find_bill_in_db(on)
                    if hit and hit.get('mk_id'):
                        mk_id, doc_type = str(hit['mk_id']), hit.get('doc_type')
                if not mk_id:
                    refs = [on]
                    clean = on.lstrip('#')
                    if clean and clean != on:
                        refs.append(clean)
                    sid = od.get('shopify_order_id')
                    if sid:
                        refs.append(str(sid))
                    deadline = _t.monotonic() + float(per_order_budget_s)
                    for ref in refs:
                        if mk_id or _t.monotonic() > deadline:
                            break
                        for dt in types:
                            if _t.monotonic() > deadline:
                                break
                            d = mk_find_bill_quick(dt, ref, limit=25)
                            if d and d.get('mk_id'):
                                mk_id, doc_type = str(d['mk_id']), d.get('_doc_type') or dt
                                break
            except Exception as _e:
                current_app.logger.warning(f"mk_link_orders_missing_bills: {on}: {_e}")
                continue
            if not mk_id:
                continue
            try:
                c.execute(
                    "UPDATE orders SET mk_bill_id = %s, mk_bill_type = %s "
                    "WHERE order_number = %s OR order_number = %s",
                    (mk_id, doc_type or 'sales_bill_foreign', on, f"#{on.lstrip('#')}"),
                )
                db.commit()
                linked += 1
            except Exception as _ue:
                current_app.logger.warning(f"mk_link_orders_missing_bills update {on}: {_ue}")
                try:
                    db.rollback()
                except Exception:
                    pass
        try:
            current_app.logger.info(
                f"mk_link_orders_missing_bills: povezanih {linked}/{len(rows)} naročil"
            )
        except Exception:
            pass
        return linked
    except Exception as e:
        try:
            current_app.logger.error(f"mk_link_orders_missing_bills error: {e}")
        except Exception:
            pass
        return 0


def mk_sync_bills_from_orders(days: int = 1, max_orders: int = 2000) -> int:
    """Import bills by iterating local orders from the last `days` and resolving their bills via search.

    For each order, try DB hit; else query MK via mk_find_bill_any. Upsert into mk_bills.
    """
    try:
        _ensure_mk_bills_table()
        from database import get_db
        db = get_db(); c = db.cursor()
        cutoff = datetime.utcnow() - timedelta(days=days)
        # Pridobi naročila (najprej po fulfilled_at, če ni pa po created_at)
        c.execute(
            """
            SELECT order_number, shopify_order_id, customer_email, COALESCE(fulfilled_at, created_at) AS ref_ts
            FROM orders
            WHERE COALESCE(fulfilled_at, created_at) > NOW() - make_interval(days => %s)
            ORDER BY COALESCE(fulfilled_at, created_at) DESC
            LIMIT %s
            """,
            (int(days), int(max_orders))
        )
        orders = c.fetchall() or []
        imported = 0
        total_orders = len(orders)
        idx = 0
        try:
            current_app.config['MK_SYNC_PROGRESS'] = {
                'phase': 'orders_scan',
                'total_orders': total_orders,
                'processed_orders': 0,
                'imported': imported
            }
        except Exception:
            pass
        for r in orders:
            # Cancel check
            if current_app.config.get('MK_SYNC_CANCEL'):
                return imported
            od = r if isinstance(r, dict) else {
                'order_number': r[0], 'shopify_order_id': r[1], 'customer_email': r[2], 'ref_ts': r[3]
            }
            onum = str(od.get('order_number') or '').lstrip('#')
            if not onum:
                continue
            # Najprej poglej v mk_bills
            db_hit = mk_find_bill_in_db(onum)
            bill = None
            doc_type = None
            if db_hit:
                bill = mk_get_document(db_hit['doc_type'], db_hit['mk_id'])
                doc_type = db_hit['doc_type']
            if not bill:
                # query MK
                bill = mk_find_bill_any(onum)
                doc_type = bill.get('_doc_type') if bill else None
            if not bill:
                # poskusi še s shopify_order_id
                sid = od.get('shopify_order_id')
                if sid:
                    bill = mk_find_bill_any(str(sid))
                    doc_type = bill.get('_doc_type') if bill else None
            if not bill:
                idx += 1
                try:
                    prog = current_app.config.get('MK_SYNC_PROGRESS', {}) or {}
                    prog.update({'processed_orders': idx, 'imported': imported})
                    current_app.config['MK_SYNC_PROGRESS'] = prog
                except Exception:
                    pass
                continue
            mk_id = str(bill.get('mk_id')) if bill.get('mk_id') else None
            if not mk_id:
                idx += 1
                try:
                    prog = current_app.config.get('MK_SYNC_PROGRESS', {}) or {}
                    prog.update({'processed_orders': idx, 'imported': imported})
                    current_app.config['MK_SYNC_PROGRESS'] = prog
                except Exception:
                    pass
                continue
            # Upsert v mk_bills
            try:
                pub_ts = _parse_iso(bill.get('publish_ts'))
                created_ts = _parse_iso(bill.get('created_ts') or bill.get('created_at'))
                c.execute(
                    """
                    INSERT INTO mk_bills (mk_id, doc_type, title, buyer_order, count_code, publish_ts, furs_zoi, furs_eor, total, created_ts, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                    ON CONFLICT (mk_id) DO UPDATE SET
                      doc_type = EXCLUDED.doc_type,
                      title = EXCLUDED.title,
                      buyer_order = EXCLUDED.buyer_order,
                      count_code = EXCLUDED.count_code,
                      publish_ts = COALESCE(EXCLUDED.publish_ts, mk_bills.publish_ts),
                      furs_zoi = COALESCE(EXCLUDED.furs_zoi, mk_bills.furs_zoi),
                      furs_eor = COALESCE(EXCLUDED.furs_eor, mk_bills.furs_eor),
                      total = COALESCE(EXCLUDED.total, mk_bills.total),
                      created_ts = COALESCE(EXCLUDED.created_ts, mk_bills.created_ts),
                      updated_at = NOW()
                    """,
                    (
                        mk_id, doc_type or '', bill.get('title'), bill.get('buyer_order'), bill.get('count_code'),
                        pub_ts, bill.get('furs_zoi'), bill.get('furs_eor'), bill.get('total'), created_ts
                    )
                )
                # Apply procurement pending increments for non-MISTRAL/FLORGARDEN SKUs (idempotent)
                try:
                    _apply_procurement_from_bill(c, bill)
                except Exception as _pe:
                    current_app.logger.error(f"procurement apply hook error: {_pe}")
                imported += 1
            except Exception as ie:
                current_app.logger.error(f"mk_sync_bills_from_orders upsert error for {mk_id}: {ie}")
            finally:
                idx += 1
                try:
                    prog = current_app.config.get('MK_SYNC_PROGRESS', {}) or {}
                    prog.update({'processed_orders': idx, 'imported': imported})
                    current_app.config['MK_SYNC_PROGRESS'] = prog
                except Exception:
                    pass
        db.commit(); c.close()
        return imported
    except Exception as e:
        current_app.logger.error(f"mk_sync_bills_from_orders fatal: {e}")
        return 0


# ===================== GENERIC APP LOGS =====================

def _ensure_app_logs_table():
    try:
        from database import get_db
        db = get_db(); c = db.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS app_logs (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ DEFAULT NOW(),
                category TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'info',
                message TEXT,
                data JSONB
            );
            """
        )
        db.commit(); c.close()
    except Exception as e:
        current_app.logger.error(f"app_logs ensure table error: {e}")


def _ensure_mk_bill_tables():
    """Create robust retail bill tables (head + items) for plug-and-play import."""
    try:
        from database import get_db
        db = get_db(); c = db.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS mk_bill (
              mk_id           TEXT PRIMARY KEY,
              document_number TEXT,
              issue_date      DATE,
              currency_code   TEXT,
              sum_eur         NUMERIC(12,2),
              sum_currency    NUMERIC(12,2),
              method_of_payment TEXT,
              furs_zoi        TEXT,
              furs_eor        TEXT,
              status_desc     TEXT,
              publish_ts      TIMESTAMPTZ,
              raw_json        JSONB,
              updated_at      TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS mk_bill_item (
              mk_id         TEXT,
              row_no        INT,
              product_id    TEXT,
              product_code  TEXT,
              title         TEXT,
              qty           NUMERIC(12,3),
              unit_price    NUMERIC(12,4),
              tax_rate      NUMERIC(5,2),
              discount      NUMERIC(12,4),
              raw_json      JSONB,
              PRIMARY KEY (mk_id, row_no)
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS mk_bill_publish_ts_idx ON mk_bill(publish_ts)")
        db.commit(); c.close()
    except Exception as e:
        current_app.logger.error(f"_ensure_mk_bill_tables error: {e}")


def mk_upsert_bill(c, bill: Dict[str, Any]) -> None:
    """UPSERT bill head into mk_bill.

    Maps robust fields with fallbacks per retail bill get_document.
    """
    try:
        mk_id = str(bill.get('mk_id') or '').strip()
        if not mk_id:
            return
        document_number = bill.get('document_number') or bill.get('count_code') or bill.get('title')
        issue_date = None
        try:
            dt = _parse_iso(bill.get('issue_date') or bill.get('doc_date') or bill.get('service_to_date'))
            issue_date = dt.date() if dt else None
        except Exception:
            issue_date = None
        currency_code = bill.get('currency_code') or bill.get('currency')
        sum_eur = bill.get('sum_eur') or bill.get('total')
        sum_currency = bill.get('sum_currency') or None
        mop = bill.get('method_of_payment')
        if isinstance(mop, list):
            try:
                method_of_payment = ", ".join([str(x) for x in mop])
            except Exception:
                method_of_payment = str(mop)
        else:
            method_of_payment = mop or None
        furs_zoi = bill.get('furs_zoi')
        furs_eor = bill.get('furs_eor')
        status_desc = bill.get('status_desc')
        publish_ts = _parse_iso(bill.get('publish_ts'))
        raw_json = _json.dumps(bill)
        c.execute(
            """
            INSERT INTO mk_bill (mk_id, document_number, issue_date, currency_code, sum_eur, sum_currency,
                                 method_of_payment, furs_zoi, furs_eor, status_desc, publish_ts, raw_json, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            ON CONFLICT (mk_id) DO UPDATE SET
              document_number = EXCLUDED.document_number,
              issue_date = EXCLUDED.issue_date,
              currency_code = EXCLUDED.currency_code,
              sum_eur = EXCLUDED.sum_eur,
              sum_currency = EXCLUDED.sum_currency,
              method_of_payment = EXCLUDED.method_of_payment,
              furs_zoi = EXCLUDED.furs_zoi,
              furs_eor = EXCLUDED.furs_eor,
              status_desc = EXCLUDED.status_desc,
              publish_ts = COALESCE(EXCLUDED.publish_ts, mk_bill.publish_ts),
              raw_json = EXCLUDED.raw_json,
              updated_at = NOW()
            """,
            (mk_id, document_number, issue_date, currency_code, sum_eur, sum_currency,
             method_of_payment, furs_zoi, furs_eor, status_desc, publish_ts, raw_json)
        )
    except Exception as e:
        current_app.logger.error(f"mk_upsert_bill error: {e}")


def mk_upsert_bill_items(c, bill: Dict[str, Any]) -> None:
    """UPSERT bill items into mk_bill_item.

    Uses item_list primarily (new get_document bill), with fallbacks to product_list.
    """
    try:
        mk_id = str(bill.get('mk_id') or '').strip()
        if not mk_id:
            return
        items = bill.get('item_list') or bill.get('rows') or bill.get('document_rows') or bill.get('product_list') or []
        if not items:
            return
        for idx, it in enumerate(items, start=1):
            product_id = str(it.get('product_id') or it.get('id') or '').strip() or None
            product_code = str(it.get('product_code') or it.get('code') or it.get('sku') or '').strip() or None
            title = it.get('title') or it.get('name')
            qty = it.get('qty') or it.get('quantity') or it.get('amount')
            unit_price = it.get('unit_price') or it.get('price')
            tax_rate = it.get('tax_rate') or None
            discount = it.get('discount') or 0
            rj = _json.dumps(it)
            c.execute(
                """
                INSERT INTO mk_bill_item (mk_id, row_no, product_id, product_code, title, qty, unit_price, tax_rate, discount, raw_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (mk_id, row_no) DO UPDATE SET
                  product_id = EXCLUDED.product_id,
                  product_code = EXCLUDED.product_code,
                  title = EXCLUDED.title,
                  qty = EXCLUDED.qty,
                  unit_price = EXCLUDED.unit_price,
                  tax_rate = EXCLUDED.tax_rate,
                  discount = EXCLUDED.discount,
                  raw_json = EXCLUDED.raw_json
                """,
                (mk_id, idx, product_id, product_code, title, qty, unit_price, tax_rate, discount, rj)
            )
    except Exception as e:
        current_app.logger.error(f"mk_upsert_bill_items error: {e}")


def mk_import_retail_bills_by_ids(mk_ids: list[str]) -> int:
    """Fetch retail bills by mk_id via get_document(doc_type='bill') and upsert into mk_bill/mk_bill_item."""
    try:
        if not mk_ids:
            return 0
        _ensure_mk_bill_tables()
        from database import get_db
        db = get_db(); c = db.cursor()
        imported = 0
        for sid in mk_ids:
            mkid = str(sid).strip()
            if not mkid:
                continue
            d = mk_get_document_bill_via_get_document(mkid) or {}
            if not d or not d.get('mk_id'):
                continue
            try:
                current_app.logger.debug(f"ids_import diag: {_retail_diag_fields(d)}")
            except Exception:
                pass
            if not _panic_import_all() and not is_retail_bill(d):
                try:
                    app_log('import.retail', 'info', 'non-retail bill skipped', {'mk_id': mkid})
                except Exception:
                    pass
                continue
            mk_upsert_bill(c, d)
            try:
                mk_upsert_bill_items(c, d)
            except Exception:
                pass
            imported += 1
        db.commit(); c.close()
        return imported
    except Exception as e:
        current_app.logger.error(f"mk_import_retail_bills_by_ids error: {e}")
        return 0


def _mk_max_publish_ts() -> Optional[datetime]:
    try:
        from database import get_db
        db = get_db(); c = db.cursor()
        c.execute("SELECT MAX(publish_ts) FROM mk_bill")
        row = c.fetchone(); c.close()
        if not row:
            return None
        val = row[0]
        return val
    except Exception:
        return None


def sync_retail_bills_delta(days_back: int = 30) -> Dict[str, int]:
    """Incremental retail sync based on publish_ts using /get_change_documents for bill IDs.

    - Harvests bill IDs from /get_change_documents in a window around last publish_ts
    - Fetches details via get_document(doc_type='bill') and filters to retail
    - Honors MK_DRY_RUN env to log-only actions
    Returns metrics.
    """
    start_ts = datetime.now(timezone.utc)
    metrics = {'found_ids': 0, 'fetched_docs': 0, 'filtered_retail': 0, 'upserted_count': 0}
    try:
        _ensure_mk_bill_tables()
        last = _mk_max_publish_ts()
        if last is None:
            date_from = start_ts - timedelta(days=int(days_back))
        else:
            date_from = last - timedelta(minutes=60)
        date_to = start_ts
        current_app.logger.info(f"sync_retail_bills_delta: start {date_from.isoformat()} -> {date_to.isoformat()}")
        dry = _mk_bool_env('MK_DRY_RUN', False)

        from database import get_db
        db = get_db(); c = db.cursor()

        # Harvest IDs via /get_change_documents (doc_type='bill'), using pagination
        harvested_ids: set[str] = set()
        total_docs = 0
        try:
            base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
            change_url = f"{base}/get_change_documents"
            offset = 0
            page_size = MAX_PAGE_SIZE
            while True:
                payload = {
                    'company_id': str(company_id),
                    'secret': str(secret),
                    'doc_type': 'bill',
                    'limit': int(page_size),
                    'offset': int(offset),
                    'publish_ts_from': date_from.replace(tzinfo=timezone.utc).isoformat(),
                    'publish_ts_to': date_to.replace(tzinfo=timezone.utc).isoformat(),
                }
                dj = _mk_post_json_with_retry(change_url, payload, max_attempts=5, min_backoff=1.0, max_backoff=20.0)
                rows = dj if isinstance(dj, list) else (dj.get('rows') or dj.get('result') or dj.get('documents') or [])
                if not rows:
                    break
                total_docs += len(rows)
                for rr in rows:
                    sid = rr.get('mk_id') or rr.get('id') or rr.get('doc_id') or rr.get('document_id')
                    if sid:
                        harvested_ids.add(str(sid))
                if len(rows) < page_size:
                    break
                offset += page_size
        except Exception as e:
            current_app.logger.error(f"sync_retail_bills_delta change_documents error, falling back to retail search: {e}")
            # Fallback to retail /search (sales_bill_*), using pagination
            offset = 0
            while True:
                docs, meta = search_pos_bills(date_from.strftime('%Y-%m-%d'), date_to.strftime('%Y-%m-%d'), limit=MAX_PAGE_SIZE, offset=offset)
                if not docs:
                    break
                total_docs += len(docs)
                for rr in docs:
                    mkid = extract_mk_id_from_search_doc(rr)
                    if mkid:
                        harvested_ids.add(str(mkid))
                if len(docs) < MAX_PAGE_SIZE:
                    break
                offset += MAX_PAGE_SIZE

        if not harvested_ids:
            current_app.logger.info(f"change_documents empty for window {date_from.isoformat()} -> {date_to.isoformat()}")
            db.commit(); c.close()
            return metrics

        for mkid in harvested_ids:
                metrics['found_ids'] += 1
                d = fetch_retail_bill(str(mkid)) or {}
                if not d or not d.get('mk_id'):
                    continue
                metrics['fetched_docs'] += 1
                # Telemetry: log diagnostic fields before filtering
                try:
                    di = _retail_diag_fields(d)
                    di['publish_ts'] = d.get('publish_ts')
                    current_app.logger.debug(f"sync_retail_bills_delta diag: {di}")
                except Exception:
                    pass
                retail_ok = True if _panic_import_all() else is_retail_bill(d)
                if not retail_ok:
                    try:
                        current_app.logger.info(f"sync_retail_bills_delta: non-retail bill skipped { _retail_diag_fields(d) }")
                    except Exception:
                        pass
                    continue
                metrics['filtered_retail'] += 1
                if dry:
                    current_app.logger.info(f"DRY_RUN: would upsert retail bill mk_id={mkid} publish_ts={d.get('publish_ts')}")
                    continue
                mk_upsert_bill(c, d)
                try:
                    mk_upsert_bill_items(c, d)
                except Exception as ie:
                    current_app.logger.error(f"sync_retail_bills_delta items error for mk_id={mkid}: {ie}")
                metrics['upserted_count'] += 1
                if metrics['upserted_count'] % 200 == 0:
                    db.commit()
        # end for mkid
        db.commit(); c.close()
        dur = (datetime.now(timezone.utc) - start_ts).total_seconds()
        metrics['searched_docs'] = total_docs
        metrics['unique_ids'] = len(harvested_ids)
        current_app.logger.info(f"sync_retail_bills_delta done in {dur:.1f}s: {metrics} window_from={date_from.isoformat()} window_to={date_to.isoformat()}")
        return metrics
    except Exception as e:
        current_app.logger.error(f"sync_retail_bills_delta fatal: {e}")
        return metrics


def mk_import_retail_bills_delta(hours: int = 24, scan_window: int = 5000) -> int:
    """Import recent retail bills by scanning tail mk_ids and filtering by publish_ts >= last seen.

    Falls back to hours window if no previous publish_ts present.
    """
    try:
        _ensure_mk_bill_tables()
        last_ts = _mk_max_publish_ts()
        if not last_ts:
            # fallback: since now-hours
            last_ts = datetime.now(timezone.utc) - timedelta(hours=int(hours))

        # Determine an anchor mk_id using retail search (newest first)
        base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
        url = f"{base}/search"
        anchor = None
        # Prefer change documents to anchor from latest bill ids
        try:
            change_url = f"{base}/get_change_documents"
            change_payload = {
                'company_id': str(company_id), 'secret': str(secret), 'doc_type': 'bill',
                'limit': 100, 'offset': 0,
                'publish_ts_from': (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
                'publish_ts_to': datetime.now(timezone.utc).isoformat(),
            }
            dj = _mk_post_json_with_retry(change_url, change_payload, max_attempts=3, min_backoff=1.0, max_backoff=8.0)
            rows = dj if isinstance(dj, list) else (dj.get('rows') or dj.get('result') or dj.get('documents') or [])
            for rr in rows:
                sid = rr.get('mk_id') or rr.get('id') or rr.get('doc_id') or rr.get('document_id')
                if sid and str(sid).isdigit():
                    anchor = int(str(sid)); break
        except Exception:
            anchor = None

        # Fallback to known max mk_id from mk_bill if needed
        if anchor is None:
            try:
                from database import get_db
                db = get_db(); c = db.cursor()
                c.execute("SELECT MAX((mk_id)::bigint) FROM mk_bill WHERE mk_id ~ '^[0-9]+'"); row = c.fetchone(); c.close()
                if row and row[0] is not None:
                    anchor = int(row[0])
            except Exception:
                anchor = None

        if anchor is None:
            return 0

        from database import get_db
        db = get_db(); c = db.cursor()
        imported = 0
        seen = 0
        skipped_non_retail = 0
        for delta in range(0, int(scan_window)):
            mkid = anchor - delta
            if mkid <= 0:
                break
            d = mk_get_document_bill_via_get_document(str(mkid)) or {}
            if not d or not d.get('mk_id'):
                continue
            # Telemetry
            try:
                current_app.logger.debug(f"delta_import diag: {_retail_diag_fields(d)}")
            except Exception:
                pass
            if not is_retail_bill(d):
                skipped_non_retail += 1
                continue
            ts_ref = _extract_bill_ts(d)
            if not ts_ref or ts_ref < last_ts:
                continue
            mk_upsert_bill(c, d)
            try:
                mk_upsert_bill_items(c, d)
            except Exception:
                pass
            imported += 1
            seen += 1
            if seen % 200 == 0:
                db.commit()
        db.commit(); c.close()
        try:
            current_app.logger.info(f"mk_import_retail_bills_delta stats: found_ids~{seen}, fetched_docs~{seen}, retail_kept={imported}, upserted={imported}, skipped_non_retail={skipped_non_retail}, window_h={hours}, anchor_id={anchor}")
        except Exception:
            pass
        return imported
    except Exception as e:
        current_app.logger.error(f"mk_import_retail_bills_delta error: {e}")
        return 0


def mk_import_retail_bills_search(hours: int = 24, max_pages: int = 50, page_size: int = 100, ignore_last_ts: bool = False) -> int:
    """Import retail bills by searching doc_type='bill' in a recent window and filtering via get_document.

    - Uses date window [now-hours, now]
    - Paginates using mk_search_bill_ids_range
    - Filters retail with is_retail_bill
    """
    try:
        _ensure_mk_bill_tables()
        date_to = datetime.now(timezone.utc)
        date_from = date_to - timedelta(hours=int(hours))
        imported = 0
        dry = _mk_bool_env('MK_DRY_RUN', False)
        from database import get_db
        db = get_db(); c = db.cursor()
        scanned = 0
        # For search path, never exceed 100 due to API caps
        for mkid in mk_search_bill_ids_range(date_from, date_to, page_size=max(1, min(100, int(page_size))), max_pages=int(max_pages)):
            scanned += 1
            d = mk_get_document_bill_via_get_document(str(mkid)) or {}
            if not d or not d.get('mk_id'):
                continue
            try:
                di = _retail_diag_fields(d)
                di['publish_ts'] = d.get('publish_ts')
                current_app.logger.debug(f"search_import diag: {di}")
            except Exception:
                pass
            retail_ok = True if _panic_import_all() else is_retail_bill(d)
            if not retail_ok:
                try:
                    current_app.logger.info(f"search_import: non-retail bill skipped { _retail_diag_fields(d) }")
                except Exception:
                    pass
                continue
            if dry:
                current_app.logger.info(f"DRY_RUN: would import retail bill mk_id={mkid}")
                continue
            mk_upsert_bill(c, d)
            try:
                mk_upsert_bill_items(c, d)
            except Exception:
                pass
            imported += 1
            if imported % 200 == 0:
                db.commit()
        db.commit(); c.close()
        current_app.logger.info(f"search_import finished: scanned={scanned}, imported={imported}, window_h={hours}")
        return imported
    except Exception as e:
        current_app.logger.error(f"mk_import_retail_bills_search error: {e}")
        return 0

def app_log(category: str, level: str = 'info', message: str | None = None, data: dict | None = None) -> None:
    try:
        _ensure_app_logs_table()
        from database import get_db
        db = get_db(); c = db.cursor()
        c.execute(
            """
            INSERT INTO app_logs (category, level, message, data)
            VALUES (%s, %s, %s, %s)
            """,
            (str(category), str(level), message, _json.dumps(data or {}))
        )
        db.commit(); c.close()
    except Exception as e:
        current_app.logger.error(f"app_log error: {e}")


def migrate_invoice_email_log_to_app_logs() -> int:
    """One-time migration of legacy invoice_email_log into app_logs.
    Returns number of rows inserted. Safe to run multiple times (dedup guarded).
    """
    inserted = 0
    try:
        _ensure_app_logs_table()
        from database import get_db
        db = get_db(); c = db.cursor()
        # Ensure legacy table exists before attempting migration
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS invoice_email_log (
                id BIGSERIAL PRIMARY KEY,
                order_number TEXT,
                mk_id TEXT,
                mk_type TEXT,
                recipient TEXT,
                status TEXT,
                error TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        db.commit()
        # Insert missing records into app_logs, preserving original timestamp
        c.execute(
            """
            WITH src AS (
                SELECT id, order_number, mk_id, mk_type, recipient, status, error, created_at
                FROM invoice_email_log
            )
            INSERT INTO app_logs (ts, category, level, message, data)
            SELECT
                COALESCE(s.created_at, NOW()) AS ts,
                'email.send_invoice' AS category,
                CASE WHEN COALESCE(NULLIF(TRIM(s.error), ''), NULL) IS NULL THEN 'info' ELSE 'error' END AS level,
                CONCAT('Invoice email ', COALESCE(s.status, '')) AS message,
                jsonb_build_object(
                    'order_number', s.order_number,
                    'mk_id', s.mk_id,
                    'mk_type', s.mk_type,
                    'recipient', s.recipient,
                    'status', s.status,
                    'error', s.error
                ) AS data
            FROM src s
            WHERE NOT EXISTS (
                SELECT 1 FROM app_logs a
                WHERE a.category = 'email.send_invoice'
                  AND COALESCE(a.data->>'order_number','') = COALESCE(s.order_number,'')
                  AND COALESCE(a.data->>'recipient','') = COALESCE(s.recipient,'')
                  AND COALESCE(a.data->>'status','') = COALESCE(s.status,'')
                  AND COALESCE(a.data->>'mk_id','') = COALESCE(s.mk_id,'')
            )
            RETURNING 1
            """
        )
        rows = c.fetchall() or []
        inserted = len(rows)
        db.commit(); c.close()
    except Exception as e:
        try:
            current_app.logger.error(f"migrate_invoice_email_log_to_app_logs error: {e}")
        except Exception:
            pass
    return inserted


def migrate_declaration_email_orders_to_app_logs() -> int:
    """Migrate historical declaration email sends from orders.email_sent_at into app_logs.
    Category: email.send_declaration. Idempotent.
    """
    inserted = 0
    try:
        _ensure_app_logs_table()
        from database import get_db
        db = get_db(); c = db.cursor()
        c.execute(
            """
            INSERT INTO app_logs (ts, category, level, message, data)
            SELECT
                COALESCE(o.email_sent_at, NOW()) AS ts,
                'email.send_declaration' AS category,
                'info' AS level,
                'Declaration email sent' AS message,
                jsonb_build_object(
                    'order_number', o.order_number,
                    'recipient', o.email_recipient,
                    'status', o.status,
                    'shopify_order_id', o.shopify_order_id,
                    'country_code', o.country_code
                ) AS data
            FROM orders o
            WHERE o.email_sent_at IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM app_logs a
                  WHERE a.category = 'email.send_declaration'
                    AND COALESCE(a.data->>'order_number','') = COALESCE(o.order_number,'')
                    AND COALESCE(a.data->>'recipient','') = COALESCE(o.email_recipient,'')
              )
            RETURNING 1
            """
        )
        rows = c.fetchall() or []
        inserted = len(rows)
        db.commit(); c.close()
    except Exception as e:
        try:
            current_app.logger.error(f"migrate_declaration_email_orders_to_app_logs error: {e}")
        except Exception:
            pass
    return inserted


def extract_mk_id_from_search_doc(doc: Dict[str, Any]) -> Optional[str]:
    """Return mk_id from a /search doc; try common locations.

    Order: doc['mk_id'] → doc['id'] → doc.get('head',{}).get('mk_id'). Log sample on failure.
    """
    try:
        sid = doc.get('mk_id') or doc.get('id')
        if not sid and isinstance(doc.get('head'), dict):
            sid = doc['head'].get('mk_id')
        if sid:
            return str(sid)
    except Exception:
        pass
    try:
        current_app.logger.debug(f"extract_mk_id_from_search_doc: no id in sample={str(doc)[:300]}")
    except Exception:
        pass
    return None


def import_retail_bills_window(date_from: str, date_to: str) -> Dict[str, int]:
    """Uvozi maloprodajne račune v oknu datumov dokumenta (YYYY-MM-DD).

    1) search_pos_bills(date_from, date_to, limit=100, offset=0 ... paginate)
    2) unikaten set mk_id iz docs
    3) za vsak mk_id: fetch_retail_bill(mk_id) → UPSERT v mk_bill/mk_bill_item
    Panic switch: če je vklopljen, ignorira retail filter.
    Vrne statistiko.
    """
    stats = {'searched_docs': 0, 'unique_ids': 0, 'fetched': 0, 'upserted': 0, 'skipped': 0}
    try:
        _ensure_mk_bill_tables()
        # paginate search
        offset = 0
        ids: set[str] = set()
        while True:
            docs, _meta = search_pos_bills(date_from, date_to, limit=MAX_PAGE_SIZE, offset=offset)
            if not docs:
                break
            stats['searched_docs'] += len(docs)
            for rr in docs:
                sid = rr.get('mk_id') or rr.get('id') or ((rr.get('head') or {}).get('mk_id') if isinstance(rr.get('head'), dict) else None)
                if sid:
                    ids.add(str(sid))
            if len(docs) < MAX_PAGE_SIZE:
                break
            offset += MAX_PAGE_SIZE
        stats['unique_ids'] = len(ids)

        from database import get_db
        db = get_db(); c = db.cursor()
        for mkid in ids:
            d = fetch_retail_bill(str(mkid)) or {}
            if not d or not d.get('mk_id'):
                continue
            stats['fetched'] += 1
            retail_ok = True if _panic_import_all() else is_retail_bill(d)
            if not retail_ok:
                stats['skipped'] += 1
                continue
            mk_upsert_bill(c, d)
            try:
                mk_upsert_bill_items(c, d)
            except Exception:
                pass
            stats['upserted'] += 1
        db.commit(); c.close()
        try:
            current_app.logger.info(f"import_retail_bills_window {date_from}->{date_to} stats={stats}")
        except Exception:
            pass
        return stats
    except Exception as e:
        try:
            current_app.logger.error(f"import_retail_bills_window error: {e}")
        except Exception:
            pass
        return stats


def sync_retail_bills_last_7d() -> Dict[str, Any]:
    """Minimalna delta (7 dni) po datumu dokumenta – uporablja strogi ESHOP retail tok."""
    today = datetime.now(timezone.utc).date()
    date_to = today.strftime('%Y-%m-%d')
    date_from = (today - timedelta(days=7)).strftime('%Y-%m-%d')
    return import_retail_window(date_from, date_to)


def search_pos_bills(date_from: str, date_to: str, limit: int = MAX_PAGE_SIZE, offset: int = 0) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Vrne DOC zapise iz /search za doc_type v ["sales_bill_domestic","sales_bill_foreign"].

    - date_from/date_to sta točno 'YYYY-MM-DD'
    - result_type: 'doc'
    - limit <= 100, paginacija z offset
    - query_advance = [{'type':'doc_date_from','value':date_from}, {'type':'doc_date_to','value':date_to}]
    Združi rezultate obeh doc_type in de-dupe po mk_id.
    Robustno izvleče mk_id in logira per-doc_type count + sample prvih 5.
    """
    base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
    url = f"{base}/search"
    merged: Dict[str, Dict[str, Any]] = {}
    page_lim = max(1, min(MAX_PAGE_SIZE, int(limit)))
    dfrom = str(date_from)[:10]
    dto = str(date_to)[:10]
    for dt in ['sales_bill_domestic','sales_bill_foreign']:
        payload = {
            'company_id': str(company_id),
            'secret': str(secret),
            'secret_key': str(secret),
            'doc_type': str(dt),
            'result_type': 'doc',
            'limit': page_lim,
            'offset': int(offset),
            'order_by': 'publish_ts',
            'order': 'desc',
            'query_advance': [
                {'type': 'doc_date_from', 'value': dfrom},
                {'type': 'doc_date_to',   'value': dto},
            ],
        }
        try:
            # READ op (search_pos_bills) — manj retry-jev
            dj = _mk_post_json_with_retry(url, payload, max_attempts=3, min_backoff=1.0, max_backoff=8.0)
        except Exception as e:
            current_app.logger.error(f"search_pos_bills error for {dt} offset={offset}: {e}")
            continue
        rows = dj if isinstance(dj, list) else (dj.get('rows') or dj.get('result') or dj.get('documents') or dj.get('docs') or dj.get('doc_list') or [])
        sample_pairs = []
        added = 0
        for rr in rows or []:
            mkid = extract_mk_id_from_search_doc(rr)
            if not mkid:
                continue
            if mkid not in merged:
                merged[mkid] = rr
                added += 1
            try:
                sample_pairs.append({'document_number': rr.get('document_number') or rr.get('count_code') or rr.get('title'), 'mk_id': mkid})
            except Exception:
                pass
        try:
            current_app.logger.info(f"search_pos_bills {dt}: count={len(rows or [])}, added_unique={added}, sample={sample_pairs[:5]}")
        except Exception:
            pass
    docs = list(merged.values())
    meta = {'count': len(docs), 'offset': offset, 'limit': page_lim}
    return docs, meta


# --- Strict retail search/fetch using ESHOP API ---
def search_retail_bills(date_from: str, date_to: str, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """Vrne surove dokumente (doc) iz /search za sales_bill_retail z query_advance datumi (YYYY-MM-DD+02:00)."""
    payload = {
        "doc_type": "sales_bill_retail",
        "result_type": "doc",
        "limit": max(1, min(int(limit), 100)),
        "offset": int(offset),
        "order_by": "publish_ts",
        "order": "desc",
        "query_advance": [
            {"type": "doc_date_from", "value": f"{str(date_from)[:10]}+02:00"},
            {"type": "doc_date_to",   "value": f"{str(date_to)[:10]}+02:00"},
        ],
    }
    resp = _http_post("/search", payload)
    return resp.get("doc_list") or resp.get("docs") or resp.get("result") or []


def debug_fetch_retail_first_n(take: int = 5) -> List[Dict[str, Any]]:
    """Debug helper: search first retail page (no date filter) and fetch first N via get_document.

    Returns list of {mk_id, publish_ts, items_len}.
    """
    # 1) search retail without date filters
    payload = {
        "doc_type": "sales_bill_retail",
        "result_type": "doc",
        "limit": 100,
        "offset": 0,
        "order_by": "publish_ts",
        "order": "desc",
    }
    resp = _http_post("/search", payload)
    docs = resp.get("doc_list") or resp.get("docs") or resp.get("result") or []
    ids: List[str] = []
    for d in docs:
        mid = d.get("mk_id") or d.get("id") or ((d.get("head") or {}).get("mk_id") if isinstance(d.get("head"), dict) else None)
        if mid:
            ids.append(str(mid))
        if len(ids) >= max(1, int(take)):
            break
    out: List[Dict[str, Any]] = []
    for mid in ids:
        bill = _http_post("/get_document", {
            "doc_type": "sales_bill_retail",
            "doc_id": str(mid),
            "return_publish_ts": True,
            "return_status_desc": True,
            "return_method_of_payment": True,
            "return_document_info": True,
            "return_product_compound": True,
            "return_allocated_cost_list": True,
            "show_tax_factor": True,
        })
        pub = bill.get("publish_ts") or ((bill.get("head") or {}).get("publish_ts") if isinstance(bill.get("head"), dict) else None)
        items_len = len(bill.get("product_list") or bill.get("item_list") or bill.get("rows") or bill.get("document_rows") or [])
        out.append({"mk_id": mid, "publish_ts": pub, "items_len": items_len})
    return out

def fetch_retail_bill_strict(doc_id: str) -> Dict[str, Any]:
    """Pridobi normaliziran retail račun iz /get_document (ESHOP), identificiran z doc_id."""
    payload = {
        "doc_type": "sales_bill_retail",
        "doc_id": str(doc_id),
        "return_publish_ts": True,
        "return_status_desc": True,
        "return_method_of_payment": True,
        "return_document_info": True,
        "return_product_compound": True,
        "return_allocated_cost_list": True,
        "show_tax_factor": True,
    }
    raw = _http_post("/get_document", payload)
    bill = _flatten_to_dict(raw)
    if not isinstance(bill, dict):
        raise RuntimeError("Unexpected get_document payload for retail bill")
    return bill


# (duplicate import_retail_window removed; consolidated earlier definition is used)


def fetch_retail_bill(mk_id: str) -> Dict[str, Any]:
    """Fetch bill via get_document(doc_type='bill') with full flags.

    Includes both 'secret' and 'secret_key' in the request body. Logs diagnostics.
    """
    base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
    if not base or not company_id or not secret:
        return {}
    url = f"{base}/get_document"
    payload = {
        'company_id': str(company_id),
        'secret': str(secret),
        'secret_key': str(secret),
        'doc_type': 'bill',
        'mk_id': str(mk_id),
        'return_publish_ts': True,
        'return_status_desc': True,
        'return_method_of_payment': True,
        'return_document_info': True,
        'return_product_compound': True,
        'return_allocated_cost_list': True,
        'show_tax_factor': True,
    }
    # Support servers expecting 'doc_id' instead of 'mk_id'
    payload['doc_id'] = payload['mk_id']
    dj: Dict[str, Any] = {}
    try:
        # READ op (fetch_retail_bill) — manj retry-jev
        dj = _mk_post_json_with_retry(url, payload, max_attempts=3, min_backoff=1.0, max_backoff=8.0)
    except Exception as e:
        current_app.logger.error(f"fetch_retail_bill error for mk_id={mk_id}: {e}")
        return {}
    # OPR code handling (if provided by API)
    try:
        code = dj.get('opr_code') if isinstance(dj, dict) else None
        if code is not None and str(code).strip() not in ('', '0'):
            desc = (dj.get('opr_desc') or 'MK error') if isinstance(dj, dict) else 'MK error'
            raise RuntimeError(f"MK get_document error {code}: {desc}")
    except Exception as e:
        current_app.logger.error(f"fetch_retail_bill MK error for mk_id={mk_id}: {e}")
        return {}
    try:
        items_len = len(dj.get('item_list') or dj.get('rows') or dj.get('document_rows') or dj.get('product_list') or [])
        di = {
            'mk_id': dj.get('mk_id') or mk_id,
            'document_number': dj.get('document_number') or dj.get('count_code') or dj.get('title'),
            'publish_ts': dj.get('publish_ts'),
            'furs_zoi': dj.get('furs_zoi'),
            'furs_eor': dj.get('furs_eor'),
            'items_len': items_len,
        }
        current_app.logger.debug(f"fetch_retail_bill diag: {di}")
    except Exception:
        pass
    return dj or {}


def dump_search_docs(date_from_iso: str, date_to_iso: str, max_docs: int = 200, out_file: str = "search_dump.json") -> Dict[str, Any]:
    """Dump up to max_docs search docs for retail doc types into a JSON file.

    Returns summary: {doc_types: {dt: count}, total, file, first_keys, first_ids}
    """
    import json as _json_local
    collected: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    offset = 0
    while len(collected) < int(max_docs):
        docs, _meta = search_pos_bills(date_from_iso, date_to_iso, limit=MAX_PAGE_SIZE, offset=offset)
        if not docs:
            break
        collected.extend(docs)
        offset += MAX_PAGE_SIZE
        if len(docs) < MAX_PAGE_SIZE:
            break
    first_keys = list(collected[0].keys()) if collected else []
    first_ids: List[str] = []
    for d in collected[:10]:
        mkid = extract_mk_id_from_search_doc(d)
        if mkid:
            first_ids.append(mkid)
        dt = str(d.get('doc_type') or '')
        counts[dt] = counts.get(dt, 0) + 1
    try:
        safe = []
        for d in collected:
            dd = dict(d)
            if 'secret' in dd:
                dd['secret'] = '***'
            safe.append(dd)
        with open(out_file, 'w') as f:
            _json_local.dump(safe[:max_docs], f, ensure_ascii=False, indent=2)
        current_app.logger.info(f"dump_search_docs wrote {min(len(safe), max_docs)} docs to {out_file}")
    except Exception as e:
        current_app.logger.error(f"dump_search_docs write error: {e}")
    return {'doc_types': counts, 'total': len(collected), 'file': out_file, 'first_keys': first_keys, 'first_ids': first_ids}


def dump_get_document_bills(mk_ids: List[str], take: int = 50, out_file: str = "bills_dump.json") -> Dict[str, Any]:
    """Fetch up to 'take' bills via get_document(bill) and write raw responses to file.

    Returns summary stats and examples.
    """
    import json as _json_local
    fetched = 0
    with_items = 0
    with_furs = 0
    examples: List[Dict[str, Any]] = []
    outputs: List[Dict[str, Any]] = []
    for sid in (mk_ids or [])[:max(1, int(take))]:
        d = fetch_retail_bill(str(sid)) or {}
        if not d:
            continue
        fetched += 1
        items_len = len(d.get('item_list') or d.get('rows') or d.get('document_rows') or [])
        if items_len:
            with_items += 1
        if d.get('furs_zoi') or d.get('furs_eor'):
            with_furs += 1
        try:
            examples.append({'mk_id': d.get('mk_id'), 'items': items_len, 'publish_ts': d.get('publish_ts')})
            dd = dict(d)
            if 'secret' in dd:
                dd['secret'] = '***'
            outputs.append(dd)
        except Exception:
            pass
    try:
        with open(out_file, 'w') as f:
            _json_local.dump(outputs, f, ensure_ascii=False, indent=2)
        current_app.logger.info(f"dump_get_document_bills wrote {len(outputs)} bills to {out_file}")
    except Exception as e:
        current_app.logger.error(f"dump_get_document_bills write error: {e}")
    return {'fetched': fetched, 'with_items': with_items, 'with_furs': with_furs, 'examples': examples[:10], 'file': out_file}

# Minimal CLI for direct smoke test
if __name__ == "__main__":
    import datetime as _dt
    _end = _dt.date.today()
    _start = _end - _dt.timedelta(days=14)
    _stats = import_retail_window(_start.isoformat(), _end.isoformat())
    print("RETAIL_IMPORT_STATS", _stats)


def _probe_retail_search_and_fetch(take: int = 3) -> list[dict]:
    """Return sample bills fetched via ESHOP get_document for retail."""
    docs = search_retail_bills("2025-08-22", "2025-08-29", limit=max(1, min(100, take)), offset=0)
    ids: list[str] = []
    for d in docs or []:
        mid = d.get("mk_id") or d.get("id") or ((d.get("head") or {}).get("mk_id") if isinstance(d.get("head"), dict) else None)
        if mid:
            ids.append(str(mid))
        if len(ids) >= take:
            break
    out: list[dict] = []
    for mid in ids:
        b = fetch_retail_bill_strict(mid)
        items = b.get("product_list") or b.get("item_list") or b.get("rows") or b.get("document_rows") or []
        out.append({"mk_id": mid, "publish_ts": b.get("publish_ts"), "items_len": len(items)})
    return out


def _probe_cash_journal_ids(days: int = 2) -> list[str]:
    from datetime import date as _date, timedelta as _td
    end = _date.today(); start = end - _td(days=days)
    ids, _meta = list_bill_ids_from_cash_journal(start.isoformat(), end.isoformat(), limit=100, offset=0)
    return ids[:10]