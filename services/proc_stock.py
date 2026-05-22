"""Helpers for adjusting `proc_products.on_hand` from sales channels.

Business rules:
- Perfume products (suppliers MISTRAL, FLORGARDEN) are tracked via `perfumes_stock`
  and decremented on the pouring event (POST /serije). They are NOT touched here.
- All other ("proc-only") products are decremented from `proc_products.on_hand`
  on every sale, regardless of channel (Shopify orders/paid, MK POS sale, ...).
- When `on_hand` drops below `min_on_hand`, we auto-bump `pending` to cover the
  shortfall (never decreasing an existing manual pending).
- Every change writes an entry to `proc_stock_movements` for audit/debug.

Idempotency is the caller's responsibility (see `proc_applied_from_mk`,
`proc_applied_from_shopify`).

All public helpers take an external cursor `c`; the caller owns the
transaction lifecycle (commit/rollback).
"""
from __future__ import annotations

from typing import Optional, Dict, Any
from flask import current_app


# Suppliers whose stock is managed via perfumes_stock + serija pouring.
PERFUME_SUPPLIERS = ('MISTRAL', 'FLORGARDEN')


def _is_perfume_supplier(name: Optional[str]) -> bool:
    if not name:
        return False
    return str(name).strip().upper() in PERFUME_SUPPLIERS


def _resolve_product_row(c, sku: str, supplier_hint: Optional[str]) -> Optional[Dict[str, Any]]:
    """Locate the proc_products row to adjust.

    Strategy:
      1. If supplier_hint is provided, look up that supplier first (most
         specific match — required when the SKU collides across suppliers).
      2. Otherwise (or if hint did not match), fall back to a SKU-only lookup.
         If that returns multiple rows we ignore perfume suppliers and pick the
         first remaining row.
    """
    sku_norm = (sku or '').strip()
    if not sku_norm:
        return None

    if supplier_hint:
        c.execute(
            """
            SELECT pp.id, pp.supplier_id, pp.sku, pp.on_hand, pp.pending, pp.min_on_hand,
                   ps.name AS supplier_name
            FROM proc_products pp
            JOIN proc_suppliers ps ON ps.id = pp.supplier_id
            WHERE UPPER(ps.name) = %s AND UPPER(pp.sku) = %s
            LIMIT 1
            """,
            (supplier_hint.strip().upper(), sku_norm.upper()),
        )
        row = c.fetchone()
        if row:
            return dict(row) if not isinstance(row, dict) else row

    c.execute(
        """
        SELECT pp.id, pp.supplier_id, pp.sku, pp.on_hand, pp.pending, pp.min_on_hand,
               ps.name AS supplier_name
        FROM proc_products pp
        JOIN proc_suppliers ps ON ps.id = pp.supplier_id
        WHERE UPPER(pp.sku) = %s
        ORDER BY (UPPER(ps.name) IN ('MISTRAL','FLORGARDEN')) ASC, pp.id ASC
        """,
        (sku_norm.upper(),),
    )
    rows = c.fetchall() or []
    if not rows:
        return None
    first = rows[0]
    return dict(first) if not isinstance(first, dict) else first


