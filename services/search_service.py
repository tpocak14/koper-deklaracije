import re
import unicodedata
from database import get_db


def normalize_query(value: str) -> str:
    v = (value or "").strip().lower()
    if not v:
        return ""
    v = unicodedata.normalize("NFKD", v)
    v = v.encode("ascii", "ignore").decode("ascii")
    v = re.sub(r"[^\w\s-]+", " ", v)
    v = v.replace("-", " ")
    v = re.sub(r"\s+", " ", v).strip()
    return v


def find_synonym(shop_domain: str, phrase_norm: str) -> str | None:
    db = get_db()
    cur = db.cursor()
    cur.execute(
        """
        SELECT target_code
        FROM search_synonyms
        WHERE shop_domain = %s AND phrase_norm = %s
        """,
        (shop_domain, phrase_norm),
    )
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return row["target_code"] if isinstance(row, dict) else row[0]


def upsert_synonym(shop_domain: str, phrase: str, target_code: str) -> int:
    phrase_norm = normalize_query(phrase)
    db = get_db()
    cur = db.cursor()
    cur.execute(
        """
        INSERT INTO search_synonyms (shop_domain, phrase_norm, phrase_raw, target_code)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (shop_domain, phrase_norm)
        DO UPDATE SET
          phrase_raw = EXCLUDED.phrase_raw,
          target_code = EXCLUDED.target_code,
          updated_at = CURRENT_TIMESTAMP
        RETURNING id
        """,
        (shop_domain, phrase_norm, phrase.strip(), target_code.lower()),
    )
    row = cur.fetchone()
    db.commit()
    cur.close()
    return row["id"] if isinstance(row, dict) else row[0]


def upsert_inspo_target(
    shop_domain: str,
    target_code: str,
    product_handle: str | None = None,
    product_id: int | None = None,
) -> int:
    db = get_db()
    cur = db.cursor()
    cur.execute(
        """
        INSERT INTO inspo_targets (shop_domain, target_code, product_handle, product_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (shop_domain, target_code)
        DO UPDATE SET
          product_handle = COALESCE(EXCLUDED.product_handle, inspo_targets.product_handle),
          product_id = COALESCE(EXCLUDED.product_id, inspo_targets.product_id),
          updated_at = CURRENT_TIMESTAMP
        RETURNING id
        """,
        (shop_domain, target_code.lower(), product_handle, product_id),
    )
    row = cur.fetchone()
    db.commit()
    cur.close()
    return row["id"] if isinstance(row, dict) else row[0]
