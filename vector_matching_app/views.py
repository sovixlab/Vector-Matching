from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.db import connection
from django.conf import settings
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .models import Candidate
from .tasks import process_candidate_pipeline, reprocess_candidate
import json
import os


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
    openai_status = "ok" if settings.OPENAI_API_KEY else "missing"
    
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
        
        # Verwerk bestanden
        created_candidates = []
        for file in files:
            try:
                candidate = Candidate.objects.create(
                    name=os.path.splitext(file.name)[0],  # Bestandsnaam zonder extensie
                    cv_pdf=file,
                    embed_status='queued'
                )
                created_candidates.append(candidate)
                
                # Start verwerkingspipeline
                try:
                    process_candidate_pipeline.delay(candidate.id)
                    messages.info(request, f'Verwerking gestart voor {file.name}')
                except Exception as e:
                    messages.warning(request, f'Verwerking kon niet gestart worden voor {file.name}: {str(e)}')
                    
            except Exception as e:
                messages.error(request, f'Fout bij uploaden van {file.name}: {str(e)}')
        
        if created_candidates:
            messages.success(request, f'{len(created_candidates)} CV(s) succesvol geüpload!')
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
        
        # Start herverwerking
        try:
            reprocess_candidate.delay(candidate_id)
            messages.success(request, f'Herverwerking gestart voor {candidate.name or f"kandidaat {candidate_id}"}')
        except Exception as e:
            messages.error(request, f'Fout bij starten herverwerking: {str(e)}')
            
    except Candidate.DoesNotExist:
        messages.error(request, 'Kandidaat niet gevonden.')
    
    return redirect('vector_matching_app:kandidaat_detail', candidate_id=candidate_id)
