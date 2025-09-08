from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.db import connection
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
    # Haal statistieken op
    total_candidates = Candidate.objects.count()
    completed_candidates = Candidate.objects.filter(embed_status='completed').count()
    queued_candidates = Candidate.objects.filter(embed_status='queued').count()
    failed_candidates = Candidate.objects.filter(embed_status='failed').count()
    total_vacatures = Vacature.objects.filter(actief=True).count()
    
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
        'completed_candidates': completed_candidates,
        'queued_candidates': queued_candidates,
        'failed_candidates': failed_candidates,
        'total_vacatures': total_vacatures,
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
        processing_errors = []
        
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
                        # Geen pauze na duplicaat - ga direct door
                    else:
                        created_candidates.append(candidate)
                        logger.info(f"Verwerking voltooid voor {file.name}")
                        # Korte pauze alleen na succesvolle verwerking
                        if i < len(files) - 1:
                            import time
                            time.sleep(1)  # 1 seconde pauze
                        
                except Exception as e:
                    logger.error(f"Verwerking gefaald voor {file.name}: {str(e)}")
                    processing_errors.append(f'{file.name}: {str(e)}')
                    # Voeg toe aan created_candidates ook bij fout, zodat het geteld wordt
                    created_candidates.append(candidate)
                    # Korte pauze na fout
                    if i < len(files) - 1:
                        import time
                        time.sleep(1)
                    
            except Exception as e:
                logger.error(f"Fout bij uploaden van {file.name}: {str(e)}")
                processing_errors.append(f'{file.name}: {str(e)}')
        
        # Toon resultaten
        if created_candidates:
            success_message = f'{len(created_candidates)} CV(s) succesvol geüpload en verwerkt!'
            if skipped_duplicates:
                success_message += f' {len(skipped_duplicates)} duplicaat(en) overgeslagen.'
            messages.success(request, success_message)
            
            # Redirect naar de eerste kandidaat detail pagina (als die bestaat)
            if len(created_candidates) == 1:
                return redirect('vector_matching_app:kandidaat_detail', candidate_id=created_candidates[0].id)
        else:
            # Geen kandidaten aangemaakt
            if skipped_duplicates:
                messages.warning(request, f'Alle {len(skipped_duplicates)} bestand(en) waren duplicaten en zijn overgeslagen.')
            else:
                messages.error(request, 'Geen bestanden konden worden verwerkt.')
        
        # Toon verwerkingsfouten
        if processing_errors:
            error_message = f'Verwerkingsfouten: {"; ".join(processing_errors[:3])}'
            if len(processing_errors) > 3:
                error_message += f' (en {len(processing_errors) - 3} meer)'
            messages.error(request, error_message)
        
        return redirect('vector_matching_app:kandidaten')


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


# Prompt Management Views
@login_required
def prompts_list_view(request):
    """Overzicht van alle prompts."""
    # Zorg ervoor dat de standaard prompts bestaan
    _ensure_default_prompts()
    
    prompts = Prompt.objects.all().order_by('name', '-version')
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
        
        # Toon success message
        messages.success(request, 
            f'Vacatures bijgewerkt! Toegevoegd: {toegevoegd}, '
            f'Bijgewerkt: {bijgewerkt}, '
            f'Gedeactiveerd: {gedeactiveerd}'
        )
        
    except requests.RequestException as e:
        logger.error(f"Fout bij ophalen XML feed: {str(e)}")
        messages.error(request, f'Kon XML feed niet ophalen: {str(e)}')
    except ET.ParseError as e:
        logger.error(f"Fout bij parsen XML: {str(e)}")
        messages.error(request, f'Kon XML niet parsen: {str(e)}')
    except Exception as e:
        logger.error(f"Onverwachte fout bij updaten vacatures: {str(e)}")
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


@login_required
def vacatures_bulk_reprocess_view(request):
    """Bulk herverwerk vacatures: genereer nieuwe samenvattingen en embeddings."""
    if request.method != 'POST':
        return redirect('vector_matching_app:vacatures')
    
    vacature_ids_str = request.POST.get('vacature_ids', '')
    if not vacature_ids_str:
        messages.error(request, 'Geen vacatures geselecteerd.')
        return redirect('vector_matching_app:vacatures')
    
    try:
        vacature_ids = [int(id.strip()) for id in vacature_ids_str.split(',') if id.strip()]
        vacatures = Vacature.objects.filter(id__in=vacature_ids)
        
        if not vacatures.exists():
            messages.error(request, 'Geen geldige vacatures gevonden.')
            return redirect('vector_matching_app:vacatures')
        
        from .tasks import reprocess_vacature_embedding
        import time
        
        success_count = 0
        error_count = 0
        
        for vacature in vacatures:
            try:
                reprocess_vacature_embedding(vacature.id)
                success_count += 1
                time.sleep(0.5)  # Korte pauze tussen requests
            except Exception as e:
                logger.error(f"Fout bij herverwerken vacature {vacature.id}: {str(e)}")
                error_count += 1
        
        if success_count > 0:
            messages.success(request, f'{success_count} vacature(s) succesvol opnieuw geëmbedded!')
        if error_count > 0:
            messages.error(request, f'{error_count} vacature(s) gefaald bij opnieuw embedden.')
            
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


