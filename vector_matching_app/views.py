from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.db import connection
from django.conf import settings
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .models import Candidate, Prompt, PromptLog
from .tasks import process_candidate_pipeline, reprocess_candidate
import json
import os
import logging

logger = logging.getLogger(__name__)


def index(request):
    """Dashboard met overzicht van kandidaten en systeem status."""
    # Haal statistieken op
    total_candidates = Candidate.objects.count()
    completed_candidates = Candidate.objects.filter(embed_status='completed').count()
    queued_candidates = Candidate.objects.filter(embed_status='queued').count()
    failed_candidates = Candidate.objects.filter(embed_status='failed').count()
    
    # Haal recente kandidaten op (laatste 10)
    recent_candidates = Candidate.objects.order_by('-updated_at')[:10]
    
    context = {
        'total_candidates': total_candidates,
        'completed_candidates': completed_candidates,
        'queued_candidates': queued_candidates,
        'failed_candidates': failed_candidates,
        'recent_candidates': recent_candidates,
    }
    
    return render(request, 'index.html', context)


def health_check(request):
    """Health check endpoint dat JSON status teruggeeft."""
    try:
        # Test database connectivity
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            db_status = "ok"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    # Test OpenAI API key availability
    try:
        openai_status = "ok" if settings.OPENAI_API_KEY else "missing"
    except Exception as e:
        openai_status = f"error: {str(e)}"
    
    response_data = {
        "status": "ok",
        "database": db_status,
        "openai": openai_status,
        "debug": settings.DEBUG,
    }
    
    return JsonResponse(response_data)


def kandidaten_list_view(request):
    """Weergave van alle kandidaten in een tabel."""
    candidates = Candidate.objects.all()
    return render(request, 'kandidaten.html', {'candidates': candidates})


@require_http_methods(["POST"])
def kandidaten_upload_view(request):
    """Verwerkt CV uploads voor kandidaten."""
    if request.method == 'POST':
        files = request.FILES.getlist('files')
        
        # Validatie
        if not files:
            messages.error(request, 'Geen bestanden geselecteerd.')
            return redirect('vector_matching_app:kandidaten')
        
        if len(files) > 100:
            messages.error(request, 'Maximaal 100 bestanden tegelijk toegestaan.')
            return redirect('vector_matching_app:kandidaten')
        
        # Controleer bestandstypen
        invalid_files = []
        for file in files:
            if not file.name.lower().endswith('.pdf'):
                invalid_files.append(file.name)
        
        if invalid_files:
            messages.error(request, f'Alleen PDF bestanden zijn toegestaan. Ongeldige bestanden: {", ".join(invalid_files)}')
            return redirect('vector_matching_app:kandidaten')
        
        # Verwerk bestanden één voor één, rustig aan
        created_candidates = []
        skipped_duplicates = []
        
        for i, file in enumerate(files):
            try:
                # Maak kandidaat aan met fallback waarden
                candidate = Candidate.objects.create(
                    name=os.path.splitext(file.name)[0] or 'Onbekend',  # Bestandsnaam zonder extensie
                    email='',  # Lege string in plaats van null
                    phone='',  # Lege string in plaats van null
                    street='',  # Lege string in plaats van null
                    house_number='',  # Lege string in plaats van null
                    postal_code='',  # Lege string in plaats van null
                    city='',  # Lege string in plaats van null
                    cv_pdf=file,
                    embed_status='queued'
                )
                
                # Verwerk één voor één met korte pauze
                try:
                    logger.info(f"Verwerking gestart voor {file.name} ({i+1}/{len(files)})")
                    process_candidate_pipeline(candidate.id)
                    
                    # Controleer of het een duplicaat was door de kandidaat opnieuw op te halen
                    candidate.refresh_from_db()
                    if candidate.embed_status == 'failed' and 'Duplicaat' in (candidate.error_message or ''):
                        # Verwijder de kandidaat als het een duplicaat was
                        candidate.delete()
                        skipped_duplicates.append(file.name)
                        logger.info(f"Duplicaat overgeslagen: {file.name}")
                    else:
                        created_candidates.append(candidate)
                        logger.info(f"Verwerking voltooid voor {file.name}")
                    
                    # Korte pauze tussen bestanden (behalve de laatste)
                    if i < len(files) - 1:
                        import time
                        time.sleep(2)  # 2 seconden pauze
                        
                except Exception as e:
                    logger.error(f"Verwerking gefaald voor {file.name}: {str(e)}")
                    messages.error(request, f'Verwerking gefaald voor {file.name}: {str(e)}')
                    # Voeg toe aan created_candidates ook bij fout, zodat het geteld wordt
                    created_candidates.append(candidate)
                    
            except Exception as e:
                logger.error(f"Fout bij uploaden van {file.name}: {str(e)}")
                messages.error(request, f'Fout bij uploaden van {file.name}: {str(e)}')
        
        if created_candidates:
            success_message = f'{len(created_candidates)} CV(s) succesvol geüpload en verwerkt!'
            if skipped_duplicates:
                success_message += f' {len(skipped_duplicates)} duplicaat(en) overgeslagen.'
            messages.success(request, success_message)
            
            # Redirect naar de eerste kandidaat detail pagina (als die bestaat)
            if len(created_candidates) == 1:
                return redirect('vector_matching_app:kandidaat_detail', candidate_id=created_candidates[0].id)
        
        return redirect('vector_matching_app:kandidaten')


