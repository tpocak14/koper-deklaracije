"""Uvozi popravljena ime_parfuma iz CSV."""

from __future__ import annotations

import csv
import io
from typing import Any

from flask import current_app

from database import get_db


def _normalize_headers(fieldnames: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in fieldnames or []:
        key = h.strip().lower()
        if key in ("id", "proizvajalec_id", "ime_parfuma"):
            out[key] = h
        elif key in ("proizvajalec", "ime proizvajalca"):
            out["proizvajalec"] = h
        elif key in ("product_no", "šifra izdelka (product no)", "sifra izdelka", "šifra izdelka"):
            out["product_no"] = h
        elif key in ("ime parfuma",):
            out["ime_parfuma"] = h
    return out


def import_parfumi_names_from_csv(
    file_bytes: bytes,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Posodobi samo ime_parfuma.

    Podprti formati:
      - UI: proizvajalec, product_no, ime_parfuma
      - legacy: id, proizvajalec_id, ime_parfuma
    """
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    col = _normalize_headers(reader.fieldnames)

    use_ui = "proizvajalec" in col and "product_no" in col and "ime_parfuma" in col
    use_id = "id" in col and "proizvajalec_id" in col and "ime_parfuma" in col
    if not use_ui and not use_id:
        return {
            "ok": False,
            "error": (
                "CSV mora imeti stolpce (Proizvajalec, Šifra izdelka, Ime parfuma) "
                "ali (id, proizvajalec_id, ime_parfuma)."
            ),
        }

    db = get_db()
    cursor = db.cursor()
    result: dict[str, Any] = {
        "ok": False,
        "dry_run": dry_run,
        "format": "ui" if use_ui else "id",
        "rows_in_file": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "errors": [],
        "samples": [],
    }

    try:
        for raw in reader:
            result["rows_in_file"] += 1
            new_name = (raw.get(col["ime_parfuma"]) or "").strip()
            if not new_name:
                result["skipped"] += 1
                continue

            if use_ui:
                proizvajalec = (raw.get(col["proizvajalec"]) or "").strip()
                product_no = (raw.get(col["product_no"]) or "").strip()
                if not proizvajalec or not product_no:
                    result["skipped"] += 1
                    continue
                cursor.execute(
                    """
                    SELECT p.id, p.ime_parfuma
                    FROM parfumi p
                    JOIN proizvajalci pr ON pr.id = p.proizvajalec_id
                    WHERE p.product_no = %s AND pr.ime = %s
                    """,
                    (product_no, proizvajalec),
                )
                existing = cursor.fetchone()
                if not existing:
                    result["skipped"] += 1
                    if len(result["errors"]) < 20:
                        result["errors"].append(
                            f"{proizvajalec} / {product_no}: ni v bazi"
                        )
                    continue
                parfum_id = existing["id"] if isinstance(existing, dict) else existing[0]
                current_name = existing["ime_parfuma"] if isinstance(existing, dict) else existing[1]
                sample_key = {"proizvajalec": proizvajalec, "product_no": product_no}
            else:
                try:
                    parfum_id = int((raw.get(col["id"]) or "").strip())
                    proizvajalec_id = int((raw.get(col["proizvajalec_id"]) or "").strip())
                except ValueError:
                    result["skipped"] += 1
                    continue
                cursor.execute(
                    "SELECT id, proizvajalec_id, ime_parfuma FROM parfumi WHERE id = %s",
                    (parfum_id,),
                )
                existing = cursor.fetchone()
                if not existing:
                    result["skipped"] += 1
                    continue
                ex_pid = existing["proizvajalec_id"] if isinstance(existing, dict) else existing[1]
                if ex_pid != proizvajalec_id:
                    result["skipped"] += 1
                    continue
                current_name = existing["ime_parfuma"] if isinstance(existing, dict) else existing[2]
                sample_key = {"id": parfum_id, "proizvajalec_id": proizvajalec_id}

            if current_name == new_name:
                result["unchanged"] += 1
                continue

            if not dry_run:
                cursor.execute(
                    "UPDATE parfumi SET ime_parfuma = %s, updated_at = NOW() WHERE id = %s",
                    (new_name, parfum_id),
                )

            result["updated"] += 1
            if len(result["samples"]) < 25:
                result["samples"].append({**sample_key, "from": current_name, "to": new_name})

        if not dry_run:
            db.commit()
        else:
            db.rollback()

        result["ok"] = True
        return result
    except Exception as exc:
        db.rollback()
        current_app.logger.error(f"import_parfumi_names_from_csv failed: {exc}")
        result["error"] = str(exc)
        return result
    finally:
        cursor.close()
