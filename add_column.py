#!/usr/bin/env python3
"""
Simple script to add shopify_fulfilled_at column to orders table
"""

import os
import psycopg
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def add_column():
    """Add shopify_fulfilled_at column to orders table"""
    
    # Get database URL from environment
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("Error: DATABASE_URL not found in environment")
        return
    
    try:
        # Connect to database
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cursor:
                
                print("Adding shopify_fulfilled_at column to orders table...")
                
                # Add the column
                cursor.execute("""
                    ALTER TABLE orders 
                    ADD COLUMN IF NOT EXISTS shopify_fulfilled_at TIMESTAMP WITH TIME ZONE;
                """)
                
                # Add index for better performance
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_orders_shopify_fulfilled_at 
                    ON orders(shopify_fulfilled_at);
                """)
                
                conn.commit()
                print("✅ Column added successfully!")
                
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    
    return True

if __name__ == "__main__":
    add_column() 