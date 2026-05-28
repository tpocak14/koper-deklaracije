"""
Centralna preusmeritev prejemnikov (test / monitoring).

Nastavi env `EMAIL_REDIRECT_TO=pocak.tomas@gmail.com` — vsi odhodni
maili (Mandrill + SMTP) gredo na ta naslov. Subject dobi prefix
`[→ original@...]`.

Izklop: odstrani env var.
"""
from __future__ import annotations

import os
from typing import List, Optional, Tuple


def resolve_recipient(original_to: str) -> Tuple[str, str, bool]:
    """
    Returns:
        (actual_to, subject_prefix, was_redirected)
    """
    original = (original_to or "").strip()
    redirect = (os.environ.get("EMAIL_REDIRECT_TO") or "").strip()

    if redirect and redirect.lower() != original.lower():
        return redirect, f"[→ {original}] ", True

    return original, "", False


def resolve_recipient_list(
    recipients: List[dict],
) -> Tuple[List[dict], str, bool]:
    """
    Za Mandrill `to` seznam. Pri redirectu zamenja vse prejemnike z enim admin.
    """
    if not recipients:
        return recipients, "", False

    originals = ",".join(r.get("email", "") for r in recipients if r.get("email"))
    redirect = (os.environ.get("EMAIL_REDIRECT_TO") or "").strip()

    if not redirect:
        return recipients, "", False

    if len(recipients) == 1 and recipients[0].get("email", "").strip().lower() == redirect.lower():
        return recipients, "", False

    name = recipients[0].get("name") or redirect
    return [{"email": redirect, "name": name, "type": "to"}], f"[→ {originals}] ", True
