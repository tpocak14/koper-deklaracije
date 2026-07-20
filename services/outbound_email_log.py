"""
services/outbound_email_log.py
==============================

Skupni helperji (deljeni z app-v2 prek skupne Neon baze) za:

  1. Branje persistiranih `app_settings` (key/value) — ista tabela, ki jo
     uporablja app-v2.
  2. Razrešitev admin BCC za DEKLARACIJSKE maile iz `app_settings`
     (`admin_bcc_enabled` + `admin_email`), z env fallback-om.
  3. Beleženje vsakega odhodnega e-maila (vsebina + priloga) v skupno tabelo
     `outbound_email_log`, da lahko kopijo pregledamo v aplikaciji.

Načelne odločitve:
  - Beleženje uporablja LASTNO kratkotrajno DB povezavo, da napaka pri zapisu
    (ali commit) NIKOLI ne poseže v transakcijo request-a / background joba.
  - Beleženje je popolnoma NON-FATAL (ovito v try/except); napaka pri logiranju
    nikoli ne prekine ali blokira dejanskega pošiljanja e-pošte.
  - Tabela se ustvari idempotentno prek `ensure_outbound_email_log_table()`
    (enak vzorec kot _ensure_*_table() helperji v services/mk_service.py).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import psycopg
from psycopg.types.json import Json
from flask import current_app

from database import get_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# app_settings branje (ista tabela kot app-v2: stolpca key, value)
# ---------------------------------------------------------------------------

def get_app_setting(key: str) -> Optional[str]:
    """Vrne `value` iz `app_settings` za dani `key` (ali None). Non-fatal.

    Uporablja request/job povezavo (get_db()). Če tabela/branje spodleti,
    vrne None, da klicalec lahko pade nazaj na env.
    """
    try:
        cur = get_db().cursor()
        try:
            cur.execute("SELECT value FROM app_settings WHERE key = %s", (key,))
            row = cur.fetchone()
        finally:
            try:
                cur.close()
            except Exception:
                pass
        if not row:
            return None
        if isinstance(row, dict):
            return row.get("value")
        return row[0]
    except Exception as e:
        logger.warning("get_app_setting(%s) failed: %s", key, e)
        return None


def resolve_admin_bcc() -> Optional[str]:
    """Admin BCC za deklaracijske maile — glavni vir resnice je DB toggle.

    Prednost (kot v app-v2):
      1. `app_settings.admin_bcc_enabled` ('true'/'false'):
         - če 'true' in je `admin_email` nastavljen → BCC = admin_email
         - če 'false' (ali admin_email prazen) → brez BCC (None)
      2. Če ključa `admin_bcc_enabled` v app_settings SPLOH NI (setting ni
         prisoten), pade nazaj na env `ADMIN_BCC_DECLARATION_EMAIL`.

    DB toggle torej vedno prevlada nad env-om; env je le fallback, ko nastavitev
    ne obstaja.
    """
    try:
        enabled_raw = get_app_setting("admin_bcc_enabled")
        if enabled_raw is not None:
            # DB toggle je prisoten → avtoritativen (brez env fallback-a).
            if str(enabled_raw).strip().lower() == "true":
                admin_email = (get_app_setting("admin_email") or "").strip()
                return admin_email or None
            return None
    except Exception as e:
        logger.warning("resolve_admin_bcc settings read failed: %s", e)

    # Setting ni prisoten → env fallback (ohrani obstoječe vedenje).
    return (os.environ.get("ADMIN_BCC_DECLARATION_EMAIL", "") or "").strip() or None


# ---------------------------------------------------------------------------
# outbound_email_log tabela (idempotentno ustvarjanje + zapis)
# ---------------------------------------------------------------------------

_TABLE_ENSURED = False

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS outbound_email_log (
  id BIGSERIAL PRIMARY KEY,
  email_type TEXT NOT NULL,
  channel TEXT,
  sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  recipient_to TEXT,
  recipient_bcc TEXT,
  subject TEXT,
  from_email TEXT,
  from_name TEXT,
  mandrill_message_id TEXT,
  status TEXT,
  error TEXT,
  order_number TEXT,
  order_send_id INTEGER,
  html_content TEXT,
  text_content TEXT,
  template_name TEXT,
  merge_vars JSONB,
  attachment_name TEXT,
  attachment_mime TEXT,
  attachment_content BYTEA,
  sent_by_user_id INTEGER,
  sent_by_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_CREATE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_outbound_email_log_sent_at "
    "ON outbound_email_log (sent_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_outbound_email_log_type "
    "ON outbound_email_log (email_type, sent_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_outbound_email_log_order "
    "ON outbound_email_log (order_number);",
)


def ensure_outbound_email_log_table(conn=None) -> bool:
    """Ustvari `outbound_email_log` + indekse (idempotentno).

    Args:
        conn: opcijska obstoječa psycopg povezava. Če je None, se odpre in
            zapre lastna kratkotrajna povezava (uporabi DATABASE_URL).

    Returns:
        True ob uspehu. Napake pusti klicalcu (endpoint jih poroča).
    """
    own = False
    if conn is None:
        conn = psycopg.connect(current_app.config["DATABASE_URL"])
        own = True
    try:
        with conn.cursor() as c:
            c.execute(_CREATE_TABLE_SQL)
            for idx_sql in _CREATE_INDEX_SQL:
                c.execute(idx_sql)
        conn.commit()
        return True
    finally:
        if own:
            try:
                conn.close()
            except Exception:
                pass


def log_outbound_email(
    *,
    email_type: str,
    channel: str = "flask",
    recipient_to: Optional[str] = None,
    recipient_bcc: Optional[str] = None,
    subject: Optional[str] = None,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
    mandrill_message_id: Optional[str] = None,
    status: Optional[str] = None,
    error: Optional[str] = None,
    order_number: Optional[str] = None,
    order_send_id: Optional[int] = None,
    html_content: Optional[str] = None,
    text_content: Optional[str] = None,
    template_name: Optional[str] = None,
    merge_vars: Optional[Any] = None,
    attachment_name: Optional[str] = None,
    attachment_mime: Optional[str] = None,
    attachment_content: Optional[bytes] = None,
    sent_by_user_id: Optional[int] = None,
    sent_by_name: Optional[str] = None,
) -> None:
    """Zapiši en odhodni e-mail v `outbound_email_log`. VEDNO non-fatal.

    Uporablja LASTNO povezavo (ne g.db), da zapis/commit ne poseže v
    transakcijo klicalca. Kakršnakoli napaka je pogoltnjena (samo warning log),
    da beleženje nikoli ne prekine ali blokira dejanskega pošiljanja.
    """
    global _TABLE_ENSURED
    conn = None
    try:
        conn = psycopg.connect(current_app.config["DATABASE_URL"])

        if not _TABLE_ENSURED:
            try:
                ensure_outbound_email_log_table(conn)
                _TABLE_ENSURED = True
            except Exception as e:
                logger.warning("ensure outbound_email_log table failed: %s", e)

        with conn.cursor() as c:
            c.execute(
                """
                INSERT INTO outbound_email_log (
                    email_type, channel, recipient_to, recipient_bcc, subject,
                    from_email, from_name, mandrill_message_id, status, error,
                    order_number, order_send_id, html_content, text_content,
                    template_name, merge_vars, attachment_name, attachment_mime,
                    attachment_content, sent_by_user_id, sent_by_name
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    email_type,
                    channel,
                    recipient_to,
                    recipient_bcc,
                    subject,
                    from_email,
                    from_name,
                    mandrill_message_id,
                    status,
                    (str(error)[:8000] if error is not None else None),
                    order_number,
                    order_send_id,
                    html_content,
                    text_content,
                    template_name,
                    (Json(merge_vars) if merge_vars is not None else None),
                    attachment_name,
                    attachment_mime,
                    attachment_content,
                    sent_by_user_id,
                    sent_by_name,
                ),
            )
        conn.commit()
    except Exception as e:
        # Non-fatal: beleženje nikoli ne sme prekiniti pošiljanja.
        logger.warning("log_outbound_email failed (non-fatal): %s", e)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
