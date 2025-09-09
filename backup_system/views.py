from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse, FileResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import django
import os
import zipfile
import tempfile
import subprocess
import json
from datetime import datetime, timedelta
from .models import Backup
# from .tasks import create_backup_task  # Celery not installed yet
import logging

logger = logging.getLogger(__name__)


def create_backup_sync(backup):
    """Maak een backup synchronously."""
    try:
        # Maak tijdelijke directory voor backup
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_files = []
            
            # Database backup
            if backup.backup_type in ['full', 'database']:
                db_backup_path = os.path.join(temp_dir, 'database.sql')
                create_database_backup(db_backup_path)
                backup_files.append(db_backup_path)
            
            # Schema backup (alleen structuur)
            if backup.backup_type in ['full', 'schema']:
                schema_backup_path = os.path.join(temp_dir, 'database_schema.sql')
                create_schema_backup(schema_backup_path)
                backup_files.append(schema_backup_path)
            
            # Configuratie backup
            if backup.backup_type in ['full', 'config']:
                config_backup_path = os.path.join(temp_dir, 'system_config')
                create_config_backup(config_backup_path)
                backup_files.append(config_backup_path)
            
            # Maak ZIP bestand
            zip_path = create_backup_zip(backup_files, temp_dir, backup.name)
            
            # Sla backup op
            backup_dir = os.path.join(settings.MEDIA_ROOT, 'backups')
            os.makedirs(backup_dir, exist_ok=True)
            
            final_backup_path = os.path.join(backup_dir, f"{backup.name}_{backup.id}.zip")
            
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
        logger.error(f"Backup {backup.id} failed: {str(e)}")
        backup.status = 'failed'
        backup.error_message = str(e)
        backup.save()
        raise e


def create_database_backup(output_path):
    """Maak volledige database backup (data + structuur)."""
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
        logger.info(f"PostgreSQL database backup created: {output_path}")
        
    else:
        # SQLite backup
        db_path = db_settings['NAME']
        import shutil
        shutil.copy2(db_path, output_path)
        logger.info(f"SQLite database backup created: {output_path}")


def create_schema_backup(output_path):
    """Maak database schema backup (alleen structuur, geen data)."""
    db_settings = settings.DATABASES['default']
    
    if db_settings['ENGINE'] == 'django.db.backends.postgresql':
        # PostgreSQL schema backup
        cmd = [
            'pg_dump',
            '-h', db_settings['HOST'],
            '-p', str(db_settings['PORT']),
            '-U', db_settings['USER'],
            '-d', db_settings['NAME'],
            '--schema-only',  # Alleen structuur
            '-f', output_path
        ]
        
        # Set password via environment variable
        env = os.environ.copy()
        if db_settings['PASSWORD']:
            env['PGPASSWORD'] = db_settings['PASSWORD']
        
        subprocess.run(cmd, env=env, check=True)
        logger.info(f"PostgreSQL schema backup created: {output_path}")
        
    else:
        # Voor SQLite, maak een lege database met alleen de structuur
        from django.core.management import call_command
        from io import StringIO
        
        # Export Django models naar SQL
        output = StringIO()
        call_command('sqlmigrate', 'vector_matching_app', '0001', stdout=output)
        call_command('sqlmigrate', 'backup_system', '0001', stdout=output)
        
        with open(output_path, 'w') as f:
            f.write(output.getvalue())
        
        logger.info(f"SQLite schema backup created: {output_path}")


