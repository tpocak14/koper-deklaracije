"""One-off: test declaration Mandrill send (+ admin BCC)."""
import json
import sys

from app import app
from database import get_db
from services.declaration_safety_net import send_declaration_email
from services.pdf_service import ustvari_pdf
from services.shopify_service import clear_product_cache, get_bulk_product_details

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

        on = order["order_number"]
        c.execute("SELECT * FROM declarations WHERE order_number = %s", (on,))
        decl_rows = c.fetchall()
        if not decl_rows:
            c.execute(
                "SELECT * FROM declarations WHERE order_number = %s",
                (on.lstrip("#"),),
            )
            decl_rows = c.fetchall()
        if not decl_rows:
            print("No declarations")
            return 1

        declaration_items = []
        for item in decl_rows:
            rok = item["rok_uporabe"]
            if hasattr(rok, "strftime"):
                rok_s = rok.strftime("%d.%m.%Y")
            else:
                rok_s = str(rok) if rok else None
            declaration_items.append(
                {
                    "title": f"{item['product_no']} - {item['proizvajalec_ime']}",
                    "product_no": item["product_no"],
                    "proizvajalec_ime": item["proizvajalec_ime"],
                    "sestava_inci": item["sestava_inci"],
                    "rok_uporabe": rok_s,
                    "serijska_stevilka": item["serijska_stevilka"] or "N/A",
                }
            )

        line_items_raw = order.get("line_items", "[]")
        line_items = (
            json.loads(line_items_raw)
            if isinstance(line_items_raw, str)
            else (line_items_raw or [])
        )
        product_ids = [
            str(i["product_id"]) for i in line_items if i and i.get("product_id")
        ]
        clear_product_cache()
        shopify_details = get_bulk_product_details(product_ids)
        email_line_items = []
        for item in line_items:
            if not item or not item.get("product_id"):
                continue
            details = shopify_details.get(str(item["product_id"]), {})
            try:
                price = float(item.get("price", 0.0))
            except (ValueError, TypeError):
                price = 0.0
            email_line_items.append(
                {
                    "title": item.get("title", "N/A"),
                    "quantity": item.get("quantity", 1),
                    "price": price,
                    "image_url": details.get(
                        "image_url",
                        "https://cdn.shopify.com/s/files/1/0533/2089/files/placeholder-images-image_large.png",
                    ),
                }
            )

        pdf_path, pdf_msg = ustvari_pdf(
            declaration_items, email_line_items, order["country_code"], on, []
        )
        if not pdf_path:
            print(f"PDF failed: {pdf_msg}")
            return 1

        bcc_env = __import__("os").environ.get("ADMIN_BCC_DECLARATION_EMAIL", "")
        print(f"Sending Mandrill order={on} BCC env={bcc_env!r}")

        order_dict = dict(order) if not isinstance(order, dict) else order
        send_res = send_declaration_email(
            order_dict,
            pdf_path,
            declaration_items,
            email_line_items,
            c,
            force=True,
            allow_smtp_fallback=True,
        )
        print(send_res)
        return 0 if send_res.get("success") else 2


if __name__ == "__main__":
    raise SystemExit(main())
