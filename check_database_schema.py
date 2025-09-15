#!/usr/bin/env python3
"""
Database Schema Inspector
========================

Dit script controleert het database schema op Render om te zien
welke kolom types er zijn voor de embedding velden.
"""

import os
import sys
import django
from pathlib import Path

# Setup Django
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vector_matching.settings')
django.setup()

from django.db import connection

def check_database_schema():
    """Controleer het database schema voor embedding kolommen."""
    print("🔍 Database Schema Inspector")
    print("=" * 50)
    
    # Database info
    print(f"Database Engine: {connection.vendor}")
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version()")
            version = cursor.fetchone()[0]
            print(f"Database Version: {version}")
    except Exception as e:
        print(f"Database Version: Could not determine - {e}")
    print()
    
    # Check Candidate embedding kolom
    print("📊 CANDIDATE TABLE:")
    print("-" * 30)
    
    with connection.cursor() as cursor:
        # Get column info for candidate embedding
        cursor.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns 
            WHERE table_name = 'vector_matching_app_candidate' 
            AND column_name = 'embedding'
        """)
        
        candidate_columns = cursor.fetchall()
        if candidate_columns:
            for col in candidate_columns:
                print(f"  Kolom: {col[0]}")
                print(f"  Type: {col[1]}")
                print(f"  Nullable: {col[2]}")
                print(f"  Default: {col[3]}")
        else:
            print("  ❌ Embedding kolom niet gevonden!")
    
    print()
    
    # Check Vacature embedding kolom
    print("📊 VACATURE TABLE:")
    print("-" * 30)
    
    with connection.cursor() as cursor:
        # Get column info for vacature embedding
        cursor.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns 
            WHERE table_name = 'vector_matching_app_vacature' 
            AND column_name = 'embedding'
        """)
        
        vacature_columns = cursor.fetchall()
        if vacature_columns:
            for col in vacature_columns:
                print(f"  Kolom: {col[0]}")
                print(f"  Type: {col[1]}")
                print(f"  Nullable: {col[2]}")
                print(f"  Default: {col[3]}")
        else:
            print("  ❌ Embedding kolom niet gevonden!")
    
    print()
    
    # Check if pgvector extension is installed
    print("🔌 PGVECTOR EXTENSION:")
    print("-" * 30)
    
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT extname, extversion 
            FROM pg_extension 
            WHERE extname = 'vector'
        """)
        
        extensions = cursor.fetchall()
        if extensions:
            for ext in extensions:
                print(f"  Extension: {ext[0]} (versie {ext[1]})")
        else:
            print("  ❌ pgvector extension niet geïnstalleerd!")
    
    print()
    
    # Check actual data in embedding kolommen
    print("📈 DATA ANALYSIS:")
    print("-" * 30)
    
    with connection.cursor() as cursor:
        # Candidate data
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(embedding) as with_embedding,
                COUNT(*) - COUNT(embedding) as without_embedding
            FROM vector_matching_app_candidate
        """)
        
        candidate_stats = cursor.fetchone()
        print(f"  Kandidaten: {candidate_stats[0]} totaal, {candidate_stats[1]} met embedding, {candidate_stats[2]} zonder")
        
        # Vacature data
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(embedding) as with_embedding,
                COUNT(*) - COUNT(embedding) as without_embedding
            FROM vector_matching_app_vacature
        """)
        
        vacature_stats = cursor.fetchone()
        print(f"  Vacatures: {vacature_stats[0]} totaal, {vacature_stats[1]} met embedding, {vacature_stats[2]} zonder")
    
    print()
    
    # Test embedding insert
    print("🧪 EMBEDDING INSERT TEST:")
    print("-" * 30)
    
    try:
        with connection.cursor() as cursor:
            # Test vector insert
            test_embedding = [0.1, 0.2, 0.3]  # Dummy embedding
            
            # Test candidate table
            try:
                cursor.execute("""
                    UPDATE vector_matching_app_candidate 
                    SET embedding = %s::vector 
                    WHERE id = 1
                """, [test_embedding])
                print("  ✅ Candidate vector insert: SUCCESS")
            except Exception as e:
                print(f"  ❌ Candidate vector insert: FAILED - {e}")
            
            # Test vacature table
            try:
                cursor.execute("""
                    UPDATE vector_matching_app_vacature 
                    SET embedding = %s::vector 
                    WHERE id = 1
                """, [test_embedding])
                print("  ✅ Vacature vector insert: SUCCESS")
            except Exception as e:
                print(f"  ❌ Vacature vector insert: FAILED - {e}")
                
    except Exception as e:
        print(f"  ❌ Test failed: {e}")

if __name__ == "__main__":
    check_database_schema()
