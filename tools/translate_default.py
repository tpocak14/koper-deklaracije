import argparse
import csv
import json
import os
import time
from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

from flask import Flask
from services.shopify_service import _get_api_url, _get_shopify_headers, _normalize_shop_domain


def normalize_shopify_id(value: str) -> str | None:
    if value is None:
        return None
    v = str(value).strip().strip("'").strip('"')
    if not v:
        return None
    if v.isdigit():
        return v
    if v.startswith("gid://"):
        parts = v.split("/")
        if parts and parts[-1].isdigit():
            return parts[-1]
    return None


class RateLimiter:
    def __init__(self, min_interval_s: float = 0.2):
        self.min_interval_s = min_interval_s
        self._next_allowed = 0.0

    def wait(self):
        now = time.time()
        if now < self._next_allowed:
            time.sleep(self._next_allowed - now)
        self._next_allowed = time.time() + self.min_interval_s


def request_with_retry(method: str, url: str, headers: dict, json_body: dict, limiter: RateLimiter, max_retries: int = 5):
    backoff = 0.5
    for attempt in range(max_retries):
        limiter.wait()
        try:
            import requests
            resp = requests.request(method, url, headers=headers, json=json_body, timeout=10)
            if resp.status_code in (429,) or 500 <= resp.status_code < 600:
                raise RuntimeError(f"HTTP {resp.status_code}")
            return resp
        except Exception:
            if attempt == max_retries - 1:
                raise
            time.sleep(backoff)
            backoff *= 2


def read_translations_csv(path: str, locale: str):
    translations = {
        "product": {},
        "collection": {},
        "page": {},
    }
    ignored_by_type = defaultdict(int)
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            lower = {k.strip().lower(): v for k, v in row.items() if k}
            r_type = (lower.get("type") or "").strip().lower()
            if r_type not in ("product", "collection", "page"):
                if r_type:
                    ignored_by_type[r_type] += 1
                continue
            row_locale = (lower.get("locale") or "").strip().lower()
            if row_locale != locale.lower():
                continue
            field = (lower.get("field") or "").strip().lower()
            identification = lower.get("identification") or ""
            trans_val = lower.get("translated content") or lower.get("translated_content") or ""
            sid = normalize_shopify_id(identification)
            if not sid:
                continue
            data = translations[r_type].setdefault(sid, {})
            if field in ("title",):
                data["title"] = trans_val
            elif field in ("body_html", "description_html"):
                data["body_html"] = trans_val
    return translations, ignored_by_type


