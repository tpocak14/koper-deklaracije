#!/usr/bin/env python3
"""
Script za popravek dovoljenj uporabnikov.
"""

import os
import psycopg
import json
from dotenv import load_dotenv

# Naloži spremenljivke okolja
load_dotenv()

def fix_user_permissions():
    """Popravi dovoljenja za obstoječe uporabnike."""
    
    # Pridobi DATABASE_URL iz okolja
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("❌ DATABASE_URL ni nastavljen v okolju")
        return False
    
    try:
        # Poveži se z bazo
        db = psycopg.connect(database_url)
        cursor = db.cursor()
        
        print("🔧 Popravljam dovoljenja uporabnikov...")
        
        # Osnovna dovoljenja za uporabnike
        user_permissions = [
            "view_orders", "view_perfumes", "view_proizvajalci", "view_users",
            "add_serije", "edit_serije", "generate_pdf", "send_email"
        ]
        
        # Admin dovoljenja
        admin_permissions = [
            "view_global_actions",
            "view_orders", "add_serije", "edit_serije", "delete_serije",
            "view_perfumes", "edit_perfumes", "add_perfumes", "delete_perfumes",
            "view_proizvajalci", "edit_proizvajalci", "add_proizvajalci", "delete_proizvajalci",
            "view_users", "edit_users", "add_users", "delete_users",
            "shopify_sync", "generate_pdf", "send_email"
        ]
        
        # Nastavi osnovna dovoljenja za vse uporabnike z role = 'user' in praznimi dovoljenji
        cursor.execute("""
            UPDATE users 
            SET permissions = %s
            WHERE role = 'user' 
              AND (permissions IS NULL OR permissions = '[]'::jsonb OR permissions = 'null'::jsonb)
        """, (json.dumps(user_permissions),))
        
        user_count = cursor.rowcount
        print(f"✅ Posodobljenih {user_count} uporabnikov z osnovnimi dovoljenji")
        
        # Nastavi osnovna dovoljenja za uporabnike brez role
        cursor.execute("""
            UPDATE users 
            SET role = 'user',
                permissions = %s
            WHERE role IS NULL 
              AND (permissions IS NULL OR permissions = '[]'::jsonb OR permissions = 'null'::jsonb)
        """, (json.dumps(user_permissions),))
        
        null_role_count = cursor.rowcount
        print(f"✅ Posodobljenih {null_role_count} uporabnikov brez role")
        
        # Posodobi admin uporabnika z vsemi dovoljenji
        cursor.execute("""
            UPDATE users 
            SET role = 'admin', 
                permissions = %s
            WHERE username = 'admin'
        """, (json.dumps(admin_permissions),))
        
        admin_count = cursor.rowcount
        print(f"✅ Posodobljenih {admin_count} admin uporabnikov")
        
        # Pridobi trenutno stanje uporabnikov
        cursor.execute("""
            SELECT username, role, permissions
            FROM users 
            ORDER BY username
        """)
        
        users = cursor.fetchall()
        print("\n📋 Trenutno stanje uporabnikov:")
        for user in users:
            print(f"  - {user[0]}: role={user[1]}, permissions={user[2]}")
        
        db.commit()
        print("\n✅ Dovoljenja uspešno popravljena!")
        return True
        
    except Exception as e:
        print(f"❌ Napaka: {e}")
        if 'db' in locals():
            db.rollback()
        return False
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'db' in locals():
            db.close()

if __name__ == "__main__":
    fix_user_permissions()
