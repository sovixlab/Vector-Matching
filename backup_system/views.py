from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse, FileResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
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