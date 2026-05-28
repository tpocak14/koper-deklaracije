import smtplib
import traceback
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
import hashlib
from flask import current_app
from database import get_db
from services.mk_service import app_log
import csv
from io import StringIO
import requests
import os

def poslji_email_s_pdf(recipient_email, order_number, shopify_order_id, pdf_path, declaration_items, status_url, shop_url, country_code, line_items, skip_test_redirect=False, allow_smtp_fallback=False):
    """Pošlje email s PDF prilogo (legacy SMTP — rezerva, ne primarna pot)."""
    try:
        # Deklaracije pošiljamo prek Mandrilla; SMTP je rezerva (allow_smtp_fallback).
        if order_number is not None and not allow_smtp_fallback:
            disabled = (os.environ.get("DISABLE_SMTP_DECLARATION_EMAIL", "1") or "1").strip().lower()
            if disabled in ("1", "true", "yes", "on"):
                current_app.logger.info(
                    f"SMTP declaration disabled for {order_number} — use Mandrill safety net"
                )
                return False

        # GLOBAL: izklop pošiljanja deklaracij za naročila
        # Izjema: ročno/ponovno pošiljanje (skip_test_redirect=True)
        if order_number is not None and not skip_test_redirect:
            try:
                cursor = get_db().cursor()
                cursor.execute("SELECT value FROM app_settings WHERE key = 'declaration_email_enabled'")
                result = cursor.fetchone()
                cursor.close()
                enabled = (result and str(result.get('value', '')).lower() == 'true')
            except Exception:
                enabled = False
            if not enabled:
                current_app.logger.info(
                    f"DECLARATION EMAIL DISABLED: preskakujem pošiljanje za naročilo {order_number}"
                )
                return True

        # Pridobi konfiguracijo
        smtp_server = current_app.config['MAIL_SERVER']
        smtp_port = current_app.config['MAIL_PORT']
        username = current_app.config['MAIL_USERNAME']
        password = current_app.config['MAIL_PASSWORD']
        
        # TEST MODE: Preusmeri vse maile na admin email
        admin_email = current_app.config.get('ADMIN_EMAIL')
        
        # Preveri nastavitev iz baze
        cursor = get_db().cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key = 'email_test_mode'")
        result = cursor.fetchone()
        
        email_mode = 'true'  # Privzeto test način
        if result:
            email_mode = result['value']
        
        current_app.logger.info(f"EMAIL MODE DEBUG: email_mode={email_mode}, admin_email={admin_email}, original_recipient={recipient_email}")
        
        original_recipient = recipient_email
        
        # Global redirect (EMAIL_REDIRECT_TO) — pred DB test mode
        redirect_to = os.environ.get("EMAIL_REDIRECT_TO", "").strip()
        if redirect_to:
            recipient_email = redirect_to
            current_app.logger.info(
                f"EMAIL_REDIRECT: Mail za naročilo {order_number} preusmerjen "
                f"z {original_recipient} na {redirect_to}"
            )
        elif email_mode == 'true' and admin_email and not skip_test_redirect:
            # TEST MODE: Samo admin
            recipient_email = admin_email
            current_app.logger.info(f"TEST MODE: Mail za naročilo {order_number} preusmerjen z {original_recipient} na {admin_email}")
        elif email_mode == 'false':
            # PRODUKCIJA MODE: Samo customer
            current_app.logger.info(f"PRODUKCIJA MODE: Mail za naročilo {order_number} se pošlje na {recipient_email}")
        elif email_mode == 'both' and admin_email and not skip_test_redirect:
            # OBA MODE: Pošlji na oba
            # Najprej pošlji na customer
            current_app.logger.info(f"OBA MODE: Mail za naročilo {order_number} se pošlje na {recipient_email} in {admin_email}")
            # Shrani original recipient za kasnejše pošiljanje na admin
            admin_recipient = admin_email
        else:
            current_app.logger.info(f"Mail za naročilo {order_number} se pošlje na {recipient_email}")
        
        cursor.close()
        
        # Ustvari sporočilo
        msg = MIMEMultipart()
        
        # Nastavi From polje z MAIL_SENDER_NAME
        sender_name = current_app.config.get('MAIL_SENDER_NAME', 'AMOUR Parfums')
        from_email = f"{sender_name} <{username}>"
        msg['From'] = from_email
        msg['To'] = recipient_email

        # Admin BCC (SMTP pot): enako kot Mandrill safety net — kupec ne vidi
        # naslova v glavah. Ne dodajamo pri redirect/test-only/both (tam admin
        # že dobi kopijo).
        bcc_admin = os.environ.get("ADMIN_BCC_DECLARATION_EMAIL", "").strip() or None
        use_admin_bcc = (
            bcc_admin
            and not redirect_to
            and email_mode not in ("both",)
            and (recipient_email or "").strip().lower() != bcc_admin.lower()
        )
        if use_admin_bcc:
            msg["Bcc"] = bcc_admin

        # Določi naslov email-a
        if order_number is None:
            msg['Subject'] = 'Varnostna deklaracija za vaš nakup'
        else:
            # Zahteva: "Varnostna deklaracija za vaše naročilo #številka"
            # Preveri, ali order_number že vsebuje #
            if order_number.startswith('#'):
                msg['Subject'] = f'Varnostna deklaracija za vaše naročilo {order_number}'
            else:
                msg['Subject'] = f'Varnostna deklaracija za vaše naročilo #{order_number}'
        
        # Izračunaj skupno ceno
        total_price = sum(float(item.get('price', 0.0)) * int(item.get('quantity', 1)) for item in line_items)
        
        # Določi jezik na podlagi države
        # Če je ročno pošiljanje (order_number je None), uporabi manual predlogo
        if order_number is None:
            if country_code == 'SI':
                template_file = 'email_template_manual_sl.html'
            else:
                template_file = 'email_template_manual_sl.html'  # Za ročno pošiljanje vedno slovenščina
        else:
            if country_code == 'SI':
                template_file = 'email_template_sl.html'
            elif country_code == 'IT':
                template_file = 'email_template_it.html'
            elif country_code == 'DE':
                template_file = 'email_template_de.html'
            elif country_code == 'HR':
                template_file = 'email_template_hr.html'
            elif country_code == 'EN':
                template_file = 'email_template_en.html'
            else:
                template_file = 'email_template_sl.html'  # Privzeti slovenščina
        
        # Preberi predlogo
        with open(f'templates/{template_file}', 'r', encoding='utf-8') as f:
            template_content = f.read()
        
        # Pripravi podatke za Jinja2 template
        from jinja2 import Template
        template = Template(template_content)
        
        # Pripravi items za loop
        items_for_template = []
        for item in line_items:
            items_for_template.append({
                'title': item.get('title', 'N/A'),
                'quantity': item.get('quantity', 1),
                'price': float(item.get('price', 0.0)),
                'image_url': item.get('image_url', 'https://via.placeholder.com/60x60?text=No+Image')
            })
        
        # Absolutni URL (trenutno ne uporabljamo v templatu; ohranimo za kompatibilnost)
        app_base_url = current_app.config.get('APP_BASE_URL', 'https://deklaracije.eu')
        if app_base_url.endswith('/'):
            app_base_url = app_base_url[:-1]
        logo_url = f"{app_base_url}/static/logo.png"

        # Render template z Jinja2
        email_content = template.render(
            order_number=order_number,
            shop_url=shop_url,
            status_url=status_url,
            total_price=f'{total_price:.2f}',
            items=items_for_template,
            store_url=shop_url,  # Dodano za kompatibilnost
            current_year=datetime.now().year,
            logo_url=logo_url
        )
        
        # Poskusi produktne slike pretvoriti v inline CID slike (ne za ročno pošiljanje)
        if order_number is not None:
            try:
                from email.utils import make_msgid
                from email.mime.image import MIMEImage
                cid_map = {}
                for idx, it in enumerate(items_for_template, start=1):
                    img_url = it.get('image_url')
                    if not img_url or not isinstance(img_url, str):
                        continue
                    if not (img_url.startswith('http://') or img_url.startswith('https://')):
                        continue
                    try:
                        resp = requests.get(img_url, timeout=5)
                        if not resp.ok or not resp.content:
                            continue
                        content_type = (resp.headers.get('Content-Type') or 'image/jpeg').lower()
                        subtype = content_type.split('/')[-1] if '/' in content_type else 'jpeg'
                        cid = make_msgid(domain='deklaracije.eu')[1:-1]
                        img_part = MIMEImage(resp.content, _subtype=subtype)
                        img_part.add_header('Content-ID', f'<{cid}>')
                        img_part.add_header('Content-Disposition', 'inline', filename=f'item_{idx}.{subtype}')
                        msg.attach(img_part)
                        cid_map[img_url] = f'cid:{cid}'
                    except Exception:
                        continue
                for original, cid_ref in cid_map.items():
                    email_content = email_content.replace(original, cid_ref)
            except Exception:
                pass
        
        # Dodaj HTML vsebino
        msg.attach(MIMEText(email_content, 'html'))
        
        # Dodaj logotip kot inline prilogo
        try:
            with open('static/logo.png', 'rb') as logo_file:
                logo_part = MIMEBase('image', 'png')
                logo_part.set_payload(logo_file.read())
            
            encoders.encode_base64(logo_part)
            logo_part.add_header('Content-ID', '<logo>')
            logo_part.add_header('Content-Disposition', 'inline', filename='logo.png')
            msg.attach(logo_part)
            current_app.logger.info(f"Logotip uspešno dodan v email za naročilo {order_number}")
        except Exception as e:
            current_app.logger.error(f"Napaka pri dodajanju logotipa: {e}")

        # Ne pripenjamo logo_white dodatno, da se ne prikazuje kot priloga v nekaterih odjemalcih
        
        # Dodaj PDF prilogo (varno: preveri obstoj)
        if not pdf_path or not os.path.isfile(pdf_path):
            current_app.logger.warning(f"Email: PDF ne obstaja na poti: {pdf_path}. Preklic pošiljanja za {order_number}")
            return False
        with open(pdf_path, 'rb') as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
        
        encoders.encode_base64(part)
        # Določi ime PDF datoteke
        if order_number is None:
            # Za ročno pošiljanje uporabi časovno oznako
            import time
            timestamp = int(time.time())
            pdf_filename = f'AmourParfumsDeclaration_{timestamp}.pdf'
        else:
            # Zahteva: AmourParfumsDeclaration_številka
            pdf_filename = f'AmourParfumsDeclaration_{order_number}.pdf'
        
        part.add_header(
            'Content-Disposition',
            f'attachment; filename= {pdf_filename}'
        )
        msg.attach(part)
        
        # Pošlji email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)
        
        current_app.logger.info(f"Email uspešno poslan na {recipient_email} za naročilo {order_number}")
        try:
            app_log('email.send_declaration', 'info', 'Declaration email sent', {
                'order_number': order_number,
                'recipient': recipient_email,
                'mode': email_mode,
                'admin_copy': bool('admin_recipient' in locals() and admin_recipient),
                'admin_bcc': bcc_admin if use_admin_bcc else None,
            })
        except Exception:
            pass
        
        # Če je "oba" način, pošlji tudi na admin
        if email_mode == 'both' and admin_email and not skip_test_redirect:
            try:
                # Ustvari novo sporočilo za admin
                admin_msg = MIMEMultipart()
                admin_msg['From'] = username
                admin_msg['To'] = admin_recipient
                # Določi naslov admin kopije
                if order_number is None:
                    admin_msg['Subject'] = '[ADMIN KOPIJA] Varnostna deklaracija za vaš nakup'
                else:
                    # Preveri, ali order_number že vsebuje #
                    if order_number.startswith('#'):
                        admin_msg['Subject'] = f'[ADMIN KOPIJA] Varnostna deklaracija za vaše naročilo {order_number}'
                    else:
                        admin_msg['Subject'] = f'[ADMIN KOPIJA] Varnostna deklaracija za vaše naročilo #{order_number}'
                
                # Dodaj HTML vsebino z dodatnim opozorilom
                admin_email_content = f"""
                <div style="background-color: #fff3cd; border: 1px solid #ffeaa7; padding: 10px; margin-bottom: 20px; border-radius: 5px;">
                    <strong>OPOZORILO:</strong> To je kopija maila, ki je bil poslan na {original_recipient}
                </div>
                {email_content}
                """
                admin_msg.attach(MIMEText(admin_email_content, 'html'))
                
                # Dodaj logotip kot inline prilogo za admin kopijo
                try:
                    with open('static/logo.png', 'rb') as logo_file:
                        logo_part = MIMEBase('image', 'png')
                        logo_part.set_payload(logo_file.read())
                    
                    encoders.encode_base64(logo_part)
                    logo_part.add_header('Content-ID', '<logo>')
                    logo_part.add_header('Content-Disposition', 'inline', filename='logo.png')
                    admin_msg.attach(logo_part)
                except Exception as e:
                    current_app.logger.error(f"Napaka pri dodajanju logotipa v admin kopijo: {e}")
                
                # Dodaj PDF prilogo (varno: preveri obstoj)
                if not pdf_path or not os.path.isfile(pdf_path):
                    current_app.logger.warning(f"Email(admin kopija): PDF ne obstaja na poti: {pdf_path}. Preskakujem admin kopijo za {order_number}")
                    return True
                with open(pdf_path, 'rb') as attachment:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment.read())
                
                encoders.encode_base64(part)
                # Določi ime PDF datoteke za admin kopijo
                if order_number is None:
                    # Za ročno pošiljanje uporabi časovno oznako
                    import time
                    timestamp = int(time.time())
                    admin_pdf_filename = f'AmourParfumsDeclaration_{timestamp}_admin_kopija.pdf'
                else:
                    admin_pdf_filename = f'AmourParfumsDeclaration_{order_number}_admin_kopija.pdf'
                
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename= {admin_pdf_filename}'
                )
                admin_msg.attach(part)
                
                # Pošlji admin kopijo
                server.send_message(admin_msg)
                current_app.logger.info(f"Admin kopija emaila uspešno poslana na {admin_recipient} za naročilo {order_number}")
                
            except Exception as e:
                current_app.logger.error(f"Napaka pri pošiljanju admin kopije: {e}")
                # Ne prekinemo, ker je glavni email že poslan
                try:
                    app_log('email.send_declaration', 'warning', 'Admin copy failed', {
                        'order_number': order_number,
                        'recipient': admin_recipient,
                        'error': str(e)
                    })
                except Exception:
                    pass
        
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        current_app.logger.error(f"SMTP napaka: {e}")
        current_app.logger.error(f"SMTP napaka tip: {type(e)}")
        raise e
    except smtplib.SMTPServerDisconnected as e:
        current_app.logger.error(f"SMTP napaka: Connection unexpectedly closed")
        current_app.logger.error(f"SMTP napaka tip: {type(e)}")
        raise e
    except Exception as e:
        current_app.logger.error(f"KRITIČNA NAPAKA v poslji_email_s_pdf: {e}")
        try:
            app_log('email.send_declaration', 'error', 'Declaration email error', {
                'order_number': order_number,
                'recipient': recipient_email,
                'error': str(e)
            })
        except Exception:
            pass
        current_app.logger.error(f"Stack trace: {traceback.format_exc()}")
        raise e