def kandidaat_detail_view(request, candidate_id):
    """Detail weergave van een kandidaat."""
    try:
        candidate = Candidate.objects.get(id=candidate_id)
        return render(request, 'kandidaat_detail.html', {'candidate': candidate})
    except Candidate.DoesNotExist:
        messages.error(request, 'Kandidaat niet gevonden.')
        return redirect('vector_matching_app:kandidaten')


@require_http_methods(["POST"])
def kandidaat_reprocess_view(request, candidate_id):
    """Herstart de verwerkingspipeline voor een kandidaat."""
    try:
        candidate = Candidate.objects.get(id=candidate_id)
        
        # Start herverwerking (synchroon)
        try:
            reprocess_candidate(candidate_id)
            messages.success(request, f'Herverwerking voltooid voor {candidate.name or f"kandidaat {candidate_id}"}')
        except Exception as e:
            messages.error(request, f'Fout bij herverwerking: {str(e)}')
            
    except Candidate.DoesNotExist:
        messages.error(request, 'Kandidaat niet gevonden.')
    
    return redirect('vector_matching_app:kandidaat_detail', candidate_id=candidate_id)


def kandidaat_cv_view(request, candidate_id):
    """Serveer het CV bestand van een kandidaat."""
    try:
        candidate = get_object_or_404(Candidate, id=candidate_id)
        
        if not candidate.cv_pdf:
            return HttpResponse('Geen CV bestand gevonden.', status=404)
        
        # Controleer of het bestand bestaat
        if not candidate.cv_pdf.storage.exists(candidate.cv_pdf.name):
            return HttpResponse('CV bestand niet gevonden op server.', status=404)
        
        # Serveer het bestand
        try:
            file_content = candidate.cv_pdf.read()
            response = HttpResponse(file_content, content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="{candidate.cv_pdf.name.split("/")[-1]}"'
            response['Content-Length'] = len(file_content)
            return response
        except Exception as e:
            return HttpResponse(f'Fout bij lezen van CV bestand: {str(e)}', status=500)
        
    except Exception as e:
        return HttpResponse(f'Fout bij het openen van CV: {str(e)}', status=500)


@require_http_methods(["POST"])
def kandidaat_delete_view(request, candidate_id):
    """Verwijder een kandidaat."""
    try:
        candidate = get_object_or_404(Candidate, id=candidate_id)
        candidate_name = candidate.name or f"kandidaat {candidate_id}"
        
        # Verwijder het CV bestand
        if candidate.cv_pdf:
            try:
                os.remove(candidate.cv_pdf.path)
            except (OSError, ValueError):
                pass  # Bestand bestaat niet of kan niet worden verwijderd
        
        candidate.delete()
        messages.success(request, f'{candidate_name} is verwijderd.')
        
    except Exception as e:
        messages.error(request, f'Fout bij verwijderen: {str(e)}')
    
    return redirect('vector_matching_app:kandidaten')


def kandidaat_edit_view(request, candidate_id):
    """Bewerk een kandidaat."""
    candidate = get_object_or_404(Candidate, id=candidate_id)
    
    if request.method == 'POST':
        try:
            # Update de kandidaat velden
            candidate.name = request.POST.get('name', candidate.name)
            candidate.email = request.POST.get('email', candidate.email)
            candidate.phone = request.POST.get('phone', candidate.phone)
            candidate.street = request.POST.get('street', candidate.street)
            candidate.house_number = request.POST.get('house_number', candidate.house_number)
            candidate.postal_code = request.POST.get('postal_code', candidate.postal_code)
            candidate.city = request.POST.get('city', candidate.city)
            candidate.education_level = request.POST.get('education_level', candidate.education_level)
            
            # Parse jaren ervaring
            years_exp = request.POST.get('years_experience', '')
            if years_exp.isdigit():
                candidate.years_experience = int(years_exp)
            else:
                candidate.years_experience = None
            
            # Parse job titles (comma separated)
            job_titles = request.POST.get('job_titles', '')
            if job_titles:
                candidate.job_titles = [title.strip() for title in job_titles.split(',') if title.strip()]
            else:
                candidate.job_titles = []
            
            candidate.save()
            messages.success(request, f'{candidate.name or "Kandidaat"} is bijgewerkt.')
            
            return redirect('vector_matching_app:kandidaat_detail', candidate_id=candidate_id)
            
        except Exception as e:
            messages.error(request, f'Fout bij bijwerken: {str(e)}')
    
    return render(request, 'kandidaat_edit.html', {'candidate': candidate})


@require_http_methods(["POST"])
def kandidaten_bulk_delete_view(request):
    """Verwijder meerdere kandidaten tegelijk."""
    try:
        candidate_ids = request.POST.getlist('candidate_ids')
        
        if not candidate_ids:
            messages.warning(request, 'Geen kandidaten geselecteerd.')
            return redirect('vector_matching_app:kandidaten')
        
        # Verwijder de geselecteerde kandidaten
        deleted_count = 0
        for candidate_id in candidate_ids:
            try:
                candidate = Candidate.objects.get(id=candidate_id)
                
                # Verwijder het CV bestand
                if candidate.cv_pdf:
                    try:
                        os.remove(candidate.cv_pdf.path)
                    except (OSError, ValueError):
                        pass  # Bestand bestaat niet of kan niet worden verwijderd
                
                candidate.delete()
                deleted_count += 1
                
            except Candidate.DoesNotExist:
                continue  # Kandidaat bestaat niet meer
        
        if deleted_count > 0:
            messages.success(request, f'{deleted_count} kandidaat(en) succesvol verwijderd.')
        else:
            messages.warning(request, 'Geen kandidaten konden worden verwijderd.')
            
    except Exception as e:
        messages.error(request, f'Fout bij bulk verwijderen: {str(e)}')
    
    return redirect('vector_matching_app:kandidaten')


# Prompt Management Views
def prompts_list_view(request):
    """Overzicht van alle prompts."""
    prompts = Prompt.objects.all().order_by('name', '-version')
    return render(request, 'prompts.html', {'prompts': prompts})


def prompt_detail_view(request, prompt_id):
    """Detail weergave van een prompt met versiegeschiedenis."""
    prompt = get_object_or_404(Prompt, id=prompt_id)
    versions = prompt.all_versions
    logs = PromptLog.objects.filter(prompt__in=versions).order_by('-timestamp')[:20]
    
    context = {
        'prompt': prompt,
        'versions': versions,
        'logs': logs,
    }
    return render(request, 'prompt_detail.html', context)


def prompt_edit_view(request, prompt_id):
    """Bewerk een prompt."""
    prompt = get_object_or_404(Prompt, id=prompt_id)
    
    if request.method == 'POST':
        new_content = request.POST.get('content', '').strip()
        notes = request.POST.get('notes', '').strip()
        
        if new_content and new_content != prompt.content:
            # Maak nieuwe versie
            old_content = prompt.content
            new_version = prompt.create_new_version(new_content, request.user)
            
            # Log de wijziging
            PromptLog.objects.create(
                prompt=new_version,
                action='updated',
                old_content=old_content,
                new_content=new_content,
                user=request.user,
                notes=notes
            )
            
            messages.success(request, f'Nieuwe versie {new_version.version} van "{prompt.name}" is aangemaakt.')
            return redirect('vector_matching_app:prompt_detail', prompt_id=new_version.id)
        else:
            messages.warning(request, 'Geen wijzigingen gedetecteerd.')
    
    return render(request, 'prompt_edit.html', {'prompt': prompt})


def prompt_create_view(request):
    """Maak een nieuwe prompt aan."""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        prompt_type = request.POST.get('prompt_type', 'custom')
        content = request.POST.get('content', '').strip()
        
        if name and content:
            try:
                prompt = Prompt.objects.create(
                    name=name,
                    prompt_type=prompt_type,
                    content=content,
                    created_by=request.user
                )
                
                # Log de creatie
                PromptLog.objects.create(
                    prompt=prompt,
                    action='created',
                    new_content=content,
                    user=request.user
                )
                
                messages.success(request, f'Prompt "{name}" is aangemaakt.')
                return redirect('vector_matching_app:prompt_detail', prompt_id=prompt.id)
            except Exception as e:
                messages.error(request, f'Fout bij aanmaken prompt: {str(e)}')
        else:
            messages.error(request, 'Naam en inhoud zijn verplicht.')
    
    return render(request, 'prompt_create.html')


def prompt_activate_view(request, prompt_id):
    """Activeer een specifieke versie van een prompt."""
    prompt = get_object_or_404(Prompt, id=prompt_id)
    
    if request.method == 'POST':
        # Deactiveer alle andere versies van dezelfde prompt
        Prompt.objects.filter(name=prompt.name).update(is_active=False)
        
        # Activeer deze versie
        prompt.is_active = True
        prompt.save()
        
        # Log de activatie
        PromptLog.objects.create(
            prompt=prompt,
            action='activated',
            user=request.user,
            notes=f'Versie {prompt.version} geactiveerd'
        )
        
        messages.success(request, f'Versie {prompt.version} van "{prompt.name}" is geactiveerd.')
    
    return redirect('vector_matching_app:prompt_detail', prompt_id=prompt.id)


def prompt_logs_view(request):
    """Overzicht van alle prompt logs."""
    logs = PromptLog.objects.all().order_by('-timestamp')[:100]
    return render(request, 'prompt_logs.html', {'logs': logs})