def load_cache(path: str, no_cache: bool):
    if no_cache or not os.path.exists(path):
        return {"handle_to_id": {}, "missing_handles": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cache(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def gql_handle_lookup(entity: str) -> str:
    # entity: product, collection, page
    return f"""
    query ($handle: String!) {{
      {entity}ByHandle(handle: $handle) {{
        id
        handle
      }}
    }}
    """


def get_handle_to_id(handles: Iterable[str], entity: str, shop_domain: str | None, cache_path: str, no_cache: bool):
    limiter = RateLimiter(0.2)
    cache = load_cache(cache_path, no_cache)
    handle_to_id = cache.get("handle_to_id", {})
    missing_handles = set(cache.get("missing_handles", []))

    query = gql_handle_lookup(entity)
    api_url = _get_api_url(shop_domain=shop_domain)
    headers = _get_shopify_headers(shop_domain)

    fetched = 0
    from_cache = 0
    for handle in handles:
        if handle in handle_to_id:
            from_cache += 1
            continue
        if handle in missing_handles:
            from_cache += 1
            continue
        try:
            resp = request_with_retry(
                "POST",
                api_url,
                headers,
                {"query": query, "variables": {"handle": handle}},
                limiter,
            )
            data = resp.json()
            if data.get("errors"):
                raise RuntimeError(f"GraphQL errors: {data['errors']}")
            node = (data.get("data") or {}).get(f"{entity}ByHandle")
            if node and node.get("id"):
                sid = normalize_shopify_id(node["id"])
                if sid:
                    handle_to_id[handle] = sid
                else:
                    missing_handles.add(handle)
            else:
                missing_handles.add(handle)
            fetched += 1
        except Exception:
            missing_handles.add(handle)

    # Fallback for pages: REST list + match by handle
    if entity == "page" and missing_handles:
        try:
            rest_map = _fetch_pages_handle_map(shop_domain, limiter)
            for h in list(missing_handles):
                if h in rest_map:
                    handle_to_id[h] = rest_map[h]
                    missing_handles.discard(h)
        except Exception:
            pass

    cache["handle_to_id"] = handle_to_id
    cache["missing_handles"] = sorted(missing_handles)
    save_cache(cache_path, cache)
    return handle_to_id, {"from_cache": from_cache, "fetched": fetched, "missing": len(missing_handles)}


def resolve_collection_body_column(fieldnames: List[str]) -> str | None:
    candidates = ["Body (HTML)", "Description", "Description HTML", "Body"]
    for c in candidates:
        if c in fieldnames:
            return c
    return None


def merge_translations_into_export(
    export_path: str,
    out_path: str,
    entity: str,
    translations_map: Dict[str, Dict[str, str]],
    handle_to_id: Dict[str, str],
    dry_run: bool,
):
    updated_title = 0
    updated_body = 0
    missing_id = []

    with open(export_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    if entity == "product":
        title_col = "Title"
        body_col = "Body (HTML)"
    elif entity == "collection":
        title_col = "Title"
        body_col = resolve_collection_body_column(fieldnames)
    else:
        title_col = "Title"
        body_col = "Body (HTML)"

    for row in rows:
        handle = row.get("Handle") or ""
        sid = handle_to_id.get(handle)
        if not sid:
            continue
        tdata = translations_map.get(sid)
        if not tdata:
            continue
        if tdata.get("title") is not None and title_col in row:
            row[title_col] = tdata["title"]
            updated_title += 1
        if tdata.get("body_html") is not None and body_col and body_col in row:
            row[body_col] = tdata["body_html"]
            updated_body += 1

    if not dry_run:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    return updated_title, updated_body, missing_id


def main():
    parser = argparse.ArgumentParser(description="Move translated EN content to default export CSVs.")
    parser.add_argument("--translations", required=True, nargs="+")
    parser.add_argument("--products")
    parser.add_argument("--collections")
    parser.add_argument("--pages")
    parser.add_argument("--locale", default="en")
    parser.add_argument("--outDir", default="./out")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--shop", help="Shop domain (optional)")
    args = parser.parse_args()

    app = Flask(__name__)
    # Minimal config needed for Shopify API usage
    app.config['SHOP_NAME'] = os.getenv('SHOP_NAME', 'parfumerija-amour')
    app.config['SHOPIFY_API_PASSWORD'] = os.getenv('SHOPIFY_API_PASSWORD')
    app.config['SHOPIFY_API_VERSION'] = os.getenv('SHOPIFY_API_VERSION', '2025-01')
    with app.app_context():
        shop_domain = _normalize_shop_domain(args.shop) if args.shop else None

        translations = {"product": {}, "collection": {}, "page": {}}
        ignored = defaultdict(int)
        for tpath in args.translations:
            tmap, ign = read_translations_csv(tpath, args.locale)
            for k in ("product", "collection", "page"):
                translations[k].update(tmap.get(k, {}))
            for k, v in ign.items():
                ignored[k] += v

        stats = {
            "products": {"title": 0, "body": 0},
            "collections": {"title": 0, "body": 0},
            "pages": {"title": 0, "body": 0},
        }
        missing = {"products": [], "collections": [], "pages": []}
        not_found = {"products": [], "collections": [], "pages": []}

        unmapped = {"products": [], "collections": [], "pages": []}

        if args.products:
            handles = _read_handles(args.products)
            handle_to_id, cache_stats = get_handle_to_id(
                handles, "product", shop_domain, ".cache/map_products.json", args.no_cache
            )
            id_to_handle = {v: k for k, v in handle_to_id.items()}
            out_path = os.path.join(args.outDir, "products_en_default.csv")
            t, b, _ = merge_translations_into_export(
                args.products, out_path, "product", translations["product"], handle_to_id, args.dry_run
            )
            stats["products"]["title"] = t
            stats["products"]["body"] = b
            not_found["products"] = _missing_handles(handles, handle_to_id)
            unmapped["products"] = [k for k in translations["product"].keys() if k not in id_to_handle]
            _log_cache_stats("products", cache_stats)

        if args.collections:
            handles = _read_handles(args.collections)
            handle_to_id, cache_stats = get_handle_to_id(
                handles, "collection", shop_domain, ".cache/map_collections.json", args.no_cache
            )
            id_to_handle = {v: k for k, v in handle_to_id.items()}
            out_path = os.path.join(args.outDir, "collections_en_default.csv")
            t, b, _ = merge_translations_into_export(
                args.collections, out_path, "collection", translations["collection"], handle_to_id, args.dry_run
            )
            stats["collections"]["title"] = t
            stats["collections"]["body"] = b
            not_found["collections"] = _missing_handles(handles, handle_to_id)
            unmapped["collections"] = [k for k in translations["collection"].keys() if k not in id_to_handle]
            _log_cache_stats("collections", cache_stats)

        if args.pages:
            handles = _read_handles(args.pages)
            handle_to_id, cache_stats = get_handle_to_id(
                handles, "page", shop_domain, ".cache/map_pages.json", args.no_cache
            )
            id_to_handle = {v: k for k, v in handle_to_id.items()}
            out_path = os.path.join(args.outDir, "pages_en_default.csv")
            t, b, _ = merge_translations_into_export(
                args.pages, out_path, "page", translations["page"], handle_to_id, args.dry_run
            )
            stats["pages"]["title"] = t
            stats["pages"]["body"] = b
            not_found["pages"] = _missing_handles(handles, handle_to_id)
            unmapped["pages"] = [k for k in translations["page"].keys() if k not in id_to_handle]
            _log_cache_stats("pages", cache_stats)

        _print_report(stats, not_found, unmapped, ignored)


def _read_handles(path: str) -> List[str]:
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return [row.get("Handle") for row in reader if row.get("Handle")]


def _missing_handles(handles: Iterable[str], handle_to_id: Dict[str, str]) -> List[str]:
    return [h for h in handles if h not in handle_to_id]


def _log_cache_stats(label: str, stats: dict):
    print(f"[{label}] cache: {stats.get('from_cache', 0)} from cache, {stats.get('fetched', 0)} fetched, missing={stats.get('missing', 0)}")


def _print_report(stats, not_found, unmapped, ignored):
    print("=== Report ===")
    for t in ("products", "collections", "pages"):
        print(f"{t}: title updated={stats[t]['title']} body updated={stats[t]['body']}")
        missing = not_found[t]
        if missing:
            print(f"{t}: handles not found={len(missing)} sample={missing[:20]}")
        unmapped_ids = unmapped.get(t) or []
        if unmapped_ids:
            print(f"{t}: translations without mapping={len(unmapped_ids)} sample={unmapped_ids[:20]}")
    if ignored:
        print("Ignored translations by type:")
        for k, v in ignored.items():
            print(f"  {k}: {v}")


def _fetch_pages_handle_map(shop_domain: str | None, limiter: RateLimiter) -> Dict[str, str]:
    api_url = _get_api_url(endpoint="pages.json", shop_domain=shop_domain)
    headers = _get_shopify_headers(shop_domain)
    pages = []
    since_id = 0
    import requests
    while True:
        limiter.wait()
        resp = requests.get(api_url, headers=headers, params={"limit": 250, "since_id": since_id}, timeout=10)
        if resp.status_code in (429,) or 500 <= resp.status_code < 600:
            raise RuntimeError(f"HTTP {resp.status_code}")
        data = resp.json() or {}
        batch = data.get("pages") or []
        if not batch:
            break
        pages.extend(batch)
        since_id = batch[-1]["id"]
    return {p["handle"]: str(p["id"]) for p in pages if p.get("handle") and p.get("id")}


if __name__ == "__main__":
    main()
