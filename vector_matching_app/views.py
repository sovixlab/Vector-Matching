from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.db import connection, models
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .models import Candidate, Prompt, PromptLog, Vacature
from .tasks import process_candidate_pipeline, reprocess_candidate
import json
import os
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

logger = logging.getLogger(__name__)


@login_required
def index(request):
    """Dashboard met overzicht van kandidaten en systeem status."""
    from datetime import datetime, timedelta
    
    # Haal statistieken op
    total_candidates = Candidate.objects.count()
    total_vacatures = Vacature.objects.filter(actief=True).count()
    
    # Fictieve matches (voor later implementatie)
    total_matches = 0  # TODO: Implementeer echte match logica
    
    # Laatste match update (fictief voor nu)
    last_match_update = datetime.now() - timedelta(hours=2)  # TODO: Implementeer echte match tracking
    
    # Haal recente kandidaten op (laatste 10)
    recent_candidates = Candidate.objects.order_by('-updated_at')[:10]
    
    # Health check data
    health_status = {
        'database': True,  # Als we hier zijn, werkt de database
        'openai': True,    # TODO: Echte check implementeren
        'system': True,    # TODO: Echte check implementeren
    }
    
    context = {
        'total_candidates': total_candidates,
        'total_vacatures': total_vacatures,
        'total_matches': total_matches,
        'last_match_update': last_match_update,
        'recent_candidates': recent_candidates,
        'health_status': health_status,
    }
    
    return render(request, 'index.html', context)


# Health check heeft geen login vereist voor monitoring
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


@login_required
def kandidaten_list_view(request):
    """Weergave van alle kandidaten in een tabel."""
    candidates = Candidate.objects.all()
    total_count = candidates.count()
    return render(request, 'kandidaten.html', {
        'candidates': candidates,
        'total_count': total_count
    })


@login_required
@require_http_methods(["POST"])
def kandidaten_upload_view(request):
    """Verwerkt CV uploads voor kandidaten."""
    if request.method == 'POST':
        files = request.FILES.getlist('files')
        
        # Validatie
        if not files:
            return JsonResponse({
                'success': False,
                'error': 'Geen bestanden geselecteerd.'
            })
        
        if len(files) > 100:
            return JsonResponse({
                'success': False,
                'error': 'Maximaal 100 bestanden tegelijk toegestaan.'
            })
        
        # Controleer bestandstypen
        invalid_files = []
        for file in files:
            if not file.name.lower().endswith('.pdf'):
                invalid_files.append(file.name)
        
        if invalid_files:
            return JsonResponse({
                'success': False,
                'error': f'Alleen PDF bestanden zijn toegestaan. Ongeldige bestanden: {", ".join(invalid_files)}'
            })
        
        # Verwerk bestanden één voor één
        created_candidates = []
        skipped_duplicates = []
        processing_errors = []
        
        try:
            for i, file in enumerate(files):
                try:
                    # Eerst PDF tekst extraheren om duplicaten te kunnen detecteren
                    logger.info(f"PDF tekst extraheren voor {file.name} ({i+1}/{len(files)})")
                    
                    # Tijdelijke kandidaat voor PDF verwerking
                    temp_candidate = Candidate.objects.create(
                        name=os.path.splitext(file.name)[0] or 'Onbekend',
                        email='',
                        phone='',
                        street='',
                        house_number='',
                        postal_code='',
                        city='',
                        cv_pdf=file,
                        embed_status='processing'
                    )
                    
                    # Extraheer PDF tekst
                    try:
                        from .tasks import extract_pdf_text
                        extract_pdf_text(temp_candidate.id)
                        temp_candidate.refresh_from_db()
                        
                        if not temp_candidate.cv_text:
                            raise ValueError("Geen tekst gevonden in PDF")
                            
                    except Exception as e:
                        logger.error(f"PDF extractie gefaald voor {file.name}: {str(e)}")
                        temp_candidate.delete()
                        processing_errors.append(f'{file.name}: PDF extractie gefaald - {str(e)}')
                        continue
                    
                    # Parse CV data
                    try:
                        from .tasks import parse_cv_to_fields
                        parse_cv_to_fields(temp_candidate.id)
                        temp_candidate.refresh_from_db()
                        
                        # Check of het een duplicaat is
                        if temp_candidate.embed_status == 'failed' and 'Duplicaat' in (temp_candidate.error_message or ''):
                            # Verwijder duplicaat
                            candidate_name = temp_candidate.name or file.name
                            temp_candidate.delete()
                            skipped_duplicates.append(f"{candidate_name} (duplicaat)")
                            logger.info(f"Duplicaat overgeslagen: {file.name} - {temp_candidate.error_message}")
                            continue
                            
                    except Exception as e:
                        logger.error(f"CV parsing gefaald voor {file.name}: {str(e)}")
                        temp_candidate.delete()
                        processing_errors.append(f'{file.name}: CV parsing gefaald - {str(e)}')
                        continue
                    
                    # Als we hier zijn, is het geen duplicaat - zet status terug naar queued
                    temp_candidate.embed_status = 'queued'
                    temp_candidate.save(update_fields=['embed_status'])
                    candidate = temp_candidate
                    
                    # Verwerk de rest van de pipeline (embedding generatie)
                    try:
                        logger.info(f"Embedding generatie gestart voor {file.name} ({i+1}/{len(files)})")
                        from .tasks import generate_profile_summary_text, embed_profile_text
                        
                        # Genereer profiel samenvatting
                        generate_profile_summary_text(candidate.id)
                        candidate.refresh_from_db()
                        
                        # Genereer embedding
                        embed_profile_text(candidate.id)
                        candidate.refresh_from_db()
                        
                        # Pauze tussen bestanden om server niet te overbelasten
                        if i < len(files) - 1:  # Niet na het laatste bestand
                            import time
                            time.sleep(0.5)  # 500ms pauze tussen bestanden
                        
                        # Voeg toe aan succesvolle lijst
                        created_candidates.append(candidate)
                        logger.info(f"Verwerking voltooid voor {file.name}")
                            
                    except Exception as e:
                        logger.error(f"Embedding generatie gefaald voor {file.name}: {str(e)}")
                        processing_errors.append(f'{file.name}: {str(e)}')
                        # Voeg toe aan created_candidates ook bij fout, zodat het geteld wordt
                        created_candidates.append(candidate)
                        
                except Exception as e:
                    logger.error(f"Fout bij uploaden van {file.name}: {str(e)}")
                    processing_errors.append(f'{file.name}: {str(e)}')
        
        except Exception as e:
            logger.error(f"Kritieke fout tijdens upload verwerking: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': f'Server error tijdens verwerking: {str(e)}'
            })
        
        # Return JSON response
        return JsonResponse({
            'success': True,
            'created_count': len(created_candidates),
            'skipped_count': len(skipped_duplicates),
            'error_count': len(processing_errors),
            'created_candidates': [c.name for c in created_candidates],
            'skipped_duplicates': skipped_duplicates,
            'processing_errors': processing_errors,
            'message': f'{len(created_candidates)} CV(s) succesvol geüpload en verwerkt!'
        })


