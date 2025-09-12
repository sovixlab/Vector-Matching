# Vector Matching Project Backup Systeem

Dit backup systeem biedt drie verschillende backup opties voor je Vector Matching project.

## 📁 Backup Locaties

Alle backups worden opgeslagen in: `./backups/`

## 🚀 Backup Opties

### 1. Quick Backup (Aanbevolen voor dagelijks gebruik)
```bash
python backup_quick.py
```
- **Wat**: Alle project bestanden in een gecomprimeerde ZIP
- **Wanneer**: Dagelijks, voor snelle backups
- **Grootte**: Klein (alleen bestanden)
- **Herstel**: Eenvoudig uitpakken

### 2. Volledige Backup (Aanbevolen voor belangrijke momenten)
```bash
python backup_project.py
```
- **Wat**: Project bestanden + database + environment configuratie
- **Wanneer**: Voor belangrijke wijzigingen, voor productie deployment
- **Grootte**: Groter (inclusief database)
- **Herstel**: Automatisch met restore script

### 3. Handmatige Database Backup
```bash
# Voor SQLite
cp db.sqlite3 backups/database_$(date +%Y%m%d_%H%M%S).sqlite3

# Voor PostgreSQL
pg_dump -h localhost -U username -d database_name > backups/database_$(date +%Y%m%d_%H%M%S).sql
```

## 🔄 Herstellen

### Quick Backup Herstellen
1. Pak de ZIP uit: `unzip backups/vector_matching_backup_YYYYMMDD_HHMMSS.zip`
2. Ga naar de uitgepakte directory
3. Installeer dependencies: `pip install -r requirements.txt`
4. Voer migraties uit: `python manage.py migrate`
5. Start server: `python manage.py runserver`

### Volledige Backup Herstellen
```bash
python restore_project.py YYYYMMDD_HHMMSS
```

**Opties:**
- `--target DIR`: Specificeer target directory (default: huidige directory)
- `--skip-deps`: Sla dependency installatie over
- `--skip-django`: Sla Django commando's over

**Voorbeeld:**
```bash
# Herstel in huidige directory
python restore_project.py 20241201_143022

# Herstel in nieuwe directory
python restore_project.py 20241201_143022 --target /path/to/new/project

# Herstel zonder dependencies te installeren
python restore_project.py 20241201_143022 --skip-deps
```

## 📊 Database Ondersteuning

### SQLite (Lokaal)
- **Backup**: Automatisch gekopieerd
- **Herstel**: Automatisch hersteld
- **Bestand**: `database_YYYYMMDD_HHMMSS.sqlite3`

### PostgreSQL (Productie)
- **Backup**: Via `pg_dump`
- **Herstel**: Handmatig via `psql` of `pg_restore`
- **Bestand**: `database_YYYYMMDD_HHMMSS.sql`

## 🛡️ Veiligheid

### Wat wordt NIET gebackupt:
- `.env` bestanden (bevatten gevoelige data)
- `__pycache__` directories
- `node_modules`
- `.git` directory
- `staticfiles` en `media` directories
- Log bestanden

### Wat wordt WEL gebackupt:
- Alle Python bestanden
- Templates en statische bestanden
- Database (zonder wachtwoorden)
- Environment configuratie (zonder gevoelige data)
- Requirements en configuratie bestanden

## 📋 Backup Checklist

### Voor belangrijke wijzigingen:
- [ ] Maak volledige backup: `python backup_project.py`
- [ ] Test de backup door te herstellen in test directory
- [ ] Bewaar backup op veilige locatie (externe drive/cloud)

### Voor dagelijks gebruik:
- [ ] Maak quick backup: `python backup_quick.py`
- [ ] Bewaar laatste 7 dagen van backups

### Voor productie deployment:
- [ ] Maak volledige backup van huidige versie
- [ ] Test restore proces
- [ ] Documenteer backup locatie
- [ ] Zorg voor off-site backup

## 🔧 Troubleshooting

### Backup problemen:
```bash
# Controleer of backup directory bestaat
ls -la backups/

# Controleer database connectie
python manage.py dbshell

# Test backup script
python backup_project.py --help
```

### Restore problemen:
```bash
# Controleer beschikbare backups
ls -la backups/

# Test restore in test directory
python restore_project.py YYYYMMDD_HHMMSS --target /tmp/test_restore

# Controleer Django setup
python manage.py check
```

## 📞 Ondersteuning

Als je problemen hebt met backup/restore:
1. Controleer de error messages
2. Bekijk de restore instructies in `backups/RESTORE_INSTRUCTIONS_*.md`
3. Test met een kleine backup eerst
4. Zorg dat alle dependencies geïnstalleerd zijn

## 💡 Tips

- **Regelmatig backuppen**: Minimaal dagelijks voor actieve projecten
- **Test je backups**: Regelmatig restore testen
- **Off-site opslag**: Bewaar belangrijke backups op externe locatie
- **Automatisering**: Overweeg cron job voor automatische backups
- **Documentatie**: Houd bij welke backup bij welke versie hoort
