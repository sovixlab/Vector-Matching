#!/usr/bin/env python3
"""
Vector Matching Project Restore Script
======================================

Dit script herstelt een backup van het Vector Matching project.
Gebruik: python restore_project.py <backup_timestamp>
"""

import os
import sys
import shutil
import subprocess
import json
import argparse
from pathlib import Path
import datetime

def find_backup(backup_timestamp):
    """Zoek backup directory op basis van timestamp"""
    backup_dir = Path("backups")
    
    if not backup_dir.exists():
        print("❌ Backup directory niet gevonden!")
        return None
    
    # Zoek project directory met timestamp
    project_dirs = [d for d in backup_dir.iterdir() 
                   if d.is_dir() and d.name.startswith(f"project_{backup_timestamp}")]
    
    if not project_dirs:
        print(f"❌ Backup met timestamp {backup_timestamp} niet gevonden!")
        print("Beschikbare backups:")
        for d in backup_dir.iterdir():
            if d.is_dir() and d.name.startswith("project_"):
                print(f"  - {d.name.replace('project_', '')}")
        return None
    
    return project_dirs[0]

def restore_project_files(project_backup_dir, target_dir):
    """Herstel project bestanden"""
    print(f"📂 Herstel project bestanden van {project_backup_dir.name}...")
    
    # Maak target directory aan als het niet bestaat
    target_dir.mkdir(exist_ok=True)
    
    # Kopieer alle bestanden
    for item in project_backup_dir.iterdir():
        target_path = target_dir / item.name
        
        if item.is_file():
            shutil.copy2(item, target_path)
        elif item.is_dir():
            if target_path.exists():
                shutil.rmtree(target_path)
            shutil.copytree(item, target_path)
    
    print("✅ Project bestanden hersteld!")

def restore_database(backup_dir, backup_timestamp, target_dir):
    """Herstel database"""
    print("🗄️  Herstel database...")
    
    # Zoek database backup
    db_files = list(backup_dir.glob(f"database_{backup_timestamp}.*"))
    
    if not db_files:
        print("❌ Database backup niet gevonden!")
        return False
    
    db_file = db_files[0]
    print(f"📁 Database backup gevonden: {db_file.name}")
    
    # Bepaal database type
    if db_file.suffix == '.sqlite3':
        # SQLite restore
        target_db = target_dir / "db.sqlite3"
        shutil.copy2(db_file, target_db)
        print(f"✅ SQLite database hersteld: {target_db}")
        return True
    
    elif db_file.suffix == '.sql':
        # PostgreSQL restore
        print("⚠️  PostgreSQL restore vereist handmatige stappen:")
        print(f"1. Zorg dat PostgreSQL draait")
        print(f"2. Maak een nieuwe database aan")
        print(f"3. Herstel met: psql -d DATABASE_NAME -f {db_file}")
        print(f"4. Of gebruik: pg_restore -d DATABASE_NAME {db_file}")
        return True
    
    else:
        print(f"❌ Onbekend database formaat: {db_file.suffix}")
        return False

def restore_environment(backup_dir, backup_timestamp):
    """Toon environment configuratie"""
    env_file = backup_dir / f"environment_{backup_timestamp}.json"
    
    if not env_file.exists():
        print("⚠️  Environment backup niet gevonden!")
        return
    
    print("⚙️  Environment configuratie:")
    print("-" * 30)
    
    with open(env_file, 'r', encoding='utf-8') as f:
        env_config = json.load(f)
    
    for key, value in env_config.items():
        if key == 'database_config':
            print(f"Database configuratie:")
            for db_key, db_value in value.items():
                print(f"  {db_key}: {db_value}")
        else:
            print(f"{key}: {value}")
    
    print("\n💡 Maak een .env bestand aan met deze waarden!")

def install_dependencies(target_dir):
    """Installeer Python dependencies"""
    print("📦 Installeer dependencies...")
    
    requirements_file = target_dir / "requirements.txt"
    
    if not requirements_file.exists():
        print("⚠️  requirements.txt niet gevonden!")
        return False
    
    try:
        result = subprocess.run([
            sys.executable, "-m", "pip", "install", "-r", str(requirements_file)
        ], capture_output=True, text=True, cwd=target_dir)
        
        if result.returncode == 0:
            print("✅ Dependencies geïnstalleerd!")
            return True
        else:
            print(f"❌ Dependency installatie gefaald: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Dependency installatie error: {e}")
        return False

def run_django_commands(target_dir):
    """Voer Django commando's uit"""
    print("🔧 Voer Django setup uit...")
    
    commands = [
        ["python", "manage.py", "migrate"],
        ["python", "manage.py", "collectstatic", "--noinput"],
    ]
    
    for cmd in commands:
        print(f"🔄 Uitvoeren: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, cwd=target_dir, capture_output=True, text=True)
            if result.returncode == 0:
                print("✅ Succesvol!")
            else:
                print(f"⚠️  Waarschuwing: {result.stderr}")
        except Exception as e:
            print(f"❌ Fout bij {cmd[2]}: {e}")

def main():
    """Hoofdfunctie voor restore"""
    parser = argparse.ArgumentParser(description='Herstel Vector Matching project backup')
    parser.add_argument('timestamp', help='Backup timestamp (bijv. 20241201_143022)')
    parser.add_argument('--target', '-t', default='.', 
                       help='Target directory (default: huidige directory)')
    parser.add_argument('--skip-deps', action='store_true',
                       help='Sla dependency installatie over')
    parser.add_argument('--skip-django', action='store_true',
                       help='Sla Django commando\'s over')
    
    args = parser.parse_args()
    
    print("🔄 Vector Matching Project Restore")
    print("=" * 50)
    print(f"🕐 Backup timestamp: {args.timestamp}")
    print(f"📁 Target directory: {args.target}")
    print()
    
    # Zoek backup
    project_backup_dir = find_backup(args.timestamp)
    if not project_backup_dir:
        return 1
    
    backup_dir = project_backup_dir.parent
    target_dir = Path(args.target)
    
    # Herstel project bestanden
    restore_project_files(project_backup_dir, target_dir)
    print()
    
    # Herstel database
    restore_database(backup_dir, args.timestamp, target_dir)
    print()
    
    # Toon environment configuratie
    restore_environment(backup_dir, args.timestamp)
    print()
    
    # Installeer dependencies
    if not args.skip_deps:
        install_dependencies(target_dir)
        print()
    
    # Voer Django commando's uit
    if not args.skip_django:
        run_django_commands(target_dir)
        print()
    
    print("=" * 50)
    print("✅ RESTORE VOLTOOID!")
    print("=" * 50)
    print("🔍 Controleer of alles werkt:")
    print("1. python manage.py runserver")
    print("2. Test de applicatie in je browser")
    print("3. Controleer database connectie")
    print("4. Test embedding functionaliteit")
    print()
    print("💡 Als er problemen zijn, bekijk de restore instructies!")

if __name__ == "__main__":
    sys.exit(main())
