from celery import shared_task
from django.conf import settings
from django.utils import timezone
import os
import zipfile
import tempfile
import subprocess
import logging
from .models import Backup

logger = logging.getLogger(__name__)


@shared_task
def create_backup_task(backup_id):
    """Celery taak voor het maken van een backup."""
    try:
        backup = Backup.objects.get(id=backup_id)
        backup.status = 'running'
        backup.save()
        
        logger.info(f"Starting backup {backup.name} (ID: {backup_id})")
        
        # Maak tijdelijke directory voor backup
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_files = []
            
            # Database backup
            if backup.backup_type in ['full', 'database']:
                db_backup_path = os.path.join(temp_dir, 'database.sql')
                create_database_backup(db_backup_path)
                backup_files.append(db_backup_path)
            
            # Bestanden backup
            if backup.backup_type in ['full', 'files']:
                files_backup_path = os.path.join(temp_dir, 'media_files')
                create_files_backup(files_backup_path)
                backup_files.append(files_backup_path)
            
            # Maak ZIP bestand
            zip_path = create_backup_zip(backup_files, temp_dir, backup.name)
            
            # Sla backup op
            backup_dir = os.path.join(settings.MEDIA_ROOT, 'backups')
            os.makedirs(backup_dir, exist_ok=True)
            
            final_backup_path = os.path.join(backup_dir, f"{backup.name}_{backup_id}.zip")
            
            # Verplaats ZIP naar definitieve locatie
            import shutil
            shutil.move(zip_path, final_backup_path)
            
            # Update backup record
            backup.file_path = final_backup_path
            backup.file_size = os.path.getsize(final_backup_path)
            backup.status = 'completed'
            backup.completed_at = timezone.now()
            backup.save()
            
            logger.info(f"Backup {backup.name} completed successfully")
            
    except Exception as e:
        logger.error(f"Backup {backup_id} failed: {str(e)}")
        try:
            backup = Backup.objects.get(id=backup_id)
            backup.status = 'failed'
            backup.error_message = str(e)
            backup.save()
        except:
            pass
        raise e


def create_database_backup(output_path):
    """Maak database backup."""
    db_settings = settings.DATABASES['default']
    
    if db_settings['ENGINE'] == 'django.db.backends.postgresql':
        # PostgreSQL backup
        cmd = [
            'pg_dump',
            '-h', db_settings['HOST'],
            '-p', str(db_settings['PORT']),
            '-U', db_settings['USER'],
            '-d', db_settings['NAME'],
            '-f', output_path
        ]
        
        # Set password via environment variable
        env = os.environ.copy()
        if db_settings['PASSWORD']:
            env['PGPASSWORD'] = db_settings['PASSWORD']
        
        subprocess.run(cmd, env=env, check=True)
        
    else:
        # SQLite backup
        db_path = db_settings['NAME']
        import shutil
        shutil.copy2(db_path, output_path)


def create_files_backup(output_path):
    """Maak backup van media bestanden."""
    media_root = settings.MEDIA_ROOT
    
    if os.path.exists(media_root):
        import shutil
        shutil.copytree(media_root, output_path)
    else:
        # Maak lege directory als media root niet bestaat
        os.makedirs(output_path, exist_ok=True)


def create_backup_zip(backup_files, temp_dir, backup_name):
    """Maak ZIP bestand van backup bestanden."""
    zip_path = os.path.join(temp_dir, f"{backup_name}.zip")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path in backup_files:
            if os.path.isfile(file_path):
                # Voeg bestand toe
                arcname = os.path.basename(file_path)
                zipf.write(file_path, arcname)
            elif os.path.isdir(file_path):
                # Voeg directory toe
                for root, dirs, files in os.walk(file_path):
                    for file in files:
                        file_path_full = os.path.join(root, file)
                        arcname = os.path.relpath(file_path_full, temp_dir)
                        zipf.write(file_path_full, arcname)
    
    return zip_path


@shared_task
def cleanup_old_backups():
    """Verwijder oude backups (ouder dan 30 dagen)."""
    from datetime import timedelta
    
    cutoff_date = timezone.now() - timedelta(days=30)
    old_backups = Backup.objects.filter(created_at__lt=cutoff_date)
    
    deleted_count = 0
    for backup in old_backups:
        # Verwijder bestand
        if backup.file_path and os.path.exists(backup.file_path):
            try:
                os.remove(backup.file_path)
            except Exception as e:
                logger.error(f"Error deleting backup file {backup.file_path}: {e}")
        
        # Verwijder record
        backup.delete()
        deleted_count += 1
    
    logger.info(f"Cleaned up {deleted_count} old backups")
    return deleted_count