def create_config_backup(output_path):
    """Maak systeem configuratie backup."""
    os.makedirs(output_path, exist_ok=True)
    
    # Django settings
    settings_file = os.path.join(output_path, 'settings.py')
    with open(settings_file, 'w') as f:
        f.write("# Django Settings Backup\n")
        f.write(f"# Generated on: {timezone.now()}\n\n")
        f.write(f"DEBUG = {settings.DEBUG}\n")
        f.write(f"SECRET_KEY = '{settings.SECRET_KEY}'\n")
        f.write(f"ALLOWED_HOSTS = {settings.ALLOWED_HOSTS}\n")
        f.write(f"DATABASE_ENGINE = '{settings.DATABASES['default']['ENGINE']}'\n")
        f.write(f"DATABASE_NAME = '{settings.DATABASES['default']['NAME']}'\n")
        f.write(f"MEDIA_ROOT = '{settings.MEDIA_ROOT}'\n")
        f.write(f"STATIC_ROOT = '{settings.STATIC_ROOT}'\n")
    
    # Requirements
    requirements_file = os.path.join(output_path, 'requirements.txt')
    try:
        import subprocess
        result = subprocess.run(['pip', 'freeze'], capture_output=True, text=True)
        with open(requirements_file, 'w') as f:
            f.write(result.stdout)
    except Exception as e:
        logger.warning(f"Could not create requirements.txt: {e}")
        with open(requirements_file, 'w') as f:
            f.write("# Requirements could not be generated\n")
    
    # Django migrations
    migrations_dir = os.path.join(output_path, 'migrations')
    os.makedirs(migrations_dir, exist_ok=True)
    
    try:
        # Kopieer migration bestanden
        import shutil
        for app in ['vector_matching_app', 'backup_system']:
            app_migrations = os.path.join(settings.BASE_DIR, app, 'migrations')
            if os.path.exists(app_migrations):
                dest_dir = os.path.join(migrations_dir, app)
                shutil.copytree(app_migrations, dest_dir)
    except Exception as e:
        logger.warning(f"Could not copy migrations: {e}")
    
    # Environment info
    env_file = os.path.join(output_path, 'environment.txt')
    with open(env_file, 'w') as f:
        f.write(f"Python Version: {os.sys.version}\n")
        f.write(f"Django Version: {django.get_version()}\n")
        f.write(f"Backup Created: {timezone.now()}\n")
        f.write(f"Server: {os.environ.get('HOSTNAME', 'Unknown')}\n")
    
    logger.info(f"System configuration backup created: {output_path}")


def create_files_backup_from_database(output_path):
    """Maak backup van bestanden direct via database."""
    try:
        from vector_matching_app.models import Candidate
        candidates = Candidate.objects.exclude(cv_pdf='')
        
        if not candidates.exists():
            logger.info("No candidates with CV files found in database")
            return False
        
        logger.info(f"Found {candidates.count()} candidates with CV files in database")
        
        # Maak directory structuur
        os.makedirs(output_path, exist_ok=True)
        cv_dir = os.path.join(output_path, 'cv_files')
        os.makedirs(cv_dir, exist_ok=True)
        
        # Kopieer bestanden
        copied_count = 0
        for candidate in candidates:
            if candidate.cv_pdf:
                try:
                    # Gebruik Django's file handling
                    if hasattr(candidate.cv_pdf, 'path'):
                        source_path = candidate.cv_pdf.path
                    else:
                        # Probeer via URL
                        source_path = os.path.join(settings.MEDIA_ROOT, str(candidate.cv_pdf))
                    
                    if os.path.exists(source_path):
                        filename = os.path.basename(source_path)
                        # Voeg candidate ID toe aan filename voor uniekheid
                        name, ext = os.path.splitext(filename)
                        filename = f"{candidate.id}_{name}{ext}"
                        dest_path = os.path.join(cv_dir, filename)
                        
                        import shutil
                        shutil.copy2(source_path, dest_path)
                        copied_count += 1
                        logger.info(f"Copied CV: {filename} (candidate {candidate.id})")
                    else:
                        logger.warning(f"CV file not found for candidate {candidate.id}: {source_path}")
                except Exception as e:
                    logger.error(f"Error copying CV for candidate {candidate.id}: {e}")
        
        logger.info(f"Successfully copied {copied_count} CV files from database")
        return copied_count > 0
        
    except Exception as e:
        logger.error(f"Error in create_files_backup_from_database: {e}")
        return False