def _record_movement(c, *, supplier_id: int, sku: str, delta: int,
                     on_hand_before: int, on_hand_after: int,
                     source: str, source_ref: Optional[str], note: Optional[str]) -> None:
    try:
        c.execute(
            """
            INSERT INTO proc_stock_movements
                (supplier_id, sku, delta, on_hand_before, on_hand_after,
                 source, source_ref, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (int(supplier_id), str(sku), int(delta), int(on_hand_before),
             int(on_hand_after), str(source), source_ref, note),
        )
    except Exception as e:
        try:
            current_app.logger.warning(f"proc_stock_movements insert failed: {e}")
        except Exception:
            pass


def apply_decrement(
    c,
    sku: str,
    qty: int,
    *,
    source: str,
    source_ref: Optional[str] = None,
    supplier_hint: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Decrement on_hand by qty for a non-perfume SKU and bump pending below min.

    Returns dict with keys:
      applied (bool), reason (str|None), supplier_id, supplier_name, sku,
      on_hand_before, on_hand_after, pending_before, pending_after.
    """
    out: Dict[str, Any] = {
        'applied': False, 'reason': None,
        'supplier_id': None, 'supplier_name': None, 'sku': sku,
        'on_hand_before': None, 'on_hand_after': None,
        'pending_before': None, 'pending_after': None,
    }
    try:
        if qty is None or int(qty) <= 0:
            out['reason'] = 'invalid_qty'
            return out

        if _is_perfume_supplier(supplier_hint):
            out['reason'] = 'perfume_supplier'
            return out

        row = _resolve_product_row(c, sku, supplier_hint)
        if not row:
            out['reason'] = 'not_found'
            return out

        supplier_name = (row.get('supplier_name') or '').strip()
        if _is_perfume_supplier(supplier_name):
            out['reason'] = 'perfume_supplier'
            out['supplier_name'] = supplier_name
            return out

        supplier_id = int(row['supplier_id'])
        sku_actual = row['sku']
        on_hand_before = int(row.get('on_hand') or 0)
        pending_before = int(row.get('pending') or 0)
        min_on_hand = int(row.get('min_on_hand') or 0)
        delta = -int(qty)
        on_hand_after = max(0, on_hand_before + delta)

        shortfall = max(0, min_on_hand - on_hand_after)
        pending_after = max(pending_before, shortfall)

        c.execute(
            """
            UPDATE proc_products
            SET on_hand = %s,
                pending = %s,
                updated_at = NOW()
            WHERE supplier_id = %s AND sku = %s
            """,
            (on_hand_after, pending_after, supplier_id, sku_actual),
        )

        _record_movement(
            c,
            supplier_id=supplier_id, sku=sku_actual, delta=delta,
            on_hand_before=on_hand_before, on_hand_after=on_hand_after,
            source=source, source_ref=source_ref, note=note,
        )

        out.update({
            'applied': True,
            'supplier_id': supplier_id,
            'supplier_name': supplier_name,
            'sku': sku_actual,
            'on_hand_before': on_hand_before,
            'on_hand_after': on_hand_after,
            'pending_before': pending_before,
            'pending_after': pending_after,
        })
        return out
    except Exception as e:
        try:
            current_app.logger.error(
                f"proc_stock.apply_decrement error sku={sku} qty={qty} src={source}: {e}"
            )
        except Exception:
            pass
        out['reason'] = 'error'
        return out


def apply_revert(
    c,
    sku: str,
    qty: int,
    *,
    source: str,
    source_ref: Optional[str] = None,
    supplier_hint: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Return qty units back to on_hand (refund / order cancelled).

    `pending` is intentionally NOT touched on revert — it is left for the
    operator to decide whether the original auto-suggested order still applies.
    """
    out: Dict[str, Any] = {
        'applied': False, 'reason': None,
        'supplier_id': None, 'supplier_name': None, 'sku': sku,
        'on_hand_before': None, 'on_hand_after': None,
    }
    try:
        if qty is None or int(qty) <= 0:
            out['reason'] = 'invalid_qty'
            return out

        if _is_perfume_supplier(supplier_hint):
            out['reason'] = 'perfume_supplier'
            return out

        row = _resolve_product_row(c, sku, supplier_hint)
        if not row:
            out['reason'] = 'not_found'
            return out

        supplier_name = (row.get('supplier_name') or '').strip()
        if _is_perfume_supplier(supplier_name):
            out['reason'] = 'perfume_supplier'
            out['supplier_name'] = supplier_name
            return out

        supplier_id = int(row['supplier_id'])
        sku_actual = row['sku']
        on_hand_before = int(row.get('on_hand') or 0)
        delta = int(qty)
        on_hand_after = on_hand_before + delta

        c.execute(
            """
            UPDATE proc_products
            SET on_hand = %s,
                updated_at = NOW()
            WHERE supplier_id = %s AND sku = %s
            """,
            (on_hand_after, supplier_id, sku_actual),
        )

        _record_movement(
            c,
            supplier_id=supplier_id, sku=sku_actual, delta=delta,
            on_hand_before=on_hand_before, on_hand_after=on_hand_after,
            source=source, source_ref=source_ref, note=note,
        )

        out.update({
            'applied': True,
            'supplier_id': supplier_id,
            'supplier_name': supplier_name,
            'sku': sku_actual,
            'on_hand_before': on_hand_before,
            'on_hand_after': on_hand_after,
        })
        return out
    except Exception as e:
        try:
            current_app.logger.error(
                f"proc_stock.apply_revert error sku={sku} qty={qty} src={source}: {e}"
            )
        except Exception:
            pass
        out['reason'] = 'error'
        return out