def send_invoice_email(recipient_email: str, order_number: str, pdf_path: str, *, country_code: str | None = None, status_url: str | None = None, store_url: str | None = None, items: list | None = None, skip_test_redirect: bool = False) -> bool:
    """Pošlji račun (MetaKocka) kot PDF na stranko; upošteva test/both način in CC admin.

    Vsebina: modern HTML (tailwind-like inline styles), logotip inline, jasen CTA in povzetek.
    """
    try:
        smtp_server = current_app.config['MAIL_SERVER']
        smtp_port = current_app.config['MAIL_PORT']
        username = current_app.config['MAIL_USERNAME']
        password = current_app.config['MAIL_PASSWORD']

        admin_email = current_app.config.get('ADMIN_EMAIL')

        cursor = get_db().cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key = 'email_test_mode'")
        result = cursor.fetchone()
        email_mode = 'true'
        if result:
            try:
                email_mode = result['value']
            except Exception:
                pass
        cursor.close()

        original_recipient = recipient_email
        admin_recipient = None
        if email_mode == 'true' and admin_email and not skip_test_redirect:
            recipient_email = admin_email
        elif email_mode == 'both' and admin_email and not skip_test_redirect:
            admin_recipient = admin_email

        msg = MIMEMultipart('related')
        sender_name = current_app.config.get('MAIL_SENDER_NAME', 'AMOUR Parfums')
        msg['From'] = f"{sender_name} <{username}>"
        msg['To'] = recipient_email
        subj_number = order_number if str(order_number).startswith('#') else f"#{order_number}"
        # Jezikovna mapa (osnovni nizi)
        lang_map = {
            'sl': {
                'subject': f"Račun za vaše naročilo {subj_number}",
                'title': 'Hvala za nakup!',
                'body': f"V priponki najdete uradni račun za vaše naročilo <strong>{subj_number}</strong>. Dokument je izdan preko MetaKocka.",
                'cta': 'Obiščite našo trgovino',
                'help': 'Če imate kakršnakoli vprašanja, nam prosim odgovorite na ta email. Z veseljem pomagamo.',
                'footer': f"© {datetime.now().year} Deklaracije · AMOUR Parfums",
                'admin_copy': f"[ADMIN KOPIJA] Račun za naročilo {subj_number} (poslano na {recipient_email})",
            },
            'en': {
                'subject': f"Invoice for your order {subj_number}",
                'title': 'Thank you for your purchase!',
                'body': f"Please find attached the official invoice for your order <strong>{subj_number}</strong>. The document was issued via MetaKocka.",
                'cta': 'Visit our store',
                'help': 'If you have any questions, please reply to this email. We are happy to help.',
                'footer': f"© {datetime.now().year} Declarations · AMOUR Parfums",
                'admin_copy': f"[ADMIN COPY] Invoice for order {subj_number} (sent to {recipient_email})",
            },
            'de': {
                'subject': f"Rechnung für Ihre Bestellung {subj_number}",
                'title': 'Vielen Dank für Ihren Einkauf!',
                'body': f"Im Anhang finden Sie die offizielle Rechnung für Ihre Bestellung <strong>{subj_number}</strong>. Das Dokument wurde über MetaKocka ausgestellt.",
                'cta': 'Besuchen Sie unseren Shop',
                'help': 'Bei Fragen antworten Sie bitte auf diese E-Mail. Wir helfen gerne weiter.',
                'footer': f"© {datetime.now().year} Deklaracije · AMOUR Parfums",
                'admin_copy': f"[ADMIN KOPIE] Rechnung für Bestellung {subj_number} (gesendet an {recipient_email})",
            },
            'it': {
                'subject': f"Fattura per il tuo ordine {subj_number}",
                'title': 'Grazie per il tuo acquisto!',
                'body': f"In allegato trovi la fattura ufficiale per il tuo ordine <strong>{subj_number}</strong>. Il documento è stato emesso tramite MetaKocka.",
                'cta': 'Visita il nostro negozio',
                'help': 'Se hai domande, rispondi a questa email. Siamo felici di aiutarti.',
                'footer': f"© {datetime.now().year} Dichiarazioni · AMOUR Parfums",
                'admin_copy': f"[COPIA ADMIN] Fattura per l’ordine {subj_number} (inviata a {recipient_email})",
            },
            'hr': {
                'subject': f"Račun za vašu narudžbu {subj_number}",
                'title': 'Hvala na kupnji!',
                'body': f"U prilogu se nalazi službeni račun za vašu narudžbu <strong>{subj_number}</strong>. Dokument je izdan putem MetaKocke.",
                'cta': 'Posjetite našu trgovinu',
                'help': 'Ako imate bilo kakvih pitanja, odgovorite na ovaj email. Rado ćemo pomoći.',
                'footer': f"© {datetime.now().year} Deklaracije · AMOUR Parfums",
                'admin_copy': f"[ADMIN KOPIJA] Račun za narudžbu {subj_number} (poslano na {recipient_email})",
            },
        }
        # Preslikava države v jezik (razširimo po potrebi)
        cc_to_lang = {
            'SI': 'sl', 'HR': 'hr', 'DE': 'de', 'AT': 'de', 'IT': 'it', 'GB': 'en', 'US': 'en', 'EN': 'en',
        }
        lang = lang_map.get(cc_to_lang.get((country_code or 'SI').upper(), 'sl'), lang_map['sl'])
        msg['Subject'] = lang['subject']
        # Pripravi podatke za template
        # Določimo pravilno trgovinsko domeno po državi
        def _store_url_for_cc(cc: str | None) -> str:
            cc_u = (cc or '').upper()
            domain_map = {
                'SI': 'https://amour.si',
                'HR': 'https://amourparfums.hr',
                'HU': 'https://amour.hu',
                'AT': 'https://amourparfums.at',
                'DE': 'https://amourparfums.de',
            }
            return domain_map.get(cc_u, 'https://amourparfums.com')

        # Vedno uporabimo domeno glede na country_code (zahteva)
        store_url = _store_url_for_cc(country_code)
        if store_url.endswith('/'):
            store_url = store_url[:-1]
        logo_path = 'static/logo.png'
        logo_cid = 'logo'

        # Uporabi enak HTML slog kot deklaracije – ločen Jinja template per jezik
        from jinja2 import Template
        def _read_template(lang_code: str) -> str:
            fname = f"templates/invoice_template_{lang_code}.html"
            try:
                with open(fname, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception:
                # Fallback na EN, nato SL
                try:
                    with open('templates/invoice_template_en.html', 'r', encoding='utf-8') as f:
                        return f.read()
                except Exception:
                    with open('templates/invoice_template_sl.html', 'r', encoding='utf-8') as f:
                        return f.read()

        # Pripravi items za prikaz (naslovi, količine, cene, slike)
        items_for_template = []
        try:
            for it in (items or []):
                try:
                    price_val = float(it.get('price', 0.0))
                except Exception:
                    price_val = 0.0
                items_for_template.append({
                    'title': it.get('title', 'N/A'),
                    'quantity': it.get('quantity', 1),
                    'price': price_val,
                    'image_url': it.get('image_url') or it.get('image', '')
                })
        except Exception:
            items_for_template = []

        # Preslikava jezika – HU trenutno uporablja EN predlogo
        lang_code = cc_to_lang.get((country_code or 'SI').upper(), 'sl')
        tmpl_string = _read_template(lang_code)
        template = Template(tmpl_string)
        html = template.render(
            order_number=subj_number,
            status_url=status_url or store_url,
            store_url=store_url,
            current_year=datetime.now().year,
            items=items_for_template,
        )
        # Vdelaj produktne slike kot CID (kot pri deklaracijah)
        try:
            from email.utils import make_msgid
            from email.mime.image import MIMEImage
            cid_map = {}
            for idx, it in enumerate(items_for_template, start=1):
                img_url = it.get('image_url')
                if not img_url or not isinstance(img_url, str):
                    continue
                if not (img_url.startswith('http://') or img_url.startswith('https://')):
                    continue
                try:
                    resp = requests.get(img_url, timeout=5)
                    if not resp.ok or not resp.content:
                        continue
                    content_type = (resp.headers.get('Content-Type') or 'image/jpeg').lower()
                    subtype = content_type.split('/')[-1] if '/' in content_type else 'jpeg'
                    cid = make_msgid(domain='deklaracije.eu')[1:-1]
                    img_part = MIMEImage(resp.content, _subtype=subtype)
                    img_part.add_header('Content-ID', f'<{cid}>')
                    img_part.add_header('Content-Disposition', 'inline', filename=f'item_{idx}.{subtype}')
                    msg.attach(img_part)
                    cid_map[img_url] = f'cid:{cid}'
                except Exception:
                    continue
            for original, cid_ref in cid_map.items():
                html = html.replace(original, cid_ref)
        except Exception:
            pass
        msg.attach(MIMEText(html, 'html'))

        # Pripni logotip kot inline CID (enako kot pri deklaracijah)
        try:
            from email.mime.image import MIMEImage
            with open(logo_path, 'rb') as lf:
                logo_part = MIMEImage(lf.read(), _subtype='png')
            logo_part.add_header('Content-ID', f'<{logo_cid}>')
            logo_part.add_header('Content-Disposition', 'inline', filename='logo.png')
            msg.attach(logo_part)
        except Exception as _:
            pass

        if not pdf_path or not os.path.isfile(pdf_path):
            current_app.logger.warning(f"Invoice email: PDF ne obstaja na poti: {pdf_path}. Preklic pošiljanja za {order_number}")
            return False
        with open(pdf_path, 'rb') as f:
            part = MIMEBase('application', 'pdf')
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f"attachment; filename=Racun_{subj_number.replace('#','')}.pdf")
        msg.attach(part)

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)

            if admin_recipient:
                admin_msg = MIMEMultipart('related')
                admin_msg['From'] = f"{sender_name} <{username}>"
                admin_msg['To'] = admin_recipient
                admin_msg['Subject'] = lang['admin_copy']
                admin_msg.attach(MIMEText(html, 'html'))
                try:
                    from email.mime.image import MIMEImage
                    with open(logo_path, 'rb') as lf2:
                        logo_part2 = MIMEImage(lf2.read(), _subtype='png')
                    logo_part2.add_header('Content-ID', f'<{logo_cid}>')
                    logo_part2.add_header('Content-Disposition', 'inline', filename='logo.png')
                    admin_msg.attach(logo_part2)
                except Exception as _:
                    pass
                if not pdf_path or not os.path.isfile(pdf_path):
                    return True
                with open(pdf_path, 'rb') as f2:
                    apart = MIMEBase('application', 'pdf')
                    apart.set_payload(f2.read())
                encoders.encode_base64(apart)
                apart.add_header('Content-Disposition', f"attachment; filename=Racun_{subj_number.replace('#','')}.pdf")
                admin_msg.attach(apart)
                server.send_message(admin_msg)

        return True
    except Exception as e:
        current_app.logger.error(f"NAPAKA pri pošiljanju računa: {e}")
        return False

