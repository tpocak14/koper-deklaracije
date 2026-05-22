import pdfkit
from flask import render_template, current_app
from pathlib import Path
import base64
import re
from datetime import datetime, timedelta, date
import logging

def get_logo_base64():
    """Prebere logo in ga vrne kot base64 niz."""
    logo_path = Path(current_app.static_folder) / "logo.png"
    if not logo_path.is_file(): return None
    try:
        with open(logo_path, "rb") as image_file:
            return f"data:image/png;base64,{base64.b64encode(image_file.read()).decode('utf-8')}"
    except Exception:
        return None

def ustvari_pdf(declaration_items, line_items, country_code, order_number=None, expiration_warnings=None):
    """
    Generična funkcija za ustvarjanje PDF-ja.
    Če je order_number podan, je za spletno naročilo. Sicer je ročno.
    """
    vsebina_html = ""
    logo_path = get_logo_base64()
    lang_suffix = {'SI': 'sl', 'HU': 'hu', 'HR': 'hr', 'DE': 'de', 'AT': 'de', 'IT': 'it'}.get(country_code, 'en')

    # Blokiraj generiranje, če je rok uporabe prekratek (< 60 dni)
    if expiration_warnings:
        return None, "PDF ni bil generiran, ker imajo nekateri izdelki rok uporabe manj kot 60 dni."

    def _pick_template_name(base_name, lang):
        candidates = [
            f"template_{base_name}_{lang}.html",
            f"template_{base_name}_{lang}.txt",
        ]
        for name in candidates:
            if (Path(current_app.template_folder) / name).is_file():
                return name
        return None

    for item in declaration_items:
        try:
            original_item_title = item.get('title', 'N/A')
            producer_name = item.get('proizvajalec_ime', item.get('proizvajalec', 'unknown')).strip().lower()
            producer_slug = re.sub(r'[^a-z0-9]+', '', producer_name)
            
            current_app.logger.info(f"PDF: Obdelujem izdelek '{original_item_title}' z proizvajalcem '{producer_name}'")
            current_app.logger.info(f"PDF: Razpoložljivi ključi v item: {list(item.keys())}")
            
            template_name = _pick_template_name(producer_name, lang_suffix) or (
                _pick_template_name(producer_slug, lang_suffix) if producer_slug else None
            )

            # Če predloga za specifičen jezik ne obstaja, poskusi z angleško.
            if not template_name:
                current_app.logger.warning(f"Predloga za '{producer_name}' ({lang_suffix}) ne obstaja. Uporabljam angleško različico.")
                template_name = _pick_template_name(producer_name, 'en') or (
                    _pick_template_name(producer_slug, 'en') if producer_slug else None
                )

            podatki_za_template = {
                "title": original_item_title, 
                "sestava_inci": item['sestava_inci'], 
                "rok_uporabe": item['rok_uporabe'], 
                "serijska_stevilka": item['serijska_stevilka'], 
                "logo_path": logo_path, 
                "id_parfuma": item.get('product_no', item.get('product_id', 'N/A'))
            }
            if template_name:
                vsebina_html += render_template(template_name, **podatki_za_template)
                vsebina_html += "<div style='page-break-before: always;'></div>"
            else:
                current_app.logger.error(
                    f"Ni predloge za proizvajalca '{producer_name}'. Uporabljam generično predlogo."
                )
                generic_html = f"""
                <div style="border:1px solid #eee;padding:16px;font-family:Helvetica,Arial,sans-serif;font-size:10pt;">
                    <h2 style="margin:0 0 8px 0;">DEKLARACIJA ZA PARFUM ŠT. {podatki_za_template['id_parfuma']}</h2>
                    <p><strong>Naziv:</strong> {podatki_za_template['title']}</p>
                    <p><strong>Proizvajalec:</strong> {producer_name or 'N/A'}</p>
                    <p><strong>INCI:</strong> {podatki_za_template['sestava_inci']}</p>
                    <p><strong>Serija:</strong> {podatki_za_template['serijska_stevilka']}</p>
                    <p><strong>Rok uporabe:</strong> {podatki_za_template['rok_uporabe']}</p>
                </div>
                <div style='page-break-before: always;'></div>
                """
                vsebina_html += generic_html
        except Exception as e:
            current_app.logger.error(f"Napaka pri renderiranju predloge za izdelek '{item.get('title')}': {e}")
            continue
    
    if vsebina_html.endswith("<div style='page-break-before: always;'></div>"):
        vsebina_html = vsebina_html[:-48]

    if not vsebina_html.strip():
        error_message = f"Ni bilo mogoče generirati vsebine za PDF za naročilo {order_number or 'ročno'}. Možen vzrok: manjkajoče predloge za vse izdelke."
        current_app.logger.error(error_message)
        return None, error_message

    if order_number:
        clean_order_number = order_number.replace('#', '')
        filename = f"{clean_order_number}.pdf"
    else:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"AmourParfumsDeclaration_{timestamp}.pdf"

    pdf_file_path = Path(current_app.root_path) / "pdf" / filename
    pdf_file_path.parent.mkdir(exist_ok=True)
    
    try:
        pdf_config = pdfkit.configuration(wkhtmltopdf=current_app.config.get('WKHTMLTOPDF_PATH')) if current_app.config.get('WKHTMLTOPDF_PATH') else pdfkit.configuration()
        pdfkit.from_string(vsebina_html, str(pdf_file_path), options={'enable-local-file-access': None}, configuration=pdf_config)
        return str(pdf_file_path), "PDF uspešno ustvarjen."
    except Exception as e:
        logger = logging.getLogger(__name__)
        error_message = ""
        
        # Specifično preverjanje za najpogostejšo napako: wkhtmltopdf ni najden
        if "No wkhtmltopdf found on path" in str(e) or "command not found" in str(e).lower():
            error_message = "Kritična napaka: `wkhtmltopdf` ni najden. Preverite, ali je na strežniku nameščen ustrezen buildpack in ali je pot v `WKHTMLTOPDF_PATH` pravilno nastavljena."
        # Preverjanje za druge napake iz knjižnice, ki imajo več podrobnosti
        elif isinstance(e, OSError):
             # Poskusi dekodirati stdout/stderr za podrobnejše odpravljanje napak
             wk_stdout = e.stdout.decode('utf-8', errors='ignore') if hasattr(e, 'stdout') and e.stdout else ''
             wk_stderr = e.stderr.decode('utf-8', errors='ignore') if hasattr(e, 'stderr') and e.stderr else ''
             error_message = f"Napaka v `wkhtmltopdf`: {str(e)}. STDOUT: {wk_stdout}. STDERR: {wk_stderr}"
        else:
             # Splošna napaka za vse ostale primere
             error_message = f"Splošna napaka pri generiranju PDF-ja za {order_number or 'ročno'}: {e}"
        
        logger.error(error_message)
        return None, error_message

