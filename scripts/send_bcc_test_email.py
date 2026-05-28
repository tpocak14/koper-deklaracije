"""Dry-run: preveri safety-net pipeline (NE pošilja brez MK Zaključeno / 21:00)."""
import sys

from app import app
from database import get_db
from services.declaration_safety_net import (
    check_mk_completed_for_send,
    process_one,
    should_wait_for_2100_pdf_batch,
)

ORDER_NUMBER = sys.argv[1] if len(sys.argv) > 1 else "#SI2483"


def main() -> int:
    with app.app_context():
        db = get_db()
        c = db.cursor()
        c.execute(
            "SELECT * FROM orders WHERE order_number = %s OR order_number = %s",
            (ORDER_NUMBER, ORDER_NUMBER.lstrip("#")),
        )
        order = c.fetchone()
        if not order:
            print(f"Order not found: {ORDER_NUMBER}")
            return 1

        od = dict(order)
        wait, wait_msg = should_wait_for_2100_pdf_batch(od)
        print(f"2100_batch_wait={wait} msg={wait_msg!r}")

        mk = check_mk_completed_for_send(od, c)
        print(f"mk_completed={mk.get('ok')} reason={mk.get('reason')!r}")

        if "--run" not in sys.argv:
            print("Dry-run only. Pass --run to invoke process_one (still gated).")
            return 0

        result = process_one(od, c)
        db.commit()
        print(result)
        return 0 if result.get("action") == "uploaded_and_mandrill" else 2


if __name__ == "__main__":
    raise SystemExit(main())