@login_required
def kandidaat_detail_view(request, candidate_id):
    """Detail weergave van een kandidaat."""
    try:
        candidate = Candidate.objects.get(id=candidate_id)
        return render(request, 'kandidaat_detail.html', {'candidate': candidate})
    except Candidate.DoesNotExist:
        messages.error(request, 'Kandidaat niet gevonden.')
        return redirect('vector_matching_app:kandidaten')


@require_http_methods(["POST"])
@login_required
def kandidaat_reprocess_view(request, candidate_id):
    """Herstart de embedding voor een kandidaat."""
    try:
        candidate = Candidate.objects.get(id=candidate_id)
        
        # Start opnieuw embedden (synchroon)
        try:
            reprocess_candidate(candidate_id)
            messages.success(request, f'Opnieuw embedden voltooid voor {candidate.name or f"kandidaat {candidate_id}"}')
        except Exception as e:
            messages.error(request, f'Fout bij opnieuw embedden: {str(e)}')
            
    except Candidate.DoesNotExist:
        messages.error(request, 'Kandidaat niet gevonden.')
    
    return redirect('vector_matching_app:kandidaat_detail', candidate_id=candidate_id)


@login_required
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
@login_required
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


@login_required
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
            
            # Voor city: sla de volledige naam op als die beschikbaar is via hidden field
            city_input = request.POST.get('city', candidate.city)
            city_full = request.POST.get('city_full', '')  # Hidden field met volledige naam
            
            if city_full:
                candidate.city = city_full  # Sla volledige naam op voor geocoding
            else:
                candidate.city = city_input  # Gebruik ingevoerde naam
                
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
            
            # Sla op zonder embedding kolom (die is van type vector, niet jsonb)
            candidate.save(update_fields=[
                'name', 'email', 'phone', 'street', 'house_number', 
                'postal_code', 'city', 'education_level', 'years_experience', 
                'job_titles', 'updated_at'
            ])
            
            # Auto-vul postcode als alleen plaatsnaam is ingevuld
            new_city = request.POST.get('city', '')
            new_postal_code = request.POST.get('postal_code', '')
            
            # Gebruik volledige plaatsnaam als beschikbaar
            city_full = request.POST.get('city_full', '')
            if city_full:
                new_city = city_full
            
            if new_city and not new_postal_code:
                try:
                    from .tasks import get_postcode_for_city
                    suggested_postcode = get_postcode_for_city(new_city)
                    if suggested_postcode:
                        candidate.postal_code = suggested_postcode
                        candidate.save(update_fields=['postal_code', 'updated_at'])
                        messages.info(request, f'Postcode {suggested_postcode} automatisch toegevoegd voor {new_city.split(",")[0].strip()}')
                except Exception as postcode_error:
                    logger.warning(f"Auto-postcode gefaald voor kandidaat {candidate_id}: {str(postcode_error)}")
            
            # Geocode locatie als plaats of postcode is gewijzigd
            old_city = candidate.city
            old_postal_code = candidate.postal_code
            
            if (old_city != new_city or old_postal_code != new_postal_code) and new_city:
                try:
                    from .tasks import geocode_candidate
                    geocode_candidate(candidate_id)
                    messages.info(request, 'Locatie wordt gegeocodeerd...')
                except Exception as geo_error:
                    logger.warning(f"Geocoding gefaald voor kandidaat {candidate_id}: {str(geo_error)}")
            
            messages.success(request, f'{candidate.name or "Kandidaat"} is bijgewerkt.')
            
            return redirect('vector_matching_app:kandidaat_detail', candidate_id=candidate_id)
            
        except Exception as e:
            messages.error(request, f'Fout bij bijwerken: {str(e)}')
    
    return render(request, 'kandidaat_edit.html', {'candidate': candidate})