def generate_declaration_pdf(order_number):
    """
    Wrapper funkcija za background service.
    Generiraj PDF za določeno naročilo iz tabel `orders` in `declarations` (vrstice, ne JSON polje).
    """
    from flask import current_app
    from database import get_db

    current_app.logger.info(f"PDF SERVICE: Generiram PDF za naročilo {order_number}")

    try:
        db = get_db()
        cursor = db.cursor()

        # Pridobi naročilo (za country_code)
        cursor.execute("SELECT country_code FROM orders WHERE order_number = %s OR order_number = %s", (order_number, f"#{order_number}"))
        row = cursor.fetchone()
        if not row:
            current_app.logger.error(f"PDF SERVICE: Naročilo {order_number} ne obstaja")
            return None
        country_code = row['country_code'] if isinstance(row, dict) else row[0]

        # Pridobi vrstice deklaracij za naročilo
        cursor.execute(
            """
            SELECT product_no, proizvajalec_ime, sestava_inci, rok_uporabe, serijska_stevilka, COALESCE(quantity, 1) AS quantity
            FROM declarations
            WHERE order_number = %s OR order_number = %s
            ORDER BY created_at
            """,
            (order_number, f"#{order_number}")
        )
        rows = cursor.fetchall()
        if not rows:
            # Ni deklaracijskih vrstic: obravnavaj kot opozorilo, ne kot napako
            current_app.logger.warning(f"PDF SERVICE: Ni deklaracijskih vrstic za naročilo {order_number}")
            return None

        # Pretvori v format, ki ga pričakuje ustvari_pdf
        declaration_items = []
        for r in rows:
            rdict = dict(r) if not isinstance(r, dict) else r
            declaration_items.append({
                'title': rdict.get('product_no') or 'Artikel',
                'proizvajalec_ime': rdict.get('proizvajalec_ime'),
                'sestava_inci': rdict.get('sestava_inci'),
                'rok_uporabe': rdict.get('rok_uporabe'),
                'serijska_stevilka': rdict.get('serijska_stevilka'),
                'product_no': rdict.get('product_no'),
                'quantity': rdict.get('quantity') or 1,
            })

        # Preveri rok uporabe (blokada < 60 dni)
        expiration_warnings = []
        today = datetime.utcnow().date()
        warn_date = today + timedelta(days=60)

        def _normalize_rok(rok_value):
            if isinstance(rok_value, datetime):
                return rok_value.date()
            if isinstance(rok_value, date):
                return rok_value
            if isinstance(rok_value, str):
                s = rok_value.strip()
                if not s:
                    return None
                for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
                    try:
                        return datetime.strptime(s, fmt).date()
                    except Exception:
                        continue
                try:
                    return datetime.fromisoformat(s).date()
                except Exception:
                    return None
            return None

        for item in declaration_items:
            rok = _normalize_rok(item.get('rok_uporabe'))
            if rok and rok < warn_date:
                expiration_warnings.append(
                    f"{item.get('title','N/A')}: Rok uporabe ({rok.strftime('%d.%m.%Y')}) poteče v manj kot 60 dneh."
                )

        email_line_items = [
            {
                'title': it.get('title', 'N/A'),
                'quantity': it.get('quantity', 1),
                'price': 0.0,
                'image_url': 'https://cdn.shopify.com/s/files/1/0533/2089/files/placeholder-images-image_large.png?v=1529089297',
            }
            for it in declaration_items
        ]

        # Generiraj PDF
        pdf_path, pdf_message = ustvari_pdf(
            declaration_items,
            email_line_items,
            country_code or 'SI',
            order_number,
            expiration_warnings,
        )

        if pdf_path:
            current_app.logger.info(f"PDF SERVICE: PDF uspešno generiran: {pdf_path}")
            return pdf_path
        else:
            current_app.logger.error(f"PDF SERVICE: Napaka pri generiranju PDF: {pdf_message}")
            return None

    except Exception as e:
        current_app.logger.error(f"PDF SERVICE: Napaka pri generiranju PDF za {order_number}: {e}")
        return None
    finally:
        try:
            cursor.close()
        except Exception:
            pass