def send_purchase_order_admin_email(po: dict, items: list[dict], pdf_bytes: bytes, xlsx_bytes: bytes | None) -> bool:
    """Pošlje email administratorju z PDF in Excel (XLSX) prilogama za naročilo dobavitelju."""
    smtp_server = current_app.config['MAIL_SERVER']
    smtp_port = current_app.config['MAIL_PORT']
    username = current_app.config['MAIL_USERNAME']
    password = current_app.config['MAIL_PASSWORD']
    admin_email = current_app.config.get('ADMIN_EMAIL')
    if not admin_email:
        current_app.logger.error('ADMIN_EMAIL ni nastavljen; ne morem poslati PO maila.')
        return False

    msg = MIMEMultipart()
    msg['From'] = username
    msg['To'] = admin_email
    msg['Subject'] = f"Naročilo dobavitelju (PO #{po.get('id')}) – {po.get('supplier','')}"

    # HTML telo
    created_at = po.get('submitted_at') or po.get('created_at') or datetime.now()
    created_at_str = created_at.strftime('%d.%m.%Y %H:%M') if hasattr(created_at, 'strftime') else str(created_at)
    rows = ''.join([f"<tr><td style='padding:6px;border:1px solid #e5e7eb'>{it.get('product_no')}</td><td style='padding:6px;border:1px solid #e5e7eb'>{it.get('ime_parfuma')}</td><td style='padding:6px;border:1px solid #e5e7eb;text-align:right'>{int(it.get('requested_qty',0))}</td></tr>" for it in items])
    html_body = f"""
        <div style='font-family:Arial,sans-serif'>
            <h2 style='margin:0 0 8px 0'>Naročilo dobavitelju</h2>
            <div>PO ID: <strong>{po.get('id')}</strong></div>
            <div>Dobavitelj: <strong>{po.get('supplier')}</strong></div>
            <div>Datum: {created_at_str}</div>
            <hr style='margin:12px 0;border:none;border-top:1px solid #e5e7eb' />
            <table style='border-collapse:collapse;font-size:13px'>
              <thead><tr style='background:#f9fafb'><th style='padding:6px;border:1px solid #e5e7eb;text-align:left'>Product No</th><th style='padding:6px;border:1px solid #e5e7eb;text-align:left'>Parfum</th><th style='padding:6px;border:1px solid #e5e7eb;text-align:right'>QTY</th></tr></thead>
              <tbody>{rows}</tbody>
            </table>
        </div>
    """
    msg.attach(MIMEText(html_body, 'html'))

    # Pripni PDF (bytes)
    part = MIMEBase('application', 'pdf')
    part.set_payload(pdf_bytes)
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', f"attachment; filename=PO_{po.get('id')}.pdf")
    msg.attach(part)

    # Pripni XLSX
    if xlsx_bytes:
        x_part = MIMEBase('application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        x_part.set_payload(xlsx_bytes)
        encoders.encode_base64(x_part)
        x_part.add_header('Content-Disposition', f"attachment; filename=PO_{po.get('id')}.xlsx")
        msg.attach(x_part)

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(msg)
    return True

def poslji_obvestilo_o_napaki(sporocilo, podrobnosti=""):
    """Pošlje email obvestilo o napaki."""
    try:
        recipient = current_app.config.get('ADMIN_EMAIL')
        if not recipient:
            current_app.logger.error("ADMIN_EMAIL ni nastavljen. Obvestilo o napaki ne bo poslano.")
            return

        msg = MIMEMultipart()
        msg['From'] = current_app.config['MAIL_USERNAME']
        msg['To'] = recipient
        msg['Subject'] = f"🚨 NAPAKA V APLIKACIJI DEKLARACIJE"
        
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background-color: #dc3545; color: white; padding: 20px; text-align: center;">
                <h2>🚨 KRITIČNA NAPAKA</h2>
            </div>
            
            <div style="padding: 20px; background-color: #f8f9fa;">
                <h3>Opis napake:</h3>
                <p style="background-color: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px;">
                    {sporocilo}
                </p>
                
                {f'<h3>Podrobnosti:</h3><p style="background-color: #e9ecef; padding: 15px; border-radius: 5px;">{podrobnosti}</p>' if podrobnosti else ''}
                
                <div style="background-color: #d1ecf1; border: 1px solid #bee5eb; padding: 15px; margin: 20px 0; border-radius: 5px;">
                    <h4>📋 Potrebne akcije:</h4>
                    <ol>
                        <li>Prijavite se v aplikacijo Deklaracije</li>
                        <li>Preverite log datoteke</li>
                        <li>Odpravite napako</li>
                        <li>Preverite, ali aplikacija deluje pravilno</li>
                    </ol>
                </div>
            </div>
            
            <div style="background-color: #e9ecef; padding: 15px; text-align: center; font-size: 12px; color: #6c757d;">
                <p>To obvestilo je bilo poslano avtomatsko iz aplikacije Deklaracije.</p>
                <p>Čas: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</p>
            </div>
        </div>
        """
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(current_app.config['MAIL_SERVER'], current_app.config['MAIL_PORT']) as server:
            server.starttls()
            server.login(current_app.config['MAIL_USERNAME'], current_app.config['MAIL_PASSWORD'])
            server.send_message(msg)
        
        current_app.logger.info(f"Obvestilo o napaki uspešno poslano na {recipient}.")
    except Exception as e:
        current_app.logger.error(f"NAPAKA PRI POŠILJANJU OBVESTILA O NAPAKI: {e}")

def send_new_user_welcome_email(username: str, recipient_email: str, password: str, login_url: str = None) -> bool:
    """Pošlje dobrodošlico novemu uporabniku z dostopnimi podatki.

    Uporabi blagovno znamko aplikacije (barva #00AEB3) in estetsko HTML postavitev.
    Za to vrsto sporočila ignorira test preusmeritev (pošlje na dejanski email uporabnika).
    """
    try:
        smtp_server = current_app.config['MAIL_SERVER']
        smtp_port = current_app.config['MAIL_PORT']
        username_mail = current_app.config['MAIL_USERNAME']
        password_mail = current_app.config['MAIL_PASSWORD']
        sender_name = current_app.config.get('MAIL_SENDER_NAME', 'AMOUR Parfums')
        brand_color = '#00AEB3'

        # Določi login URL
        if not login_url:
            login_url = current_app.config.get('APP_BASE_URL', 'https://deklaracije.eu/')

        html = f"""
        <div style="font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; background:#f6f9fb; padding:24px;">
          <table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" role=\"presentation\">
            <tr>
              <td align=\"center\">
                <table width=\"600\" cellpadding=\"0\" cellspacing=\"0\" role=\"presentation\" style=\"max-width:600px;background:#ffffff;border-radius:16px;box-shadow:0 2px 12px rgba(0,0,0,0.06);overflow:hidden;\">
                  <tr>
                    <td style=\"background:{brand_color};padding:20px 24px;color:#ffffff;\">
                      <h1 style=\"margin:0;font-size:20px;line-height:1.4;font-weight:700;\">Dobrodošli v aplikaciji Deklaracije</h1>
                      <p style=\"margin:4px 0 0 0;font-size:14px;opacity:.95;\">Vaš račun je pripravljen</p>
                    </td>
                  </tr>
                  <tr>
                    <td style=\"padding:24px;\">
                      <p style=\"margin:0 0 12px 0;color:#0f172a;font-size:16px;\">Pozdravljeni,</p>
                      <p style=\"margin:0 0 16px 0;color:#334155;font-size:14px;line-height:1.6;\">Vaš uporabniški račun za aplikacijo Deklaracije je bil uspešno ustvarjen. Spodaj so vaši podatki za prvi dostop. Ob prvi prijavi priporočamo, da geslo spremenite.</p>

                      <div style=\"border:1px solid #e5e7eb;border-radius:12px;padding:16px;margin:8px 0 16px 0;background:#f9fafb;\">
                        <table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" width=\"100%\">
                          <tr>
                            <td style=\"padding:6px 0;color:#475569;font-size:14px;\">Uporabniško ime</td>
                            <td style=\"padding:6px 0;color:#0f172a;font-weight:600;font-size:14px;\" align=\"right\">{username}</td>
                          </tr>
                          <tr>
                            <td style=\"padding:6px 0;color:#475569;font-size:14px;\">Začasno geslo</td>
                            <td style=\"padding:6px 0;color:#0f172a;font-weight:600;font-size:14px;\" align=\"right\">{password}</td>
                          </tr>
                        </table>
                      </div>

                      <div style=\"text-align:center;margin:20px 0;\">
                        <a href=\"{login_url}\" style=\"display:inline-block;background:{brand_color};color:#ffffff;text-decoration:none;padding:12px 18px;border-radius:10px;font-weight:600;font-size:14px;\">Odpri aplikacijo Deklaracije</a>
                      </div>

                      <p style=\"margin:16px 0 0 0;color:#64748b;font-size:12px;\">Če niste pričakovali tega sporočila, ga lahko varno ignorirate.</p>
                    </td>
                  </tr>
                  <tr>
                    <td style=\"padding:16px 24px;border-top:1px solid #f1f5f9;color:#94a3b8;font-size:12px;text-align:center;\">
                      © {datetime.now().year} Deklaracije · AMOUR Parfums
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </div>
        """

        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Vaš dostop do aplikacije Deklaracije'
        msg['From'] = f"{sender_name} <{username_mail}>"
        msg['To'] = recipient_email
        msg.attach(MIMEText(html, 'html'))

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(username_mail, password_mail)
            server.send_message(msg)

        current_app.logger.info(f"Welcome email poslan na {recipient_email} (uporabnik: {username})")
        return True
    except Exception as e:
        current_app.logger.error(f"NAPAKA pri pošiljanju welcome emaila: {e}")
        current_app.logger.error(f"Stack: {traceback.format_exc()}")
        return False

def preveri_ali_je_opozorilo_poslano(order_number, notification_type, missing_data_details):
    """Preveri, ali je opozorilo že bilo poslano v zadnjih 24 urah za isto naročilo in podatke."""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Ustvari hash iz manjkajočih podatkov
        missing_data_str = '|'.join(sorted(missing_data_details)) if isinstance(missing_data_details, list) else str(missing_data_details)
        missing_data_hash = hashlib.md5(missing_data_str.encode()).hexdigest()
        
        # Preveri, ali je opozorilo že bilo poslano v zadnjih 24 urah
        cursor.execute("""
            SELECT id FROM notification_log 
            WHERE order_number = %s 
            AND notification_type = %s 
            AND missing_data_hash = %s 
            AND sent_at > NOW() - INTERVAL '24 hours'
        """, (order_number, notification_type, missing_data_hash))
        
        result = cursor.fetchone()
        cursor.close()
        
        return result is not None
        
    except Exception as e:
        current_app.logger.error(f"Napaka pri preverjanju opozoril: {e}")
        return False

def zabelezi_poslano_opozorilo(order_number, notification_type, missing_data_details):
    """Zabeleži, da je bilo opozorilo poslano."""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Ustvari hash iz manjkajočih podatkov
        missing_data_str = '|'.join(sorted(missing_data_details)) if isinstance(missing_data_details, list) else str(missing_data_details)
        missing_data_hash = hashlib.md5(missing_data_str.encode()).hexdigest()
        
        # Vstavi zapis o poslanem opozorilu
        cursor.execute("""
            INSERT INTO notification_log (order_number, notification_type, missing_data_hash)
            VALUES (%s, %s, %s)
        """, (order_number, notification_type, missing_data_hash))
        
        db.commit()
        cursor.close()
        
    except Exception as e:
        current_app.logger.error(f"Napaka pri beleženju opozorila: {e}")

def poslji_obvestilo_o_narocilu_z_manjkajocimi_podatki(order_number, missing_data_details, customer_email=None, shopify_order_id=None):
    """Pošlje email obvestilo o naročilu z manjkajočimi podatki (omejeno na enkrat na dan)."""
    try:
        # Najprej preveri, ali je opozorilo že bilo poslano danes za to naročilo (hitrejša preveritev)
        try:
            db = get_db()
            cursor = db.cursor()
            cursor.execute("""
                SELECT COUNT(*) as count FROM notification_log 
                WHERE order_number = %s 
                AND notification_type = 'missing_data'
                AND DATE(sent_at) = CURRENT_DATE
            """, (order_number,))
            result = cursor.fetchone()
            cursor.close()
            
            if result and result['count'] > 0:
                current_app.logger.info(f"Opozorilo za naročilo {order_number} je že bilo poslano danes. Preskačem.")
                return True
        except Exception as e:
            current_app.logger.warning(f"Napaka pri dodatnem preverjanju opozoril: {e}")
            # Če ne moremo preveriti, nadaljujemo z normalnim procesom
        
        # Preveri, ali je opozorilo že bilo poslano v zadnjih 24 urah (podrobnejša preveritev)
        if preveri_ali_je_opozorilo_poslano(order_number, 'missing_data', missing_data_details):
            current_app.logger.info(f"Opozorilo za naročilo {order_number} je že bilo poslano v zadnjih 24 urah. Preskačem.")
            return True
        
        # Dodatna zaščita - preveri, ali je opozorilo že bilo poslano v zadnjih 2 urah za to naročilo
        try:
            db = get_db()
            cursor = db.cursor()
            cursor.execute("""
                SELECT COUNT(*) as count FROM notification_log 
                WHERE order_number = %s 
                AND notification_type = 'missing_data'
                AND sent_at > NOW() - INTERVAL '2 hours'
            """, (order_number,))
            result = cursor.fetchone()
            cursor.close()
            
            if result and result['count'] > 0:
                current_app.logger.info(f"Opozorilo za naročilo {order_number} je že bilo poslano v zadnjih 2 urah. Preskačem.")
                return True
        except Exception as e:
            current_app.logger.warning(f"Napaka pri preverjanju opozoril v zadnjih 2 urah: {e}")
        
        recipient = current_app.config.get('ADMIN_EMAIL')
        if not recipient:
            current_app.logger.error("ADMIN_EMAIL ni nastavljen. Obvestilo o naročilu ne bo poslano.")
            return False

        msg = MIMEMultipart()
        msg['From'] = current_app.config['MAIL_USERNAME']
        msg['To'] = recipient
        msg['Subject'] = f"🚨 NAROČILO {order_number} - MANJKAJO PODATKI ZA DEKLARACIJO"
        
        # Pretvori missing_data_details v seznam, če je string
        if isinstance(missing_data_details, str):
            try:
                import json
                missing_list = json.loads(missing_data_details)
            except:
                missing_list = [missing_data_details]
        else:
            missing_list = missing_data_details
        
        missing_html = ""
        for i, detail in enumerate(missing_list, 1):
            missing_html += f"<li>{detail}</li>"
        
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background-color: #dc3545; color: white; padding: 20px; text-align: center;">
                <h2>🚨 URGENT: NAROČILO Z MANJKAJOČIMI PODATKI</h2>
            </div>
            
            <div style="padding: 20px; background-color: #f8f9fa;">
                <h3>Podrobnosti naročila:</h3>
                <ul>
                    <li><strong>Številka naročila:</strong> {order_number}</li>
                    <li><strong>Shopify Order ID:</strong> {shopify_order_id or 'N/A'}</li>
                    <li><strong>Email stranke:</strong> {customer_email or 'N/A'}</li>
                    <li><strong>Čas obvestila:</strong> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</li>
                </ul>
                
                <h3>Manjkajoči podatki:</h3>
                <ul style="color: #dc3545; font-weight: bold;">
                    {missing_html}
                </ul>
                
                <div style="background-color: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; margin: 20px 0; border-radius: 5px;">
                    <h4>🔧 Potrebne akcije:</h4>
                    <ol>
                        <li>Prijavite se v aplikacijo Deklaracije</li>
                        <li>Poiščite naročilo {order_number} v seznamu naročil</li>
                        <li>Dodajte manjkajoče podatke (INCI, serije, roke uporabe)</li>
                        <li>Poskusite ponovno poslati deklaracijo</li>
                        <li>Stranka bo prejela deklaracijo takoj, ko bodo podatki popolni</li>
                    </ol>
                </div>
                
                <div style="background-color: #d1ecf1; border: 1px solid #bee5eb; padding: 15px; margin: 20px 0; border-radius: 5px;">
                    <h4>📋 Pogoji za pošiljanje deklaracije:</h4>
                    <ul>
                        <li>✅ Parfum mora imeti INCI sestavo</li>
                        <li>✅ Parfum mora biti označen kot "na zalogi" (GREEN tag)</li>
                        <li>✅ Parfum mora imeti serijo z veljavnim rokom uporabe</li>
                        <li>✅ Rok uporabe ne sme biti pretečen</li>
                    </ul>
                </div>
                
                <div style="background-color: #e2e3e5; border: 1px solid #d6d8db; padding: 15px; margin: 20px 0; border-radius: 5px;">
                    <h4>ℹ️ Informacija:</h4>
                    <p>To opozorilo se pošlje samo enkrat na dan za isto napako. Dodatna opozorila bodo poslana šele naslednji dan, če se napaka ne bo odpravila.</p>
                </div>
            </div>
            
            <div style="background-color: #e9ecef; padding: 15px; text-align: center; font-size: 12px; color: #6c757d;">
                <p>To obvestilo je bilo poslano avtomatsko iz aplikacije Deklaracije.</p>
                <p>Čas: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</p>
            </div>
        </div>
        """
        
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(current_app.config['MAIL_SERVER'], current_app.config['MAIL_PORT']) as server:
            server.starttls()
            server.login(current_app.config['MAIL_USERNAME'], current_app.config['MAIL_PASSWORD'])
            server.send_message(msg)
        
        # Zabeleži poslano opozorilo
        zabelezi_poslano_opozorilo(order_number, 'missing_data', missing_data_details)
        
        current_app.logger.info(f"Obvestilo o naročilu {order_number} z manjkajočimi podatki uspešno poslano na {recipient}.")
        return True
    except Exception as e:
        current_app.logger.error(f"NAPAKA PRI POŠILJANJU OBVESTILA O NAROČILU: {e}")
        return False


def poslji_mk_deklaracije_report(
    order_numbers,
    *,
    window_days: int,
    sent_at=None,
    stats=None,
    failed_orders=None,
    no_pdf_orders=None,
    prior_uploaded_orders=None,
):
    """Pošlje adminu povzetek dnevnega batcha MK deklaracij.

    Razdeljeno na 4 sekcije:
      - ✅ Naloženo zdaj (uspeli MK upload-i v tem batchu)
      - ❌ Neuspeli MK upload (z razlogom, kjer je možno)
      - ⚠️ Fulfilled brez PDF (manjkajoči podatki / preveč star rok)
      - ℹ️ Že naloženo prej (hourly reconcile, isti delovni dan)
    """
    import html as html_lib
    try:
        recipient = current_app.config.get('ADMIN_EMAIL')
        if not recipient:
            current_app.logger.error("ADMIN_EMAIL ni nastavljen. MK report ne bo poslan.")
            return False

        smtp_server = current_app.config.get('MAIL_SERVER')
        smtp_port = current_app.config.get('MAIL_PORT', 587)
        username = current_app.config.get('MAIL_USERNAME')
        password = current_app.config.get('MAIL_PASSWORD')
        if not smtp_server or not username or not password:
            current_app.logger.error("MAIL_SERVER/MAIL_USERNAME/MAIL_PASSWORD ni nastavljen. MK report ne bo poslan.")
            return False

        if sent_at is None:
            sent_at = datetime.now()

        # Admin UI base URL (deep-link za vsak order_number)
        admin_base = (
            current_app.config.get('ADMIN_NEXT_BASE_URL')
            or os.environ.get('ADMIN_NEXT_BASE_URL')
            or 'https://koper-deklaracije-v2.vercel.app'
        ).rstrip('/')

        def _esc(v) -> str:
            return html_lib.escape(str(v) if v is not None else '', quote=True)

        def _norm(o) -> str:
            return str(o).lstrip('#').strip() if o is not None else ''

        def _sort_key(s: str):
            return int(s) if s.isdigit() else 10**18

        def _order_link(num: str) -> str:
            # Naš Next.js detail page uporablja path /narocila/<order_number>
            n = _norm(num)
            return f"{admin_base}/narocila/{_esc(n)}"

        def _human_reason(reason: str) -> str:
            r = (reason or '').strip()
            mapping = {
                'bill_not_found':           'Račun (sales_bill/sales_order) v MK ni najden — preveri MK ali shrani mk_bill_id.',
                'pdf_missing':              'PDF se ni generiral (najverjetneje manjkajo INCI/serija/rok).',
                'mk_add_attachment_failed': 'MK API je zavrnil prilogo (duplikat, dokument zaklenjen ali interna napaka MK).',
                'unknown_error':            'Neznana napaka (preveri logs).',
            }
            if r in mapping:
                return mapping[r]
            if r.startswith('pdf_error:'):
                return f"Napaka pri generiranju PDF: {r.split(':', 1)[1]}"
            if r.startswith('pdf_base64_error:'):
                return f"PDF base64 napaka: {r.split(':', 1)[1]}"
            if r.startswith('exception:'):
                return f"Izjema: {r.split(':', 1)[1].strip()}"
            return r or '(brez razloga)'

        # Normalize inputs
        ok_orders = sorted(
            {_norm(o) for o in (order_numbers or []) if _norm(o)},
            key=_sort_key,
        )
        prior_orders = sorted(
            {_norm(o) for o in (prior_uploaded_orders or []) if _norm(o)},
            key=_sort_key,
        )
        # Avoid duplicates between "zdaj" and "prej"
        prior_orders = [p for p in prior_orders if p not in set(ok_orders)]

        # Failed (list of {order_number, reason})
        failed_list = []
        seen_failed = set()
        for it in (failed_orders or []):
            if not isinstance(it, dict):
                continue
            on = _norm(it.get('order_number'))
            if not on or on in seen_failed:
                continue
            seen_failed.add(on)
            failed_list.append({
                'order_number': on,
                'reason': str(it.get('reason') or '').strip(),
            })
        failed_list.sort(key=lambda x: _sort_key(x['order_number']))

        # No-PDF (manjkajoči podatki)
        no_pdf_list = []
        seen_no_pdf = set()
        for it in (no_pdf_orders or []):
            if not isinstance(it, dict):
                continue
            on = _norm(it.get('order_number'))
            if not on or on in seen_no_pdf:
                continue
            seen_no_pdf.add(on)
            no_pdf_list.append({
                'order_number': on,
                'reason': str(it.get('reason') or '').strip(),
            })
        no_pdf_list.sort(key=lambda x: _sort_key(x['order_number']))

        n_ok = len(ok_orders)
        n_fail = len(failed_list)
        n_no_pdf = len(no_pdf_list)
        n_prior = len(prior_orders)

        # Subject: scoreboard + datum
        date_label = sent_at.strftime('%d.%m.%Y')
        subject = (
            f"MK deklaracije {date_label}: "
            f"{n_ok} ✅"
            + (f" / {n_fail} ❌" if n_fail else "")
            + (f" / {n_no_pdf} ⚠️" if n_no_pdf else "")
        )

        # ----- HTML stilske helperje -----
        TH = "padding:8px 10px;border:1px solid #e5e7eb;background:#f9fafb;text-align:left;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:#374151"
        TD = "padding:8px 10px;border:1px solid #e5e7eb;font-size:13px;vertical-align:top"
        TBL = "border-collapse:collapse;width:100%;margin:6px 0 14px 0"
        LINK = "color:#4f46e5;text-decoration:none"

        def _table_simple(orders: list, header_label: str, badge_color: str) -> str:
            if not orders:
                return ""
            rows = "".join(
                f"<tr>"
                f"<td style='{TD};width:120px'>"
                f"<a href='{_order_link(o)}' style='{LINK}' target='_blank'>#{_esc(o)}</a>"
                f"</td>"
                f"<td style='{TD};color:#6b7280'>—</td>"
                f"</tr>"
                for o in orders
            )
            return (
                f"<table style='{TBL}'>"
                f"<thead><tr>"
                f"<th style='{TH}'><span style=\"color:{badge_color}\">●</span> Naročilo</th>"
                f"<th style='{TH}'>{_esc(header_label)}</th>"
                f"</tr></thead>"
                f"<tbody>{rows}</tbody></table>"
            )

        def _table_with_reason(items: list, header_label: str, badge_color: str) -> str:
            if not items:
                return ""
            rows = "".join(
                f"<tr>"
                f"<td style='{TD};width:120px'>"
                f"<a href='{_order_link(it['order_number'])}' style='{LINK}' target='_blank'>#{_esc(it['order_number'])}</a>"
                f"</td>"
                f"<td style='{TD}'>{_esc(_human_reason(it['reason']))}</td>"
                f"</tr>"
                for it in items
            )
            return (
                f"<table style='{TBL}'>"
                f"<thead><tr>"
                f"<th style='{TH}'><span style=\"color:{badge_color}\">●</span> Naročilo</th>"
                f"<th style='{TH}'>{_esc(header_label)}</th>"
                f"</tr></thead>"
                f"<tbody>{rows}</tbody></table>"
            )

        # ----- Statistike (zgornja KPI vrstica) -----
        stats = stats or {}
        kpi = lambda label, val, color="#111827": (
            f"<td style='padding:10px 14px;border:1px solid #e5e7eb;border-radius:8px;background:#fff;'>"
            f"<div style='font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.04em'>{_esc(label)}</div>"
            f"<div style='font-size:22px;font-weight:700;color:{color};margin-top:2px'>{_esc(val if val is not None else '–')}</div>"
            f"</td>"
        )
        kpi_row = (
            "<table style='border-collapse:separate;border-spacing:8px;margin:0 -8px 14px -8px'>"
            "<tr>"
            f"{kpi('Fulfilled danes', stats.get('fulfilled_today'))}"
            f"{kpi('PDF generirano', stats.get('pdf_today'), '#4f46e5')}"
            f"{kpi('MK upload', stats.get('mk_today'), '#16a34a')}"
            f"{kpi('Manjka MK', stats.get('missing_mk_today'), '#dc2626' if (stats.get('missing_mk_today') or 0) else '#6b7280')}"
            "</tr></table>"
        )

        # ----- Sestavi sekcije -----
        sections_html = []
        if n_ok:
            sections_html.append(
                f"<h3 style='font-size:15px;margin:16px 0 6px;color:#16a34a'>✅ Naloženo v MK v tem batchu ({n_ok})</h3>"
                + _table_simple(ok_orders, "Status", "#16a34a")
            )
        if n_fail:
            sections_html.append(
                f"<h3 style='font-size:15px;margin:16px 0 6px;color:#dc2626'>❌ Neuspeli MK upload ({n_fail})</h3>"
                + _table_with_reason(failed_list, "Razlog", "#dc2626")
            )
        if n_no_pdf:
            sections_html.append(
                f"<h3 style='font-size:15px;margin:16px 0 6px;color:#d97706'>⚠️ Fulfilled brez PDF ({n_no_pdf})</h3>"
                + "<div style='font-size:12px;color:#6b7280;margin-bottom:6px'>"
                + "Tem naročilom <strong>stranka NE bo prejela deklaracije</strong> dokler ne dopolnimo podatkov. "
                + "Po popravku jih bo hourly reconcile job samodejno potegnil v MK."
                + "</div>"
                + _table_with_reason(no_pdf_list, "Manjka", "#d97706")
            )
        if n_prior:
            sections_html.append(
                f"<h3 style='font-size:15px;margin:16px 0 6px;color:#6b7280'>ℹ️ Že naloženo prej istega dne ({n_prior})</h3>"
                + "<div style='font-size:12px;color:#6b7280;margin-bottom:6px'>"
                + "Hourly reconcile job (vsako uro) je naročilo že naložil pred 21:00 batchem."
                + "</div>"
                + _table_simple(prior_orders, "Status", "#6b7280")
            )

        if not sections_html:
            sections_html.append(
                "<div style='padding:14px;border:1px dashed #e5e7eb;border-radius:8px;color:#6b7280;text-align:center'>"
                "V tem ciklu ni novih aktivnosti glede MK deklaracij.</div>"
            )

        period_text = "danes" if window_days == 1 else f"zadnjih {window_days} dni"
        html_body = f"""
        <div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:760px;margin:0 auto;color:#111827;background:#f3f4f6;padding:18px">
          <div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:22px">
            <div style="display:flex;align-items:baseline;justify-content:space-between;gap:12px;border-bottom:1px solid #e5e7eb;padding-bottom:12px;margin-bottom:14px">
              <h2 style="margin:0;font-size:18px">MK deklaracije — dnevni report</h2>
              <div style="font-size:12px;color:#6b7280">{_esc(sent_at.strftime('%d.%m.%Y %H:%M'))}</div>
            </div>
            <div style="font-size:13px;color:#374151;margin-bottom:14px">
              Pregled za <strong>{_esc(period_text)}</strong>. Logika: ob 21:00 generiramo PDF deklaracije za vsa fulfilled naročila in jih naložimo v MK. MK nato preko Mandrilla pošlje račun s prilogo stranki, ko označi naročilo kot <em>Zaključeno</em>.
            </div>
            {kpi_row}
            {''.join(sections_html)}
            <div style="margin-top:18px;font-size:11px;color:#9ca3af;border-top:1px solid #e5e7eb;padding-top:10px">
              Pošiljevalec: APP background scheduler · Tehnika: <code style="background:#f3f4f6;padding:1px 4px;border-radius:4px">process_fulfilled_orders_daily(window_days={_esc(window_days)})</code>
            </div>
          </div>
        </div>
        """

        msg = MIMEMultipart()
        msg['From'] = username
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)
        return True
    except Exception as e:
        current_app.logger.error(f"Napaka pri pošiljanju MK reporta: {e}")
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# Safety net alerts (instant + daily digest)
# ---------------------------------------------------------------------------

def _safety_net_send_html(subject: str, html_body: str) -> bool:
    """Pošlje HTML email adminu (interna funkcija za safety net alerts)."""
    try:
        recipient = current_app.config.get('ADMIN_EMAIL')
        if not recipient:
            current_app.logger.error("ADMIN_EMAIL ni nastavljen, safety net alert ne bo poslan.")
            return False
        smtp_server = current_app.config.get('MAIL_SERVER')
        smtp_port = current_app.config.get('MAIL_PORT', 587)
        username = current_app.config.get('MAIL_USERNAME')
        password = current_app.config.get('MAIL_PASSWORD')
        if not (smtp_server and username and password):
            current_app.logger.error("SMTP ni konfiguriran, safety net alert ne bo poslan.")
            return False

        msg = MIMEMultipart()
        msg['From'] = username
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)
        return True
    except Exception as e:
        current_app.logger.error(f"Safety net alert send error: {e}")
        traceback.print_exc()
        return False


