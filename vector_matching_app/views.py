from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.db import connection
from django.conf import settings
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .models import Candidate
from .tasks import process_candidate_pipeline, reprocess_candidate
import json
import os
import logging

logger = logging.getLogger(__name__)


def index(request):
    """Homepage met DaisyUI hero component."""
    return render(request, 'index.html')


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
        for i, file in enumerate(files):
            try:
                # Maak kandidaat aan
                candidate = Candidate.objects.create(
                    name=os.path.splitext(file.name)[0],  # Bestandsnaam zonder extensie
                    cv_pdf=file,
                    embed_status='queued'
                )
                created_candidates.append(candidate)
                
                # Verwerk één voor één met korte pauze
                try:
                    logger.info(f"Verwerking gestart voor {file.name} ({i+1}/{len(files)})")
                    process_candidate_pipeline(candidate.id)
                    logger.info(f"Verwerking voltooid voor {file.name}")
                    
                    # Korte pauze tussen bestanden (behalve de laatste)
                    if i < len(files) - 1:
                        import time
                        time.sleep(2)  # 2 seconden pauze
                        
                except Exception as e:
                    logger.error(f"Verwerking gefaald voor {file.name}: {str(e)}")
                    messages.error(request, f'Verwerking gefaald voor {file.name}: {str(e)}')
                    
            except Exception as e:
                logger.error(f"Fout bij uploaden van {file.name}: {str(e)}")
                messages.error(request, f'Fout bij uploaden van {file.name}: {str(e)}')
        
        if created_candidates:
            messages.success(request, f'{len(created_candidates)} CV(s) succesvol geüpload en verwerkt!')
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