def generate_purchase_order_pdf(po: dict, items: list[dict]) -> tuple[str | None, str]:
    """
    Ustvari PDF povzetek naročila dobavitelju.
    Vrnitev: (pdf_path, message)
    """
    try:
        logo = get_logo_base64()
        title = f"Naročilo dobavitelju – {po.get('supplier','')} (PO #{po.get('id')})"
        created_at = po.get('submitted_at') or po.get('created_at') or datetime.now()
        created_at_str = created_at.strftime('%d.%m.%Y %H:%M') if hasattr(created_at, 'strftime') else str(created_at)

        # Sestavi HTML
        rows_html = "".join([
            f"""
            <tr>
                <td style='padding:8px;border:1px solid #e5e7eb;'>{it.get('product_no','')}</td>
                <td style='padding:8px;border:1px solid #e5e7eb;'>{it.get('proizvajalec','')}</td>
                <td style='padding:8px;border:1px solid #e5e7eb;'>{it.get('ime_parfuma','')}</td>
                <td style='padding:8px;border:1px solid #e5e7eb;text-align:right;'>{int(it.get('requested_qty',0))}</td>
                <td style='padding:8px;border:1px solid #e5e7eb;text-align:right;'>{int(it.get('received_qty',0))}</td>
                <td style='padding:8px;border:1px solid #e5e7eb;text-align:right;'>{int(max(0, int(it.get('requested_qty',0)) - int(it.get('received_qty',0))))}</td>
            </tr>
            """ for it in items
        ])

        html = f"""
        <html>
        <head>
            <meta charset='utf-8' />
            <title>{title}</title>
        </head>
        <body style='font-family: Arial, sans-serif; color:#111827;'>
            <div style='display:flex;align-items:center;gap:16px;'>
                {f"<img src='{logo}' alt='logo' style='height:40px'/>" if logo else ''}
                <h1 style='margin:0;font-size:20px;'>{title}</h1>
            </div>
            <div style='margin:8px 0 16px 0; color:#4b5563;'>
                <div><strong>Datum:</strong> {created_at_str}</div>
                <div><strong>Status:</strong> {po.get('status','')}</div>
            </div>
            <table style='border-collapse:collapse;width:100%;font-size:12px;'>
                <thead>
                    <tr style='background:#f9fafb;'>
                        <th style='padding:8px;border:1px solid #e5e7eb;text-align:left;'>Product No</th>
                        <th style='padding:8px;border:1px solid #e5e7eb;text-align:left;'>Proizvajalec</th>
                        <th style='padding:8px;border:1px solid #e5e7eb;text-align:left;'>Parfum</th>
                        <th style='padding:8px;border:1px solid #e5e7eb;text-align:right;'>Naročeno</th>
                        <th style='padding:8px;border:1px solid #e5e7eb;text-align:right;'>Prejeto</th>
                        <th style='padding:8px;border:1px solid #e5e7eb;text-align:right;'>Nismo prejeli</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </body>
        </html>
        """

        filename = f"PO_{po.get('id')}.pdf"
        pdf_file_path = Path(current_app.root_path) / "pdf" / filename
        pdf_file_path.parent.mkdir(exist_ok=True)
        pdf_config = pdfkit.configuration(wkhtmltopdf=current_app.config.get('WKHTMLTOPDF_PATH')) if current_app.config.get('WKHTMLTOPDF_PATH') else pdfkit.configuration()
        pdfkit.from_string(html, str(pdf_file_path), options={'enable-local-file-access': None}, configuration=pdf_config)
        return str(pdf_file_path), "PDF naročila ustvarjen."
    except Exception as e:
        logging.getLogger(__name__).error(f"Napaka pri generiranju PO PDF: {e}")
        return None, str(e)


def generiraj_pdf_za_order(order_number: str):
    """Fallback: generiraj PDF iz obstoječih podatkov deklaracije in vrni bajte.

    Uporabi 'generate_declaration_pdf' za ustvarjanje datoteke, nato preberi bajte.
    Vrne None, če PDF ni mogoče ustvariti.
    """
    try:
        pdf_path = generate_declaration_pdf(order_number)
        if not pdf_path:
            return None
        with open(pdf_path, 'rb') as f:
            return f.read()
    except Exception as e:
        logging.getLogger(__name__).error(f"Fallback PDF za {order_number} ni uspel: {e}")
        return None