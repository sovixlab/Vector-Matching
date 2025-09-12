#!/usr/bin/env python3
"""
Vector Matching Project Backup Script
=====================================

Dit script maakt een volledige backup van:
- Alle project bestanden
- Database (SQLite of PostgreSQL)
- Environment variabelen
- Dependencies

Backup wordt opgeslagen in: ./backups/
"""

import os
import sys
import shutil
import subprocess
import json
import datetime
from pathlib import Path
import django
from django.conf import settings

# Voeg project root toe aan Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vector_matching.settings')
django.setup()

def create_backup_directory():
    """Maak backup directory aan"""
    backup_dir = project_root / "backups"
    backup_dir.mkdir(exist_ok=True)
    return backup_dir

def get_database_info():
    """Haal database informatie op"""
    db_config = settings.DATABASES['default']
    return {
        'engine': db_config['ENGINE'],
        'name': db_config.get('NAME', ''),
        'host': db_config.get('HOST', ''),
        'port': db_config.get('PORT', ''),
        'user': db_config.get('USER', ''),
        'password': db_config.get('PASSWORD', ''),
    }

def backup_sqlite_database(db_path, backup_dir, timestamp):
    """Backup SQLite database"""
    if not os.path.exists(db_path):
        print(f"⚠️  SQLite database niet gevonden: {db_path}")
        return None
    
    backup_file = backup_dir / f"database_{timestamp}.sqlite3"
    shutil.copy2(db_path, backup_file)
    print(f"✅ SQLite database gebackupt: {backup_file}")
    return backup_file

def backup_postgresql_database(db_info, backup_dir, timestamp):
    """Backup PostgreSQL database"""
    try:
        # Maak pg_dump commando
        env = os.environ.copy()
        if db_info['password']:
            env['PGPASSWORD'] = db_info['password']
        
        backup_file = backup_dir / f"database_{timestamp}.sql"
        
        cmd = [
            'pg_dump',
            '--host', db_info['host'] or 'localhost',
            '--port', str(db_info['port']) or '5432',
            '--username', db_info['user'],
            '--no-password',
            '--verbose',
            '--clean',
            '--no-owner',
            '--no-privileges',
            '--format=plain',
            '--file', str(backup_file),
            db_info['name']
        ]
        
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✅ PostgreSQL database gebackupt: {backup_file}")
            return backup_file
        else:
            print(f"❌ PostgreSQL backup gefaald: {result.stderr}")
            return None
            
    except FileNotFoundError:
        print("❌ pg_dump niet gevonden. Installeer PostgreSQL client tools.")
        return None
    except Exception as e:
        print(f"❌ PostgreSQL backup error: {e}")
        return None

def backup_project_files(backup_dir, timestamp):
    """Backup alle project bestanden"""
    # Bestanden/directories om uit te sluiten
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
        'Thumbs.db'
    }
    
    project_backup_dir = backup_dir / f"project_{timestamp}"
    project_backup_dir.mkdir(exist_ok=True)
    
    # Kopieer alle bestanden behalve uitgesloten
    for item in project_root.iterdir():
        if item.name in exclude_patterns:
            continue
            
        if item.is_file():
            shutil.copy2(item, project_backup_dir)
        elif item.is_dir():
            shutil.copytree(item, project_backup_dir / item.name, 
                          ignore=shutil.ignore_patterns(*exclude_patterns))
    
    print(f"✅ Project bestanden gebackupt: {project_backup_dir}")
    return project_backup_dir