@require_http_methods(["POST"])
@login_required
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


@require_http_methods(["POST"])
@login_required
def kandidaten_bulk_reprocess_view(request):
    """Herstart de embedding voor meerdere kandidaten tegelijk."""
    try:
        candidate_ids = request.POST.getlist('candidate_ids')
        
        if not candidate_ids:
            messages.warning(request, 'Geen kandidaten geselecteerd.')
            return redirect('vector_matching_app:kandidaten')
        
        processed_count = 0
        failed_count = 0
        failed_candidates = []
        
        for candidate_id in candidate_ids:
            try:
                candidate = Candidate.objects.get(id=candidate_id)
                
                # Controleer of CV tekst beschikbaar is
                if not candidate.cv_text:
                    failed_count += 1
                    failed_candidates.append(f"{candidate.name or f'Kandidaat {candidate_id}'}: Geen CV tekst")
                    continue
                
                # Start opnieuw embedden
                reprocess_candidate(candidate_id)
                processed_count += 1
                
                # Korte pauze tussen kandidaten
                import time
                time.sleep(0.5)
                
            except Candidate.DoesNotExist:
                failed_count += 1
                failed_candidates.append(f"Kandidaat {candidate_id}: Niet gevonden")
                continue
            except Exception as e:
                failed_count += 1
                candidate_name = candidate.name if 'candidate' in locals() else f"Kandidaat {candidate_id}"
                failed_candidates.append(f"{candidate_name}: {str(e)}")
                continue
        
        # Toon resultaten
        if processed_count > 0:
            messages.success(request, f'{processed_count} kandidaat(en) succesvol opnieuw geëmbedded.')
        
        if failed_count > 0:
            error_msg = f'{failed_count} kandidaat(en) gefaald: ' + '; '.join(failed_candidates[:3])
            if len(failed_candidates) > 3:
                error_msg += f' (en {len(failed_candidates) - 3} meer)'
            messages.error(request, error_msg)
            
    except Exception as e:
        messages.error(request, f'Fout bij bulk opnieuw embedden: {str(e)}')
    
    return redirect('vector_matching_app:kandidaten')


@require_http_methods(["POST"])
@login_required
def kandidaten_bulk_geocode_view(request):
    """Geocode meerdere kandidaten tegelijk."""
    try:
        candidate_ids = request.POST.getlist('candidate_ids')
        
        if not candidate_ids:
            messages.warning(request, 'Geen kandidaten geselecteerd.')
            return redirect('vector_matching_app:kandidaten')
        
        processed_count = 0
        failed_count = 0
        failed_candidates = []
        
        for candidate_id in candidate_ids:
            try:
                candidate = Candidate.objects.get(id=candidate_id)
                
                # Controleer of kandidaat een plaats heeft
                if not candidate.city:
                    failed_count += 1
                    failed_candidates.append(f"{candidate.name or f'Kandidaat {candidate_id}'}: Geen plaats opgegeven")
                    continue
                
                # Start geocoding
                from .tasks import geocode_candidate
                geocode_candidate(candidate_id)
                processed_count += 1
                
                # Korte pauze tussen kandidaten
                import time
                time.sleep(0.5)
                
            except Candidate.DoesNotExist:
                failed_count += 1
                failed_candidates.append(f"Kandidaat {candidate_id}: Niet gevonden")
                continue
            except Exception as e:
                failed_count += 1
                candidate_name = candidate.name if 'candidate' in locals() else f"Kandidaat {candidate_id}"
                failed_candidates.append(f"{candidate_name}: {str(e)}")
                continue
        
        # Toon resultaten
        if processed_count > 0:
            messages.success(request, f'{processed_count} kandidaat(en) succesvol gegeocodeerd.')
        
        if failed_count > 0:
            error_msg = f'{failed_count} kandidaat(en) gefaald: ' + ', '.join(failed_candidates[:3])
            if len(failed_candidates) > 3:
                error_msg += f' (en {len(failed_candidates) - 3} meer)'
            messages.error(request, error_msg)
            
    except Exception as e:
        messages.error(request, f'Fout bij bulk geocoding: {str(e)}')
    
    return redirect('vector_matching_app:kandidaten')


# Prompt Management Views
@login_required
def prompts_list_view(request):
    """Overzicht van alle prompts - alleen unieke prompts per naam."""
    # Zorg ervoor dat de standaard prompts bestaan
    _ensure_default_prompts()
    
    # Haal alleen de nieuwste versie van elke unieke prompt op
    prompts = Prompt.objects.filter(
        id__in=Prompt.objects.values('name').annotate(
            latest_id=models.Max('id')
        ).values_list('latest_id', flat=True)
    ).order_by('name')
    
    return render(request, 'prompts.html', {'prompts': prompts})