def create_files_backup(output_path):
    """Maak backup van media bestanden."""
    media_root = settings.MEDIA_ROOT
    
    logger.info(f"Creating files backup from: {media_root}")
    logger.info(f"Media root exists: {os.path.exists(media_root)}")
    
    # Maak media directory aan als deze niet bestaat
    if not os.path.exists(media_root):
        logger.info(f"Creating media directory: {media_root}")
        os.makedirs(media_root, exist_ok=True)
    
    # Zoek naar bestaande bestanden in verschillende locaties
    possible_media_paths = [
        media_root,
        os.path.join(settings.BASE_DIR, 'media'),
        '/opt/render/project/src/media',
        '/app/media',
        os.path.join(os.path.dirname(settings.BASE_DIR), 'media')
    ]
    
    actual_media_path = None
    for path in possible_media_paths:
        if os.path.exists(path):
            logger.info(f"Found media directory at: {path}")
            # Controleer of er bestanden in staan
            has_files = False
            for root, dirs, files in os.walk(path):
                if files:
                    has_files = True
                    break
            if has_files:
                actual_media_path = path
                break
    
    if actual_media_path:
        logger.info(f"Using media directory: {actual_media_path}")
        # Debug: toon wat er in de media directory staat
        logger.info("Contents of media directory:")
        for root, dirs, files in os.walk(actual_media_path):
            level = root.replace(actual_media_path, '').count(os.sep)
            indent = ' ' * 2 * level
            logger.info(f"{indent}{os.path.basename(root)}/")
            subindent = ' ' * 2 * (level + 1)
            for file in files:
                logger.info(f"{subindent}{file}")
        
        import shutil
        try:
            # Kopieer de hele media directory
            shutil.copytree(actual_media_path, output_path)
            logger.info(f"Successfully copied media files to: {output_path}")
            
            # Log wat er gekopieerd is
            logger.info("Contents of copied backup directory:")
            for root, dirs, files in os.walk(output_path):
                level = root.replace(output_path, '').count(os.sep)
                indent = ' ' * 2 * level
                logger.info(f"{indent}{os.path.basename(root)}/")
                subindent = ' ' * 2 * (level + 1)
                for file in files:
                    file_path = os.path.join(root, file)
                    file_size = os.path.getsize(file_path)
                    logger.info(f"{subindent}{file} ({file_size} bytes)")
        except Exception as e:
            logger.error(f"Error copying media files: {e}")
            # Maak lege directory als kopiëren mislukt
            os.makedirs(output_path, exist_ok=True)
    else:
        logger.warning("No media directory with files found")
        
        # Probeer bestanden te vinden via de database
        try:
            from vector_matching_app.models import Candidate
            candidates = Candidate.objects.exclude(cv_pdf='')
            if candidates.exists():
                logger.info(f"Found {candidates.count()} candidates with CV files in database")
                
                # Maak directory structuur
                os.makedirs(output_path, exist_ok=True)
                cv_dir = os.path.join(output_path, 'cv_files')
                os.makedirs(cv_dir, exist_ok=True)
                
                # Kopieer bestanden
                copied_count = 0
                for candidate in candidates:
                    if candidate.cv_pdf and hasattr(candidate.cv_pdf, 'path'):
                        try:
                            source_path = candidate.cv_pdf.path
                            if os.path.exists(source_path):
                                filename = os.path.basename(source_path)
                                dest_path = os.path.join(cv_dir, filename)
                                import shutil
                                shutil.copy2(source_path, dest_path)
                                copied_count += 1
                                logger.info(f"Copied CV: {filename}")
                        except Exception as e:
                            logger.error(f"Error copying CV for candidate {candidate.id}: {e}")
                
                logger.info(f"Successfully copied {copied_count} CV files")
            else:
                logger.info("No candidates with CV files found in database")
        except Exception as e:
            logger.error(f"Error searching for CV files in database: {e}")
        
        # Maak lege directory als media root niet bestaat
        os.makedirs(output_path, exist_ok=True)


def create_backup_zip(backup_files, temp_dir, backup_name):
    """Maak ZIP bestand van backup bestanden."""
    zip_path = os.path.join(temp_dir, f"{backup_name}.zip")
    
    logger.info(f"Creating ZIP file: {zip_path}")
    logger.info(f"Backup files to include: {backup_files}")
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path in backup_files:
            logger.info(f"Processing backup file: {file_path}")
            if os.path.isfile(file_path):
                # Voeg bestand toe
                arcname = os.path.basename(file_path)
                zipf.write(file_path, arcname)
                logger.info(f"Added file to ZIP: {arcname}")
            elif os.path.isdir(file_path):
                # Voeg directory toe
                logger.info(f"Adding directory to ZIP: {file_path}")
                file_count = 0
                for root, dirs, files in os.walk(file_path):
                    for file in files:
                        file_path_full = os.path.join(root, file)
                        arcname = os.path.relpath(file_path_full, temp_dir)
                        zipf.write(file_path_full, arcname)
                        file_count += 1
                        logger.info(f"Added file to ZIP: {arcname}")
                logger.info(f"Total files added from directory: {file_count}")
            else:
                logger.warning(f"Backup file does not exist: {file_path}")
    
    logger.info(f"ZIP file created successfully: {zip_path}")
    return zip_path


@login_required
def backup_list_view(request):
    """Overzicht van alle backups."""
    backups = Backup.objects.all()
    
    # Filter opties
    backup_type = request.GET.get('type', '')
    status = request.GET.get('status', '')
    
    if backup_type:
        backups = backups.filter(backup_type=backup_type)
    if status:
        backups = backups.filter(status=status)
    
    context = {
        'backups': backups,
        'backup_types': Backup.BACKUP_TYPES,
        'status_choices': Backup.STATUS_CHOICES,
        'current_type': backup_type,
        'current_status': status,
    }
    return render(request, 'backup_system/backup_list.html', context)