def poslji_safety_net_instant_alert(order_data: dict, analysis: dict) -> bool:
    """Instant alert za blokirano naročilo, ki je staro >7 dni.

    Pošlje takoj, ko safety net cron prvič zazna blokado pri starem naročilu
    (critical_alert_sent_at se nato nastavi, da ne spam-amo).
    """
    import html as html_lib
    order_number = order_data.get('order_number') or '?'
    customer = order_data.get('customer_name') or order_data.get('customer_email') or '?'
    created = order_data.get('created_at')
    created_str = str(created)[:10] if created else '?'
    codes = analysis.get('blocked_codes') or []
    missing = analysis.get('missing') or []

    admin_base = (current_app.config.get('ADMIN_NEXT_BASE_URL')
                  or os.environ.get('ADMIN_NEXT_BASE_URL')
                  or 'https://koper-deklaracije-v2.vercel.app').rstrip('/')
    order_url = f"{admin_base}/narocila/{html_lib.escape(str(order_number).lstrip('#'))}"

    codes_html = "".join(
        f"<li><code style='background:#fee2e2;padding:2px 6px;border-radius:4px'>{html_lib.escape(c)}</code></li>"
        for c in codes
    )
    missing_html = "".join(f"<li>{html_lib.escape(str(m))}</li>" for m in missing)

    html_body = f"""
    <div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:640px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #fecaca">
      <div style="background:#dc2626;color:#fff;padding:14px 20px;font-size:15px;font-weight:600">
        🚨 Deklaracija blokirana — staro naročilo
      </div>
      <div style="padding:18px 20px;font-size:14px;color:#374151;line-height:1.6">
        <p><strong>Naročilo:</strong> <a href="{order_url}" style="color:#dc2626">{html_lib.escape(str(order_number))}</a></p>
        <p><strong>Kupec:</strong> {html_lib.escape(str(customer))}</p>
        <p><strong>Ustvarjeno:</strong> {html_lib.escape(created_str)}</p>
        <p style="margin-top:14px"><strong>Razlogi blokade:</strong></p>
        <ul style="margin:6px 0 12px 18px">{missing_html}</ul>
        <p><strong>Code-i (za invalidation):</strong></p>
        <ul style="margin:6px 0 12px 18px">{codes_html}</ul>
        <div style="margin-top:16px;padding:10px;background:#fef3c7;border-radius:8px;font-size:13px">
          ⚠️ Stranka <strong>NE</strong> bo prejela deklaracije, dokler ne vneseš manjkajočih podatkov.
          Po popravku se naročilo avtomatsko odblokira (smart invalidation hook).
        </div>
        <p style="margin-top:18px;font-size:12px;color:#6b7280">
          Naročilo je starejše od 7 dni — ker stranka že čaka, je nujno čimprej rešiti.
        </p>
      </div>
    </div>
    """
    subject = f"🚨 [URGENT] Deklaracija blokirana: {order_number}"
    return _safety_net_send_html(subject, html_body)