def _ensure_default_prompts():
    """Zorg ervoor dat de standaard prompts bestaan."""
    # Kandidaten Samenvatting Prompt
    if not Prompt.objects.filter(prompt_type='profile_summary').exists():
        Prompt.objects.create(
            name='Kandidaten Samenvatting',
            prompt_type='profile_summary',
            content="""Schrijf één zakelijke Nederlandse alinea (80–140 woorden) die de kandidaat samenvat voor matching. Benoem opleiding, jaren ervaring, functietitels, domeinen, vaardigheden, talen, beschikbaarheid. Gebruik alleen info uit de CV.

CV tekst:
""",
            is_active=True
        )
    
    # Vacature Samenvatting Prompt
    if not Prompt.objects.filter(prompt_type='vacature_summary').exists():
        Prompt.objects.create(
            name='Vacature Samenvatting',
            prompt_type='vacature_summary',
            content="""Schrijf één zakelijke Nederlandse alinea (80–140 woorden) die de vacature samenvat voor matching met kandidaten. Focus vooral op:

1. Functietitel en niveau
2. Belangrijkste eisen en kwalificaties
3. Verantwoordelijkheden en taken
4. Gewenste ervaring en opleiding
5. Vaardigheden en competenties
6. Locatie en arbeidsvoorwaarden (indien relevant)

Gebruik alleen informatie uit de vacaturetekst. Maak het geschikt voor matching met kandidatenprofielen.

Vacature tekst:
""",
            is_active=True
        )
    
    # CV Parsing Prompt
    if not Prompt.objects.filter(prompt_type='cv_parsing').exists():
        Prompt.objects.create(
            name='CV Parsing',
            prompt_type='cv_parsing',
            content="""Je bent een NL data-extractie-assistent. Antwoord uitsluitend met JSON met deze sleutels:
{ "volledige_naam": "...", "email": "...", "telefoonnummer": "...", "straat": "...", "huisnummer": "...", "postcode": "...", "woonplaats": "...", "opleidingsniveau": "...", "functietitels": ["..."], "jaren_ervaring": 0 }

BELANGRIJK voor opleidingsniveau: Gebruik ALTIJD één van deze categorieën:
- VMBO (voor VMBO, LBO, VBO)
- HAVO (voor HAVO, 5-jarig HAVO)
- VWO (voor VWO, Atheneum, Gymnasium)
- MBO (voor MBO, ROC, niveau 2/3/4)
- HBO (voor HBO, Hogeschool, Bachelor)
- WO (voor WO, Universiteit, Master, PhD)
- Overige (voor alle andere opleidingen)

CV tekst:
""",
            is_active=True
        )


@login_required
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


@login_required
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


@login_required
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


@login_required
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


@login_required
def prompt_logs_view(request):
    """Overzicht van alle prompt logs."""
    logs = PromptLog.objects.all().order_by('-timestamp')[:100]
    return render(request, 'prompt_logs.html', {'logs': logs})


# Vacature Management Views
@login_required
def vacatures_list_view(request):
    """Overzicht van alle vacatures."""
    vacatures = Vacature.objects.filter(actief=True)
    total_count = vacatures.count()
    
    return render(request, 'vacatures.html', {
        'vacatures': vacatures,
        'total_count': total_count
    })


