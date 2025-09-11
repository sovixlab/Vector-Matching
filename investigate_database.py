#!/usr/bin/env python
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vector_matching.settings')
django.setup()

from django.db import connection

def investigate_database():
    """Onderzoek de werkelijke database structuur."""
    cursor = connection.cursor()
    
    try:
        print("=== DATABASE ONDERZOEK ===")
        
        # Check candidate embedding field
        print("\n1. Candidate embedding field:")
        cursor.execute("""
            SELECT column_name, data_type, udt_name 
            FROM information_schema.columns 
            WHERE table_name = 'vector_matching_app_candidate' 
            AND column_name = 'embedding'
        """)
        result = cursor.fetchall()
        print(f"   Resultaat: {result}")
        
        # Check vacature embedding field
        print("\n2. Vacature embedding field:")
        cursor.execute("""
            SELECT column_name, data_type, udt_name 
            FROM information_schema.columns 
            WHERE table_name = 'vector_matching_app_vacature' 
            AND column_name = 'embedding'
        """)
        result = cursor.fetchall()
        print(f"   Resultaat: {result}")
        
        # Check if pgvector extension is installed
        print("\n3. PostgreSQL extensions:")
        cursor.execute("SELECT * FROM pg_extension WHERE extname = 'vector'")
        result = cursor.fetchall()
        print(f"   pgvector extension: {result}")
        
        # Check database version
        print("\n4. Database info:")
        cursor.execute("SELECT version()")
        result = cursor.fetchone()
        print(f"   PostgreSQL versie: {result[0][:100]}...")
        
        # Check current embedding data format
        print("\n5. Huidige embedding data sample:")
        cursor.execute("SELECT id, embedding FROM vector_matching_app_candidate WHERE embedding IS NOT NULL LIMIT 1")
        result = cursor.fetchone()
        if result:
            print(f"   Kandidaat {result[0]}: {type(result[1])} - {str(result[1])[:100]}...")
        else:
            print("   Geen embedding data gevonden")
            
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = investigate_database()
    sys.exit(0 if success else 1)

