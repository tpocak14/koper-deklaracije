"""Machine-only mode: Flask je headless backend (webhooki + cron), ne UI.

Privzeto vklopljeno na Heroku (DYNO). Lokalno izklop: FLASK_MACHINE_ONLY=0.
"""
from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask


def machine_only_enabled() -> bool:
    raw = (os.environ.get("FLASK_MACHINE_ONLY") or "").strip().lower()
    if raw in ("0", "false", "off", "no"):
        return False
    if raw in ("1", "true", "on", "yes"):
        return True
    # Privzeto: na Heroku / produkciji ON
    return bool(os.environ.get("DYNO") or os.getenv("FLASK_ENV") == "production")


# Poti, ki ostanejo odprte (avtorizacijo še vedno uveljavljajo sami handlerji).
_PREFIX_ALLOW = (
    "/webhook/",
    "/api/internal/",
    "/apps/deklaracije/",
)

_EXACT_ALLOW = {
    "/webhook",
    "/api/internal",
    "/api/health",
    "/shopify/install",
    "/shopify/callback",
}

# Javni MK endpointi z lastnim secretom (X-MK-Secret).
_MK_SECRET_RE = re.compile(
    r"^/api/mk/(webhook/stock|.+/secret)$"
)

# Eksplicitno zaprto tudi znotraj sicer dovoljenih predpon.
_DENY_EXACT = {
    "/webhook/check-new-orders",
}


def is_machine_path_allowed(method: str, path: str) -> bool:
    if path in _DENY_EXACT:
        return False
    if path in _EXACT_ALLOW:
        return True
    if any(path.startswith(p) for p in _PREFIX_ALLOW):
        return True
    if _MK_SECRET_RE.match(path):
        return True
    # CORS preflight na dovoljenih poteh
    if method == "OPTIONS" and (
        path.startswith("/webhook")
        or path.startswith("/api/internal")
        or path.startswith("/api/mk/")
        or path.startswith("/apps/deklaracije/")
    ):
        return True
    return False


def register_machine_only_gate(app: "Flask") -> None:
    from flask import jsonify, request

    if not machine_only_enabled():
        app.logger.info("FLASK_MACHINE_ONLY=off — UI/API poti ostanejo odprte")
        return

    app.logger.warning(
        "FLASK_MACHINE_ONLY=on — dovoljeni samo webhooki, /api/internal, "
        "MK secret poti, storefront /apps/deklaracije, Shopify OAuth"
    )

    @app.before_request
    def _machine_only_gate():
        path = request.path or "/"
        method = request.method or "GET"
        if is_machine_path_allowed(method, path):
            return None
        # Ne razkrivaj, da gre za zaklep — 404 kot da pot ne obstaja.
        if path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
            return jsonify({
                "success": False,
                "error": "Not found",
                "machine_only": True,
            }), 404
        return ("Not found", 404)