@require_http_methods(["POST"])
@login_required
def vacatures_update_view(request):
    """Update vacatures via de XML feed."""
    try:
        # Verwijder eerst alle demo vacatures (zonder externe_id)
        demo_vacatures = Vacature.objects.filter(externe_id__isnull=True) | Vacature.objects.filter(externe_id="temp")
        demo_count = demo_vacatures.count()
        if demo_count > 0:
            demo_vacatures.delete()
            logger.info(f"{demo_count} demo vacatures verwijderd")
        
        # Haal XML feed op
        feed_url = "https://noordtalent.nl/werkzoeken-feed.xml"
        response = requests.get(feed_url, timeout=30)
        response.raise_for_status()
        
        # Parse XML
        root = ET.fromstring(response.content)
        
        # Teller voor statistieken
        toegevoegd = 0
        bijgewerkt = 0
        gedeactiveerd = 0
        fouten = 0
        
        # Verzamel alle externe IDs uit de feed
        feed_externe_ids = set()
        
        # Verwerk elke vacature in de feed
        for item in root.findall('.//vacature'):
            try:
                # Haal velden op
                externe_id = item.find('id').text if item.find('id') is not None else None
                title = item.find('title').text if item.find('title') is not None else ""
                url = item.find('url').text if item.find('url') is not None else ""
                company = item.find('company').text if item.find('company') is not None else ""
                city = item.find('city').text if item.find('city') is not None else ""
                zipcode = item.find('zipcode').text if item.find('zipcode') is not None else ""
                description = item.find('description').text if item.find('description') is not None else ""
                
                if not externe_id:
                    continue
                    
                feed_externe_ids.add(externe_id)
                
                # Probeer vacature te vinden of maak nieuwe aan
                vacature, created = Vacature.objects.get_or_create(
                    externe_id=externe_id,
                    defaults={
                        'titel': title,
                        'organisatie': company,
                        'plaats': city,
                        'postcode': zipcode,
                        'url': url,
                        'beschrijving': description,
                        'actief': True
                    }
                )
                
                if created:
                    toegevoegd += 1
                    logger.info(f"Vacature toegevoegd: {title} - {company}")
                else:
                    # Update bestaande vacature
                    vacature.titel = title
                    vacature.organisatie = company
                    vacature.plaats = city
                    vacature.postcode = zipcode
                    vacature.url = url
                    vacature.beschrijving = description
                    vacature.actief = True
                    vacature.save()
                    bijgewerkt += 1
                    logger.info(f"Vacature bijgewerkt: {title} - {company}")
                    
            except Exception as e:
                fouten += 1
                logger.error(f"Fout bij verwerken vacature: {str(e)}")
                continue
        
        # Markeer vacatures die niet meer in de feed staan als inactief
        inactive_vacatures = Vacature.objects.filter(actief=True).exclude(externe_id__in=feed_externe_ids)
        for vacature in inactive_vacatures:
            vacature.actief = False
            vacature.save()
            gedeactiveerd += 1
            logger.info(f"Vacature gedeactiveerd: {vacature.titel} - {vacature.organisatie}")
        
        # Check if this is an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from django.http import JsonResponse
            return JsonResponse({
                'success': True,
                'toegevoegd': toegevoegd,
                'bijgewerkt': bijgewerkt,
                'gedeactiveerd': gedeactiveerd,
                'fouten': fouten,
                'message': f'Vacatures bijgewerkt! Toegevoegd: {toegevoegd}, Bijgewerkt: {bijgewerkt}, Gedeactiveerd: {gedeactiveerd}'
            })
        
        # Toon success message
        messages.success(request, 
            f'Vacatures bijgewerkt! Toegevoegd: {toegevoegd}, '
            f'Bijgewerkt: {bijgewerkt}, '
            f'Gedeactiveerd: {gedeactiveerd}'
        )
        
    except requests.RequestException as e:
        logger.error(f"Fout bij ophalen XML feed: {str(e)}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from django.http import JsonResponse
            return JsonResponse({
                'success': False,
                'error': f'Kon XML feed niet ophalen: {str(e)}'
            })
        messages.error(request, f'Kon XML feed niet ophalen: {str(e)}')
    except ET.ParseError as e:
        logger.error(f"Fout bij parsen XML: {str(e)}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from django.http import JsonResponse
            return JsonResponse({
                'success': False,
                'error': f'Kon XML niet parsen: {str(e)}'
            })
        messages.error(request, f'Kon XML niet parsen: {str(e)}')
    except Exception as e:
        logger.error(f"Onverwachte fout bij updaten vacatures: {str(e)}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            from django.http import JsonResponse
            return JsonResponse({
                'success': False,
                'error': f'Onverwachte fout: {str(e)}'
            })
        messages.error(request, f'Onverwachte fout: {str(e)}')
    
    return redirect('vector_matching_app:vacatures')


@login_required
def vacature_detail_view(request, vacature_id):
    """Detail pagina voor een specifieke vacature."""
    vacature = get_object_or_404(Vacature, id=vacature_id)
    
    return render(request, 'vacature_detail.html', {
        'vacature': vacature
    })


@login_required
def vacature_reprocess_view(request, vacature_id):
    """Herverwerk een vacature: genereer nieuwe samenvatting en embedding."""
    vacature = get_object_or_404(Vacature, id=vacature_id)
    
    try:
        from .tasks import reprocess_vacature_embedding
        reprocess_vacature_embedding(vacature_id)
        messages.success(request, f'Vacature "{vacature.titel}" succesvol opnieuw geëmbedded!')
    except Exception as e:
        logger.error(f"Fout bij herverwerken vacature {vacature_id}: {str(e)}")
        messages.error(request, f'Fout bij opnieuw embedden: {str(e)}')
    
    return redirect('vector_matching_app:vacature_detail', vacature_id=vacature_id)


@require_http_methods(["POST"])
@login_required
def vacatures_bulk_reprocess_view(request):
    """Herstart de embedding voor meerdere vacatures tegelijk."""
    try:
        vacature_ids = request.POST.getlist('vacature_ids')
        
        if not vacature_ids:
            messages.warning(request, 'Geen vacatures geselecteerd.')
            return redirect('vector_matching_app:vacatures')
        
        processed_count = 0
        failed_count = 0
        failed_vacatures = []
        
        for vacature_id in vacature_ids:
            try:
                vacature = Vacature.objects.get(id=vacature_id)
                
                # Controleer of beschrijving beschikbaar is
                if not vacature.beschrijving:
                    failed_count += 1
                    failed_vacatures.append(f"{vacature.titel or f'Vacature {vacature_id}'}: Geen beschrijving")
                    continue
                
                # Start opnieuw embedden
                from .tasks import generate_vacature_summary, generate_vacature_embedding
                generate_vacature_summary(vacature_id)
                generate_vacature_embedding(vacature_id)
                processed_count += 1
                
                # Korte pauze tussen vacatures
                import time
                time.sleep(0.5)
                
            except Vacature.DoesNotExist:
                failed_count += 1
                failed_vacatures.append(f"Vacature {vacature_id}: Niet gevonden")
                continue
            except Exception as e:
                failed_count += 1
                vacature_title = vacature.titel if 'vacature' in locals() else f"Vacature {vacature_id}"
                failed_vacatures.append(f"{vacature_title}: {str(e)}")
                continue
        
        # Toon resultaten
        if processed_count > 0:
            messages.success(request, f'{processed_count} vacature(s) succesvol opnieuw geëmbedded.')
        
        if failed_count > 0:
            error_msg = f'{failed_count} vacature(s) gefaald: ' + '; '.join(failed_vacatures[:5])
            if len(failed_vacatures) > 5:
                error_msg += f' ... en {len(failed_vacatures) - 5} meer'
            messages.error(request, error_msg)
            
    except Exception as e:
        logger.error(f"Fout bij bulk herverwerken vacatures: {str(e)}")
        messages.error(request, f'Fout bij bulk opnieuw embedden: {str(e)}')
    
    return redirect('vector_matching_app:vacatures')


# Authentication Views
def login_view(request):
    """Login pagina."""
    if request.user.is_authenticated:
        return redirect('vector_matching_app:index')
    
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        
        if username and password:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f'Welkom terug, {user.username}!')
                next_url = request.GET.get('next', 'vector_matching_app:index')
                return redirect(next_url)
            else:
                messages.error(request, 'Ongeldige gebruikersnaam of wachtwoord.')
        else:
            messages.error(request, 'Vul beide velden in.')
    
    return render(request, 'login.html')


def logout_view(request):
    """Logout functionaliteit."""
    logout(request)
    messages.info(request, 'Je bent succesvol uitgelogd.')
    return redirect('vector_matching_app:login')


@require_http_methods(["POST"])
@login_required
def api_vacatures_update_view(request):
    """API endpoint voor het updaten van vacatures vanuit XML feed."""
    try:
        # Haal XML feed op
        feed_url = "https://noordtalent.nl/werkzoeken-feed.xml"
        response = requests.get(feed_url, timeout=30)
        response.raise_for_status()
        
        # Parse XML
        root = ET.fromstring(response.content)
        
        # Teller voor statistieken
        toegevoegd = 0
        bijgewerkt = 0
        gedeactiveerd = 0
        
        # Verzamel alle externe IDs uit de feed
        feed_externe_ids = set()
        
        # Verwerk elke vacature in de feed
        for item in root.findall('.//vacature'):
            try:
                # Haal velden op
                externe_id = item.find('id').text if item.find('id') is not None else None
                title = item.find('title').text if item.find('title') is not None else ""
                url = item.find('url').text if item.find('url') is not None else ""
                company = item.find('company').text if item.find('company') is not None else ""
                city = item.find('city').text if item.find('city') is not None else ""
                zipcode = item.find('zipcode').text if item.find('zipcode') is not None else ""
                description = item.find('description').text if item.find('description') is not None else ""
                
                if not externe_id:
                    continue
                    
                feed_externe_ids.add(externe_id)
                
                # Probeer vacature te vinden of maak nieuwe aan
                vacature, created = Vacature.objects.get_or_create(
                    externe_id=externe_id,
                    defaults={
                        'titel': title,
                        'organisatie': company,
                        'plaats': city,
                        'postcode': zipcode,
                        'url': url,
                        'beschrijving': description,
                        'actief': True
                    }
                )
                
                if created:
                    toegevoegd += 1
                    logger.info(f"Vacature toegevoegd: {title} - {company}")
                else:
                    # Update bestaande vacature
                    vacature.titel = title
                    vacature.organisatie = company
                    vacature.plaats = city
                    vacature.postcode = zipcode
                    vacature.url = url
                    vacature.beschrijving = description
                    vacature.actief = True
                    vacature.save()
                    bijgewerkt += 1
                    logger.info(f"Vacature bijgewerkt: {title} - {company}")
                    
            except Exception as e:
                logger.error(f"Fout bij verwerken vacature: {str(e)}")
                continue
        
        # Markeer vacatures die niet meer in de feed staan als inactief
        inactive_vacatures = Vacature.objects.filter(actief=True).exclude(externe_id__in=feed_externe_ids)
        for vacature in inactive_vacatures:
            vacature.actief = False
            vacature.save()
            gedeactiveerd += 1
            logger.info(f"Vacature gedeactiveerd: {vacature.titel} - {vacature.organisatie}")
        
        # Retourneer JSON response
        return JsonResponse({
            'success': True,
            'message': 'Vacatures succesvol bijgewerkt',
            'statistieken': {
                'toegevoegd': toegevoegd,
                'bijgewerkt': bijgewerkt,
                'gedeactiveerd': gedeactiveerd,
                'totaal_actief': Vacature.objects.filter(actief=True).count()
            }
        })
        
    except requests.RequestException as e:
        logger.error(f"Fout bij ophalen XML feed: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': f'Kon XML feed niet ophalen: {str(e)}'
        }, status=500)
        
    except ET.ParseError as e:
        logger.error(f"Fout bij parsen XML: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': f'Kon XML niet parsen: {str(e)}'
        }, status=500)
        
    except Exception as e:
        logger.error(f"Onverwachte fout bij updaten vacatures: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': f'Onverwachte fout: {str(e)}'
        }, status=500)


