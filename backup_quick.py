#!/usr/bin/env python3
"""
Quick Backup Script voor Vector Matching
========================================

Eenvoudige backup voor dagelijks gebruik.
Maakt een gecomprimeerde backup van het hele project.
"""

import os
import sys
import shutil
import subprocess
import datetime
from pathlib import Path
import zipfile

def create_quick_backup():
    """Maak een snelle gecomprimeerde backup"""
    print("🚀 Quick Backup - Vector Matching Project")
    print("=" * 50)
    
    # Maak backup directory
    backup_dir = Path("backups")
    backup_dir.mkdir(exist_ok=True)
    
    # Genereer timestamp
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"vector_matching_backup_{timestamp}"
    backup_zip = backup_dir / f"{backup_name}.zip"
    
    print(f"📁 Backup bestand: {backup_zip}")
    print(f"🕐 Timestamp: {timestamp}")
    print()
    
    # Bestanden om uit te sluiten
    exclude_patterns = {
        '__pycache__',
        '*.pyc',
        '*.pyo',
        '*.pyd',
        '.git',
        'node_modules',
        '.env',
        'backups',
        'staticfiles',
        'media',
        '.DS_Store',
        'Thumbs.db',
        '*.log'
    }
    
    # Maak zip backup
    with zipfile.ZipFile(backup_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        project_root = Path('.')
        
        for file_path in project_root.rglob('*'):
            # Skip uitgesloten bestanden
            if any(pattern in str(file_path) for pattern in exclude_patterns):
                continue
            
            # Skip directories
            if file_path.is_dir():
                continue
            
            # Voeg bestand toe aan zip
            arcname = file_path.relative_to(project_root)
            zipf.write(file_path, arcname)
            
            if file_path.name.endswith(('.py', '.html', '.css', '.js')):
                print(f"📄 {arcname}")
    
    # Toon backup info
    file_size = backup_zip.stat().st_size
    file_size_mb = file_size / (1024 * 1024)
    
    print()
    print("=" * 50)
    print("✅ QUICK BACKUP VOLTOOID!")
    print("=" * 50)
    print(f"📦 Backup bestand: {backup_zip}")
    print(f"📊 Grootte: {file_size_mb:.1f} MB")
    print()
    print("💡 Om te herstellen:")
    print(f"1. Pak uit: unzip {backup_zip}")
    print("2. Ga naar de uitgepakte directory")
    print("3. Installeer dependencies: pip install -r requirements.txt")
    print("4. Voer migraties uit: python manage.py migrate")
    print("5. Start server: python manage.py runserver")
    print()
    print("🔄 Voor volledige backup met database: python backup_project.py")

if __name__ == "__main__":
    create_quick_backup()