def poslji_safety_net_daily_digest(stats: dict, blocked_orders: list, recent_safety_sends: list) -> bool:
    """Dnevni povzetek safety net dejavnosti (ob 21:30, po dnevnem batchu)."""
    import html as html_lib

    admin_base = (current_app.config.get('ADMIN_NEXT_BASE_URL')
                  or os.environ.get('ADMIN_NEXT_BASE_URL')
                  or 'https://koper-deklaracije-v2.vercel.app').rstrip('/')

    def order_link(o):
        n = html_lib.escape(str(o or '').lstrip('#'))
        return f'<a href="{admin_base}/narocila/{n}" style="color:#2563eb;text-decoration:none">#{n}</a>'

    blocked_rows = ""
    for b in (blocked_orders or [])[:50]:
        codes_str = ", ".join(b.get('codes') or [])
        blocked_rows += f"""
        <tr>
          <td style="padding:6px 10px;border-bottom:1px solid #f3f4f6">{order_link(b.get('order_number'))}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #f3f4f6;font-size:12px;color:#6b7280">
            <code style="background:#fee2e2;padding:1px 4px;border-radius:3px">{html_lib.escape(codes_str)}</code>
          </td>
          <td style="padding:6px 10px;border-bottom:1px solid #f3f4f6;font-size:12px;color:#6b7280">
            {html_lib.escape(str(b.get('reason') or '')[:120])}
          </td>
        </tr>"""

    sends_rows = ""
    for s in (recent_safety_sends or [])[:50]:
        sends_rows += f"""
        <tr>
          <td style="padding:6px 10px;border-bottom:1px solid #f3f4f6">{order_link(s.get('order_number'))}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #f3f4f6">{html_lib.escape(str(s.get('status') or ''))}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #f3f4f6;font-size:12px;color:#6b7280">{html_lib.escape(str(s.get('email') or ''))}</td>
        </tr>"""

    n_blocked = len(blocked_orders or [])
    n_sends = len(recent_safety_sends or [])

    html_body = f"""
    <div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:720px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e5e7eb">
      <div style="background:linear-gradient(90deg,#4f46e5,#7c3aed);color:#fff;padding:14px 20px;font-size:15px;font-weight:600">
        📊 Safety net dnevni povzetek
      </div>
      <div style="padding:18px 20px;font-size:14px;color:#374151">
        <p style="margin:0 0 14px">
          <strong>Scanned:</strong> {stats.get('scanned', 0)} ·
          <strong style="color:#dc2626">Blocked:</strong> {n_blocked} ·
          <strong style="color:#16a34a">Uspesno v MK:</strong> {stats.get('uploaded_mk_only', 0)} ·
          <strong style="color:#7c3aed">Mandrill safety sends:</strong> {stats.get('uploaded_and_mandrill', 0)} ·
          <strong>Errors:</strong> {stats.get('errors', 0)}
        </p>

        {('<h3 style="font-size:14px;margin:18px 0 6px;color:#dc2626">🚨 Trenutno blokirana naročila ({})</h3>'
          '<table style="width:100%;border-collapse:collapse;font-size:13px">'
          '<thead style="background:#f9fafb"><tr>'
          '<th style="text-align:left;padding:6px 10px">Naročilo</th>'
          '<th style="text-align:left;padding:6px 10px">Codes</th>'
          '<th style="text-align:left;padding:6px 10px">Razlog</th>'
          '</tr></thead><tbody>'
          f'{blocked_rows}</tbody></table>').format(n_blocked) if n_blocked else ''}

        {('<h3 style="font-size:14px;margin:18px 0 6px;color:#7c3aed">💌 Direktni Mandrill sends (zadnji dan)</h3>'
          '<table style="width:100%;border-collapse:collapse;font-size:13px">'
          '<thead style="background:#f9fafb"><tr>'
          '<th style="text-align:left;padding:6px 10px">Naročilo</th>'
          '<th style="text-align:left;padding:6px 10px">Status</th>'
          '<th style="text-align:left;padding:6px 10px">Email</th>'
          '</tr></thead><tbody>'
          f'{sends_rows}</tbody></table>') if n_sends else ''}

        <div style="margin-top:18px;font-size:11px;color:#9ca3af;border-top:1px solid #e5e7eb;padding-top:10px">
          Safety net job teče vsako uro · invalidation se sproži ob vnosu serije/INCI/metafield
        </div>
      </div>
    </div>
    """
    today = datetime.now().strftime('%d.%m.%Y')
    subject = f"📊 Safety net povzetek {today} — {n_blocked} blokiranih"
    return _safety_net_send_html(subject, html_body)