@login_required
def matching_view(request):
    """Toon matchresultaten tussen kandidaten en vacatures."""
    from .models import Match
    
    # Haal echte matches op uit de database, gesorteerd op afstand status
    # Eerst matches met afstand, dan zonder afstand
    matches_with_distance = Match.objects.filter(
        afstand_berekend=True
    ).select_related('kandidaat', 'vacature').order_by('-score')
    
    matches_without_distance = Match.objects.filter(
        afstand_berekend=False
    ).select_related('kandidaat', 'vacature').order_by('-score')
    
    # Combineer en beperk tot 250
    all_matches = list(matches_with_distance) + list(matches_without_distance)
    matches = all_matches[:250]
    
    # Converteer naar format voor template
    matches_data = []
    for match in matches:
        matches_data.append({
            'match_id': match.id,
            'kandidaat_naam': match.kandidaat.name or f"Kandidaat {match.kandidaat.id}",
            'vacature_titel': match.vacature.titel,
            'organisatie': match.vacature.organisatie,
            'matchscore': match.score,
            'afstand_km': match.afstand_km,
            'kandidaat_id': match.kandidaat.id,
            'vacature_id': match.vacature.id,
            'afstand_berekend': match.afstand_berekend,
            'timestamp': match.timestamp
        })
    
    context = {
        'matches': matches_data,
        'total_matches': len(matches_data)
    }
    
    return render(request, 'matching.html', context)


