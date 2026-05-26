"""
services/mandrill_service.py
============================

Tanek wrapper okoli Mandrill API (https://mandrillapp.com/api/1.0/).

Uporaba v naši aplikaciji:

  1. Customer safety net (declaration_safety_net.py):
     Ko je MK sales_order že "completed" in priponka manjka, MK ne bo več
     sam sprožil Mandrill template-a (njegov trigger je vezan na status
     change "shipped" → "completed"). Naša aplikacija takrat direktno
     pokliče Mandrill API s template-om 'deklaracije_si' in stranka dobi
     pravi mail z deklaracijo v prilogi.

  2. Mandrill messages/info za verifikacijo statusa pošiljanja.

  3. Mandrill webhook payload utility za incoming events (delivered,
     bounced, ...) - opcijsko (ni nujno potrebno).

OPOMBA o API key-u:
  Trenutno uporabljamo SAM Mandrill račun kot MetaKocka — MetaKocka pošilja
  prek template-a 'deklaracije_si', mi pošljemo prek istega template-a, da
  ostane vizualno konsistentno za stranko. API key je v env var
  MANDRILL_API_KEY.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any, Dict, Iterable, List, Optional

import requests

logger = logging.getLogger(__name__)

MANDRILL_BASE_URL = "https://mandrillapp.com/api/1.0"
DEFAULT_TIMEOUT = 30  # sekund


class MandrillError(Exception):
    """Splošna napaka pri klicu Mandrill API-ja."""

    def __init__(self, message: str, *, status_code: Optional[int] = None,
                 payload: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def _api_key() -> str:
    key = os.environ.get("MANDRILL_API_KEY", "").strip()
    if not key:
        raise MandrillError(
            "MANDRILL_API_KEY ni nastavljen v env (Heroku config). "
            "Pridobi key na https://mandrillapp.com/settings/index in ga "
            "vstavi z `heroku config:set MANDRILL_API_KEY=...`."
        )
    return key


def _post(endpoint: str, body: Dict[str, Any], *, timeout: int = DEFAULT_TIMEOUT) -> Any:
    url = f"{MANDRILL_BASE_URL}/{endpoint.lstrip('/')}"
    payload = {"key": _api_key(), **body}
    try:
        r = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as e:
        raise MandrillError(f"Mandrill HTTP failure on {endpoint}: {e}") from e

    if r.status_code >= 400:
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text[:500]}
        raise MandrillError(
            f"Mandrill {endpoint} returned HTTP {r.status_code}: {data}",
            status_code=r.status_code,
            payload=data if isinstance(data, dict) else None,
        )
    try:
        return r.json()
    except ValueError as e:
        raise MandrillError(f"Mandrill {endpoint}: invalid JSON response") from e


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ping() -> bool:
    """Preveri, da API key dela. Vrne True/False (ne raise-a)."""
    try:
        resp = _post("users/ping.json", {})
        return resp == "PONG!" or resp is not None
    except MandrillError as e:
        logger.warning("Mandrill ping failed: %s", e)
        return False


def template_info(name: str) -> Optional[Dict[str, Any]]:
    """Pridobi info o template-u. Vrne None, če ne obstaja."""
    try:
        return _post("templates/info.json", {"name": name})
    except MandrillError as e:
        if e.status_code == 500 or (e.payload and e.payload.get("name") == "Unknown_Template"):
            return None
        raise


def send_template(
    *,
    template_name: str,
    to: List[Dict[str, str]],
    global_merge_vars: List[Dict[str, Any]],
    attachments: Optional[List[Dict[str, Any]]] = None,
    from_email: str = "orders@amourparfums.com",
    from_name: str = "AMOUR Parfums",
    subject: Optional[str] = None,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, str]] = None,
    bcc_address: Optional[str] = None,
    merge_language: str = "mailchimp",
    track_opens: bool = True,
    track_clicks: bool = True,
    inline_css: bool = True,
    async_send: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[Dict[str, Any]]:
    """
    Pošlje Mandrill template z opcijsko PDF prilogo.

    Args:
        template_name: ime template-a v Mandrill (npr. 'deklaracije_si')
        to: seznam prejemnikov, [{'email': '...', 'name': '...'}]
        global_merge_vars: globalni merge variables ([{'name': 'key', 'content': 'val'}])
        attachments: seznam PDF prilog [{'filename': str, 'data': bytes}]
        tags: seznam tag-ov za Mandrill filtriranje (npr. ['safety-net', 'SI2377'])
        metadata: poljubne ključ-vrednost metadata (max ~10 ključev)
        bcc_address: slepa kopija (BCC) na naslov za admin nadzor. Kupec ne
            vidi tega naslova v glavah maila. Uporablja se za monitoring
            deklaracij prek `ADMIN_BCC_DECLARATION_EMAIL` env var.

    Returns:
        seznam [{'_id': str, 'email': str, 'status': 'sent'|'queued'|'rejected'|'invalid',
                 'reject_reason': str|None}]

    Raises:
        MandrillError: če API klic ni uspel
    """
    message: Dict[str, Any] = {
        "from_email": from_email,
        "from_name": from_name,
        "to": [
            {"email": r["email"], "name": r.get("name") or r["email"], "type": "to"}
            for r in to
        ],
        "global_merge_vars": global_merge_vars,
        "merge": True,
        "merge_language": merge_language,
        "track_opens": track_opens,
        "track_clicks": track_clicks,
        "inline_css": inline_css,
    }

    if subject:
        message["subject"] = subject
    if tags:
        message["tags"] = list(tags)
    if metadata:
        message["metadata"] = dict(metadata)
    if bcc_address:
        # Mandrill BCC: posebno polje, ne v `to` array. Mandrill na ta naslov
        # pošlje ločen mail, ki ni vidno kupcu (ni v To/Cc glavah).
        message["bcc_address"] = bcc_address

    if attachments:
        message["attachments"] = [
            {
                "type": a.get("type", "application/pdf"),
                "name": a["filename"],
                "content": base64.b64encode(a["data"]).decode("ascii"),
            }
            for a in attachments
        ]

    body = {
        "template_name": template_name,
        "template_content": [],
        "message": message,
        "async": bool(async_send),
    }

    logger.info(
        "Mandrill send-template: name=%s, to=%s, attachments=%d, tags=%s",
        template_name,
        ",".join(r["email"] for r in to),
        len(attachments) if attachments else 0,
        tags,
    )
    return _post("messages/send-template.json", body, timeout=timeout)


def messages_info(message_id: str) -> Dict[str, Any]:
    """
    Pridobi trenutni status sporočila.

    Returns dict z 'state' (sent|queued|scheduled|rejected|invalid|bounced|
    soft-bounced|spam|unsub|...) in dodatki ('opens', 'clicks', 'ts', ...).

    Raises:
        MandrillError: če klic ni uspel ali sporočilo ne obstaja
    """
    return _post("messages/info.json", {"id": message_id})


def messages_search(
    *,
    query: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    tags: Optional[List[str]] = None,
    senders: Optional[List[str]] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Iskanje poslanih sporočil. Query je Mandrill search syntax,
    npr. 'order_id:SI2377' ali 'email:edina.beganovic78@gmail.com'.

    Pomembno: 'metadata.order_id:SI2377' deluje le, če smo pri send-template
    poslali metadata={'order_id': '...'}. Brez tega iskanje po naslovu
    ali email-u prejemnika.
    """
    body: Dict[str, Any] = {"query": query, "limit": limit}
    if date_from:
        body["date_from"] = date_from
    if date_to:
        body["date_to"] = date_to
    if tags:
        body["tags"] = tags
    if senders:
        body["senders"] = senders
    return _post("messages/search.json", body)


# ---------------------------------------------------------------------------
# Convenience helpers for our use case
# ---------------------------------------------------------------------------

def is_terminal_status(state: str) -> bool:
    """Vrne True, če Mandrill 'state' pomeni, da ne pričakujemo več sprememb."""
    return state in {
        "sent",
        "delivered",
        "opened",
        "clicked",
        "rejected",
        "invalid",
        "bounced",
        "soft-bounced",
        "spam",
        "unsub",
    }


def is_failure_status(state: str) -> bool:
    """Vrne True, če gre za napako, kjer admin mora ročno reševati."""
    return state in {"rejected", "invalid", "bounced", "soft-bounced", "spam"}