@login_required
def backup_detail_view(request, pk):
    """Detail weergave van een backup."""
    backup = get_object_or_404(Backup, pk=pk)
    
    context = {
        'backup': backup,
    }
    return render(request, 'backup_system/backup_detail.html', context)


@login_required
@require_http_methods(["POST"])
def create_backup_view(request):
    """Maak een nieuwe backup aan."""
    backup_type = request.POST.get('backup_type', 'full')
    name = request.POST.get('name', '')
    notes = request.POST.get('notes', '')
    
    if not name:
        name = f"Backup {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    
    # Maak backup record aan
    backup = Backup.objects.create(
        name=name,
        backup_type=backup_type,
        created_by=request.user,
        notes=notes,
        status='pending'
    )
    
    # Start backup taak (synchronous for now)
    try:
        backup.status = 'running'
        backup.save()
        
        # Maak echte backup
        create_backup_sync(backup)
        
        messages.success(request, f'Backup "{name}" is succesvol gemaakt!')
    except Exception as e:
        backup.status = 'failed'
        backup.error_message = str(e)
        backup.save()
        messages.error(request, f'Fout bij maken backup: {str(e)}')
    
    return redirect('backup_system:backup_list')


@login_required
def download_backup_view(request, pk):
    """Download een backup bestand."""
    backup = get_object_or_404(Backup, pk=pk)
    
    if not backup.is_completed or not backup.file_path:
        messages.error(request, 'Backup is niet beschikbaar voor download.')
        return redirect('backup_system:backup_detail', pk=pk)
    
    if not os.path.exists(backup.file_path):
        messages.error(request, 'Backup bestand niet gevonden.')
        return redirect('backup_system:backup_detail', pk=pk)
    
    # Serveer bestand
    response = FileResponse(
        open(backup.file_path, 'rb'),
        content_type='application/zip'
    )
    response['Content-Disposition'] = f'attachment; filename="{backup.name}.zip"'
    return response


@login_required
@require_http_methods(["POST"])
def delete_backup_view(request, pk):
    """Verwijder een backup."""
    backup = get_object_or_404(Backup, pk=pk)
    
    # Verwijder bestand als het bestaat
    if backup.file_path and os.path.exists(backup.file_path):
        try:
            os.remove(backup.file_path)
        except Exception as e:
            logger.error(f"Fout bij verwijderen backup bestand: {e}")
    
    backup.delete()
    messages.success(request, f'Backup "{backup.name}" is verwijderd.')
    
    return redirect('backup_system:backup_list')


@login_required
def backup_status_view(request, pk):
    """AJAX endpoint voor backup status."""
    backup = get_object_or_404(Backup, pk=pk)
    
    return JsonResponse({
        'status': backup.status,
        'progress': backup.get_status_display(),
        'file_size_mb': backup.file_size_mb,
        'completed_at': backup.completed_at.isoformat() if backup.completed_at else None,
        'error_message': backup.error_message,
    })


@login_required
def restore_backup_view(request, pk):
    """Herstel een backup (alleen voor superusers)."""
    if not request.user.is_superuser:
        messages.error(request, 'Alleen superusers kunnen backups herstellen.')
        return redirect('backup_system:backup_list')
    
    backup = get_object_or_404(Backup, pk=pk)
    
    if not backup.is_completed or not backup.file_path:
        messages.error(request, 'Backup is niet beschikbaar voor herstel.')
        return redirect('backup_system:backup_detail', pk=pk)
    
    if not os.path.exists(backup.file_path):
        messages.error(request, 'Backup bestand niet gevonden.')
        return redirect('backup_system:backup_detail', pk=pk)
    
    # TODO: Implementeer restore functionaliteit
    messages.warning(request, 'Restore functionaliteit wordt nog geïmplementeerd.')
    
    return redirect('backup_system:backup_detail', pk=pk)


@login_required
def backup_stats_view(request):
    """Statistieken over backups."""
    total_backups = Backup.objects.count()
    completed_backups = Backup.objects.filter(status='completed').count()
    failed_backups = Backup.objects.filter(status='failed').count()
    
    # Recente backups (laatste 7 dagen)
    week_ago = timezone.now() - timedelta(days=7)
    recent_backups = Backup.objects.filter(created_at__gte=week_ago).count()
    
    # Totale opslag gebruikt
    total_size = sum(backup.file_size for backup in Backup.objects.filter(status='completed'))
    total_size_mb = round(total_size / (1024 * 1024), 2)
    
    context = {
        'total_backups': total_backups,
        'completed_backups': completed_backups,
        'failed_backups': failed_backups,
        'recent_backups': recent_backups,
        'total_size_mb': total_size_mb,
    }
    return render(request, 'backup_system/backup_stats.html', context)