@login_required
@require_http_methods(["POST"])
def generate_matches_view(request):
    """Genereer nieuwe matches via AJAX."""
    from .tasks import generate_matches
    from django.http import JsonResponse
    
    try:
        logger.info("Start genereren matches via web interface")
        
        # Genereer matches
        created_count = generate_matches()
        
        return JsonResponse({
            'success': True,
            'message': f'Succesvol {created_count} matches gegenereerd!',
            'created_count': created_count
        })
        
    except Exception as e:
        logger.error(f"Fout bij genereren matches: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': f'Fout bij genereren matches: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def calculate_distances_view(request):
    """Bereken afstanden voor alle matches die nog geen afstand hebben."""
    try:
        from .models import Match, Candidate, Vacature
        from .tasks import calculate_distance_for_match
        
        # Debug: toon database status
        total_matches = Match.objects.count()
        matches_without_distance = Match.objects.filter(afstand_berekend=False)
        matches_with_distance = Match.objects.filter(afstand_berekend=True)
        total_candidates = Candidate.objects.count()
        total_vacatures = Vacature.objects.count()
        candidates_with_location = Candidate.objects.filter(latitude__isnull=False, longitude__isnull=False).count()
        
        logger.info(f"Database status - Matches: {total_matches} (zonder afstand: {matches_without_distance.count()}, met afstand: {matches_with_distance.count()})")
        logger.info(f"Candidaten: {total_candidates} (met locatie: {candidates_with_location}), Vacatures: {total_vacatures}")
        
        # Haal alle matches op die nog geen afstand hebben
        matches_to_process = matches_without_distance.select_related('kandidaat', 'vacature')
        
        logger.info(f"Berekenen afstanden voor {matches_to_process.count()} matches")
        
        # Bereken afstanden voor alle matches zonder afstand
        calculated_count = 0
        error_count = 0
        
        for match in matches_to_process:
            try:
                # Controleer of kandidaat locatie heeft en vacature plaatsnaam
                if (match.kandidaat.latitude and match.kandidaat.longitude and 
                    match.vacature.plaats):
                    
                    # Bereken afstand
                    distance = calculate_distance_for_match(match)
                    if distance is not None:
                        match.afstand_km = distance
                        match.afstand_berekend = True
                        match.save()
                        calculated_count += 1
                    else:
                        error_count += 1
                else:
                    # Geen locatie beschikbaar - sla None op voor afstand
                    match.afstand_km = None
                    match.afstand_berekend = True  # Markeer als berekend om te voorkomen dat het opnieuw wordt geprobeerd
                    match.save()
                    error_count += 1
                    
            except Exception as e:
                logger.error(f"Fout bij berekenen afstand voor match {match.id}: {str(e)}")
                # Markeer als berekend met None om herhaling te voorkomen
                match.afstand_km = None
                match.afstand_berekend = True
                match.save()
                error_count += 1
                continue
        
        return JsonResponse({
            'success': True,
            'message': f'Afstanden berekend: {calculated_count} succesvol, {error_count} fouten',
            'calculated': calculated_count,
            'errors': error_count
        })
        
    except Exception as e:
        logger.error(f"Fout bij berekenen afstanden: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': f'Fout bij berekenen afstanden: {str(e)}'
        }, status=500)


