#!/usr/bin/env python
"""
Script om database constraints te fixen op Render
"""
import os
import django
from django.conf import settings

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vector_matching.settings')
django.setup()

from django.db import connection
from django.core.management import execute_from_command_line

def fix_database_constraints():
    """Fix database constraints door velden nullable te maken"""
    with connection.cursor() as cursor:
        # Maak alle problematische velden nullable
        constraints_to_fix = [
            "ALTER TABLE vector_matching_app_candidate ALTER COLUMN name DROP NOT NULL;",
            "ALTER TABLE vector_matching_app_candidate ALTER COLUMN email DROP NOT NULL;",
            "ALTER TABLE vector_matching_app_candidate ALTER COLUMN phone DROP NOT NULL;",
            "ALTER TABLE vector_matching_app_candidate ALTER COLUMN street DROP NOT NULL;",
            "ALTER TABLE vector_matching_app_candidate ALTER COLUMN house_number DROP NOT NULL;",
            "ALTER TABLE vector_matching_app_candidate ALTER COLUMN postal_code DROP NOT NULL;",
            "ALTER TABLE vector_matching_app_candidate ALTER COLUMN city DROP NOT NULL;",
        ]
        
        for constraint in constraints_to_fix:
            try:
                cursor.execute(constraint)
                print(f"✅ Uitgevoerd: {constraint}")
            except Exception as e:
                print(f"⚠️  Fout bij {constraint}: {e}")
        
        # Commit de wijzigingen
        connection.commit()
        print("✅ Database constraints gefixed!")

if __name__ == "__main__":
    fix_database_constraints()