def backup_environment_variables(backup_dir, timestamp):
    """Backup environment variabelen (zonder gevoelige data)"""
    env_backup = {}
    
    # Veilige environment variabelen
    safe_vars = [
        'DEBUG', 'ALLOWED_HOSTS', 'CSRF_TRUSTED_ORIGINS',
        'LANGUAGE_CODE', 'TIME_ZONE', 'STATIC_URL', 'MEDIA_URL'
    ]
    
    for var in safe_vars:
        if var in os.environ:
            env_backup[var] = os.environ[var]
    
    # Database configuratie (zonder wachtwoorden)
    db_info = get_database_info()
    env_backup['database_config'] = {
        'engine': db_info['engine'],
        'name': str(db_info['name']),  # Converteer Path naar string
        'host': db_info['host'],
        'port': db_info['port'],
        'user': db_info['user']
    }
    
    env_file = backup_dir / f"environment_{timestamp}.json"
    with open(env_file, 'w', encoding='utf-8') as f:
        json.dump(env_backup, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Environment configuratie gebackupt: {env_file}")
    return env_file

def create_restore_instructions(backup_dir, timestamp, db_file, project_dir, env_file):
    """Maak restore instructies"""
    instructions = f"""# Vector Matching Project Restore Instructies
# Backup gemaakt op: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# Backup ID: {timestamp}

## Stap 1: Project Bestanden Herstellen
1. Kopieer alle bestanden uit: {project_dir.name}/
2. Plaats ze in je project directory

## Stap 2: Database Herstellen
"""
    
    db_info = get_database_info()
    if 'sqlite' in db_info['engine']:
        instructions += f"""1. Kopieer {db_file.name} naar je project root
2. Hernoem naar: db.sqlite3
3. Zorg dat Django de juiste permissies heeft
"""
    else:
        instructions += f"""1. Zorg dat PostgreSQL draait
2. Maak een nieuwe database aan
3. Herstel met: psql -d DATABASE_NAME -f {db_file.name}
4. Of gebruik: pg_restore -d DATABASE_NAME {db_file.name}
"""
    
    instructions += f"""
## Stap 3: Dependencies Installeren
1. pip install -r requirements.txt

## Stap 4: Environment Variabelen
1. Bekijk {env_file.name} voor de originele configuratie
2. Maak een .env bestand aan met je eigen waarden
3. Zorg dat DATABASE_URL correct is ingesteld

## Stap 5: Django Setup
1. python manage.py migrate
2. python manage.py collectstatic
3. python manage.py runserver

## Stap 6: Test
1. Controleer of de applicatie start
2. Test database connectie
3. Test embedding functionaliteit
"""
    
    instructions_file = backup_dir / f"RESTORE_INSTRUCTIONS_{timestamp}.md"
    with open(instructions_file, 'w', encoding='utf-8') as f:
        f.write(instructions)
    
    print(f"✅ Restore instructies gemaakt: {instructions_file}")
    return instructions_file

def main():
    """Hoofdfunctie voor backup"""
    print("🚀 Vector Matching Project Backup")
    print("=" * 50)
    
    # Maak backup directory
    backup_dir = create_backup_directory()
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    
    print(f"📁 Backup directory: {backup_dir}")
    print(f"🕐 Timestamp: {timestamp}")
    print()
    
    # Haal database info op
    db_info = get_database_info()
    print(f"🗄️  Database type: {db_info['engine']}")
    
    # Backup database
    db_file = None
    if 'sqlite' in db_info['engine']:
        db_file = backup_sqlite_database(db_info['name'], backup_dir, timestamp)
    else:
        db_file = backup_postgresql_database(db_info, backup_dir, timestamp)
    
    if not db_file:
        print("⚠️  Database backup gefaald, maar project backup gaat door...")
    
    # Backup project bestanden
    project_dir = backup_project_files(backup_dir, timestamp)
    
    # Backup environment
    env_file = backup_environment_variables(backup_dir, timestamp)
    
    # Maak restore instructies
    instructions_file = create_restore_instructions(
        backup_dir, timestamp, db_file, project_dir, env_file
    )
    
    # Toon backup samenvatting
    print("\n" + "=" * 50)
    print("✅ BACKUP VOLTOOID!")
    print("=" * 50)
    print(f"📁 Backup locatie: {backup_dir}")
    print(f"🗄️  Database: {db_file.name if db_file else 'GEFAALD'}")
    print(f"📂 Project: {project_dir.name}")
    print(f"⚙️  Environment: {env_file.name}")
    print(f"📋 Instructies: {instructions_file.name}")
    print()
    print("💡 Tip: Bewaar deze backup op een veilige locatie!")
    print("🔄 Gebruik restore_project.py om terug te zetten")

if __name__ == "__main__":
    main()