@require_http_methods(["GET"])
def location_search_view(request):
    """Zoek plaatsen op basis van query voor autocomplete."""
    import requests
    
    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse({'results': []})
    
    try:
        # Zoek via PDOK
        pdok_url = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/suggest"
        params = {
            'q': query,
            'fl': 'weergavenaam,centroide_ll,postcode',
            'rows': 10,
            'fq': 'type:woonplaats'  # Alleen woonplaatsen
        }
        
        response = requests.get(pdok_url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            results = []
            
            for doc in data.get('response', {}).get('docs', []):
                place_name = doc.get('weergavenaam', '')
                postcode = doc.get('postcode', '')
                centroide = doc.get('centroide_ll', '')
                
                if place_name and centroide:
                    # Parse POINT(lon lat) format
                    if centroide.startswith('POINT('):
                        coords = centroide[6:-1]  # Remove 'POINT(' and ')'
                        lon, lat = coords.split(' ')
                    else:
                        lat, lon = centroide.split(' ')
                    
                    results.append({
                        'name': place_name,
                        'postcode': postcode,
                        'latitude': float(lat),
                        'longitude': float(lon)
                    })
            
            return JsonResponse({'results': results})
        
    except Exception as e:
        logger.error(f"Fout bij zoeken plaatsen: {str(e)}")
    
    return JsonResponse({'results': []})


@require_http_methods(["GET"])
def postcode_suggest_view(request):
    """Suggereer postcode op basis van plaatsnaam."""
    place = request.GET.get('place', '').strip().lower()
    if not place:
        return JsonResponse({'postcodes': []})
    
    # Bekende postcodes voor grote steden (eenvoudige mapping)
    city_postcodes = {
        'amsterdam': ['1011', '1012', '1013', '1014', '1015', '1016', '1017', '1018', '1019', '1020'],
        'rotterdam': ['3011', '3012', '3013', '3014', '3015', '3016', '3017', '3018', '3019', '3020'],
        'den haag': ['2511', '2512', '2513', '2514', '2515', '2516', '2517', '2518', '2519', '2520'],
        'utrecht': ['3511', '3512', '3513', '3514', '3515', '3516', '3517', '3518', '3519', '3520'],
        'eindhoven': ['5611', '5612', '5613', '5614', '5615', '5616', '5617', '5618', '5619', '5620'],
        'tilburg': ['5011', '5012', '5013', '5014', '5015', '5016', '5017', '5018', '5019', '5020'],
        'groningen': ['9711', '9712', '9713', '9714', '9715', '9716', '9717', '9718', '9719', '9720'],
        'almere': ['1311', '1312', '1313', '1314', '1315', '1316', '1317', '1318', '1319', '1320'],
        'breda': ['4811', '4812', '4813', '4814', '4815', '4816', '4817', '4818', '4819', '4820'],
        'nijmegen': ['6511', '6512', '6513', '6514', '6515', '6516', '6517', '6518', '6519', '6520'],
    }
    
    # Zoek exacte match
    if place in city_postcodes:
        return JsonResponse({'postcodes': city_postcodes[place]})
    
    # Zoek gedeeltelijke match
    for city, postcodes in city_postcodes.items():
        if place in city or city in place:
            return JsonResponse({'postcodes': postcodes[:5]})  # Max 5 suggesties
    
    return JsonResponse({'postcodes': []})


@login_required
def debug_database_status_view(request):
    """Debug view om database status te bekijken."""
    from .models import Match, Candidate, Vacature
    
    total_matches = Match.objects.count()
    matches_without_distance = Match.objects.filter(afstand_berekend=False).count()
    matches_with_distance = Match.objects.filter(afstand_berekend=True).count()
    total_candidates = Candidate.objects.count()
    total_vacatures = Vacature.objects.count()
    candidates_with_location = Candidate.objects.filter(latitude__isnull=False, longitude__isnull=False).count()
    candidates_with_embedding = Candidate.objects.filter(embedding__isnull=False).count()
    vacatures_with_embedding = Vacature.objects.filter(embedding__isnull=False).count()
    
    # Sample data
    sample_matches = list(Match.objects.select_related('kandidaat', 'vacature')[:5])
    sample_candidates = list(Candidate.objects.all()[:5])
    sample_vacatures = list(Vacature.objects.all()[:5])
    
    context = {
        'total_matches': total_matches,
        'matches_without_distance': matches_without_distance,
        'matches_with_distance': matches_with_distance,
        'total_candidates': total_candidates,
        'total_vacatures': total_vacatures,
        'candidates_with_location': candidates_with_location,
        'candidates_with_embedding': candidates_with_embedding,
        'vacatures_with_embedding': vacatures_with_embedding,
        'sample_matches': sample_matches,
        'sample_candidates': sample_candidates,
        'sample_vacatures': sample_vacatures,
    }
    
    return render(request, 'debug_database_status.html', context)


@login_required
@require_http_methods(["GET"])
def get_match_afstand(request, match_id):
    """Haal afstand op voor een specifieke match."""
    from .models import Match
    
    try:
        match = get_object_or_404(Match, id=match_id)
        
        # Als afstand al berekend is, retourneer deze
        if match.afstand_berekend and match.afstand_km is not None:
            return JsonResponse({
                'success': True,
                'afstand_km': float(match.afstand_km),
                'berekend': True
            })
        
        # Bereken afstand (voor nu fictief, later met echte geolocatie)
        # TODO: Implementeer echte afstandsberekening op basis van postcodes
        import random
        afstand = round(random.uniform(5, 100), 1)
        
        # Update match met berekende afstand
        match.afstand_km = afstand
        match.afstand_berekend = True
        match.save()
        
        return JsonResponse({
            'success': True,
            'afstand_km': afstand,
            'berekend': True
        })
        
    except Exception as e:
        logger.error(f"Fout bij ophalen afstand voor match {match_id}: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': f'Fout bij ophalen afstand: {str(e)}'
        }, status=500)


