import json
import logging
import os
import requests
from django.conf import settings
from django.core.files.base import ContentFile
from .models import Candidate, Vacature, Prompt
from .services.openai_client import get_openai_client

logger = logging.getLogger(__name__)

# PDF processing imports
try:
    import PyPDF2
    PDF_LIBRARY = 'PyPDF2'
except ImportError:
    try:
        from pdfminer.high_level import extract_text
        PDF_LIBRARY = 'pdfminer'
    except ImportError:
        PDF_LIBRARY = None


def extract_pdf_text(candidate_id):
    """Extract tekst uit PDF CV."""
    try:
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('processing', 'PDF tekst extractie')
        
        if not candidate.cv_pdf:
            raise ValueError("Geen CV PDF gevonden")
        
        if PDF_LIBRARY is None:
            raise ValueError("Geen PDF bibliotheek beschikbaar. Installeer PyPDF2 of pdfminer")
        
        # Lees PDF bestand
        pdf_path = candidate.cv_pdf.path
        if not os.path.exists(pdf_path):
            raise ValueError(f"PDF bestand niet gevonden: {pdf_path}")
        
        # Extract tekst
        if PDF_LIBRARY == 'PyPDF2':
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
        else:  # pdfminer
            text = extract_text(pdf_path)
        
        if not text.strip():
            raise ValueError("Geen tekst gevonden in PDF")
        
        # Verwijder NUL bytes en andere problematische karakters
        cleaned_text = text.replace('\x00', '').replace('\0', '').strip()
        
        if not cleaned_text:
            raise ValueError("Geen bruikbare tekst na opschoning")
        
        # Sla tekst op
        candidate.cv_text = cleaned_text
        candidate.save(update_fields=['cv_text', 'updated_at'])
        
        logger.info(f"PDF tekst geëxtraheerd voor kandidaat {candidate_id}")
        return candidate_id
        
    except Exception as e:
        logger.error(f"Fout bij PDF extractie voor kandidaat {candidate_id}: {str(e)}")
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('failed', 'PDF tekst extractie', str(e))
        raise


def parse_cv_to_fields(candidate_id):
    """Parse CV tekst naar gestructureerde velden met OpenAI."""
    try:
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('processing', 'CV parsing')
        
        if not candidate.cv_text:
            raise ValueError("Geen CV tekst gevonden")
        
        # OpenAI prompt
        prompt = """Je bent een NL data-extractie-assistent. Antwoord uitsluitend met JSON met deze sleutels:
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
""" + candidate.cv_text[:4000]  # Limiteer input voor OpenAI
        
        # OpenAI API call
        try:
            openai_client = get_openai_client()
            messages = [
                {"role": "system", "content": "Je bent een expert in het extraheren van gestructureerde data uit Nederlandse CV's. Antwoord altijd met geldige JSON."},
                {"role": "user", "content": prompt}
            ]
            
            response = openai_client.chat(messages, model="gpt-3.5-turbo")
        except Exception as e:
            logger.error(f"OpenAI API error bij CV parsing voor kandidaat {candidate_id}: {str(e)}")
            raise ValueError(f"OpenAI API fout: {str(e)}")
        
        # Parse JSON response
        try:
            extracted_data = json.loads(response)
        except json.JSONDecodeError:
            # Probeer JSON te extraheren uit response
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                extracted_data = json.loads(json_match.group())
            else:
                raise ValueError("Geen geldige JSON gevonden in OpenAI response")
        
        # Valideer en normaliseer data met fallback waarden
        def safe_get(data, key, default=None):
            value = data.get(key, default)
            if value is None or (isinstance(value, str) and not value.strip()):
                return default
            return value
        
        def normalize_education_level(level):
            """Normaliseer opleidingsniveau naar standaard categorieën."""
            if not level or not isinstance(level, str):
                return 'Overige'
            
            level_lower = level.lower().strip()
            
            # VMBO categorieën
            if any(x in level_lower for x in ['vmbo', 'lbo', 'vbo', 'mavo']):
                return 'VMBO'
            
            # HAVO categorieën
            elif any(x in level_lower for x in ['havo', '5-jarig']):
                return 'HAVO'
            
            # VWO categorieën
            elif any(x in level_lower for x in ['vwo', 'atheneum', 'gymnasium']):
                return 'VWO'
            
            # MBO categorieën
            elif any(x in level_lower for x in ['mbo', 'roc', 'niveau 2', 'niveau 3', 'niveau 4']):
                return 'MBO'
            
            # HBO categorieën
            elif any(x in level_lower for x in ['hbo', 'hogeschool', 'bachelor', 'bsc', 'ba']):
                return 'HBO'
            
            # WO categorieën
            elif any(x in level_lower for x in ['wo', 'universiteit', 'master', 'msc', 'ma', 'phd', 'doctoraat']):
                return 'WO'
            
            # Overige
            else:
                return 'Overige'
        
        extracted_data = {
            'volledige_naam': safe_get(extracted_data, 'volledige_naam', 'Onbekend'),
            'email': safe_get(extracted_data, 'email'),
            'telefoonnummer': safe_get(extracted_data, 'telefoonnummer'),
            'straat': safe_get(extracted_data, 'straat'),
            'huisnummer': safe_get(extracted_data, 'huisnummer'),
            'postcode': safe_get(extracted_data, 'postcode'),
            'woonplaats': safe_get(extracted_data, 'woonplaats'),
            'opleidingsniveau': normalize_education_level(safe_get(extracted_data, 'opleidingsniveau')),
            'functietitels': safe_get(extracted_data, 'functietitels', []),
            'jaren_ervaring': safe_get(extracted_data, 'jaren_ervaring', 0)
        }
        
        # Controleer duplicaten op basis van e-mailadres (alleen als e-mail niet leeg is)
        email = extracted_data['email']
        name = extracted_data['volledige_naam']
        
        # Check duplicaten op e-mailadres EN naam
        existing_candidate = None
        duplicate_reason = ""
        
        if email and email.strip():
            # Check op e-mailadres
            existing_candidate = Candidate.objects.filter(email=email).exclude(id=candidate_id).first()
            if existing_candidate:
                duplicate_reason = f"E-mailadres {email} bestaat al bij kandidaat {existing_candidate.id}"
        
        if not existing_candidate and name and name.strip():
            # Check op naam (case-insensitive)
            existing_candidate = Candidate.objects.filter(
                name__iexact=name.strip()
            ).exclude(id=candidate_id).first()
            if existing_candidate:
                duplicate_reason = f"Naam '{name}' bestaat al bij kandidaat {existing_candidate.id}"
        
        if existing_candidate:
            logger.warning(f"Duplicaat gevonden: {duplicate_reason}. Kandidaat {candidate_id} wordt gemarkeerd als duplicaat.")
            candidate.embed_status = 'failed'
            candidate.error_message = f"Duplicaat: {duplicate_reason}"
            candidate.save(update_fields=['embed_status', 'error_message', 'updated_at'])
            return candidate_id
        
        # Update candidate velden
        candidate.name = extracted_data['volledige_naam']
        candidate.email = email  # Kan leeg zijn
        candidate.phone = extracted_data['telefoonnummer']
        candidate.street = extracted_data['straat']
        candidate.house_number = extracted_data['huisnummer']
        candidate.postal_code = extracted_data['postcode']
        candidate.city = extracted_data['woonplaats']
        candidate.education_level = extracted_data['opleidingsniveau']
        candidate.job_titles = extracted_data['functietitels']
        candidate.years_experience = extracted_data['jaren_ervaring']
        candidate.extract_json = extracted_data
        
        candidate.save(update_fields=[
            'name', 'email', 'phone', 'street', 'house_number', 'postal_code', 
            'city', 'education_level', 'job_titles', 'years_experience', 
            'extract_json', 'updated_at'
        ])
        
        logger.info(f"CV geparsed voor kandidaat {candidate_id}")
        return candidate_id
        
    except Exception as e:
        logger.error(f"Fout bij CV parsing voor kandidaat {candidate_id}: {str(e)}")
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('failed', 'CV parsing', str(e))
        raise


def generate_profile_summary_text(candidate_id):
    """Genereer profiel samenvatting met OpenAI."""
    try:
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('processing', 'Profiel samenvatting')
        
        if not candidate.cv_text:
            raise ValueError("Geen CV tekst gevonden")
        
        # Haal de actieve samenvatting prompt op uit de database
        from .models import Prompt
        prompt_obj = Prompt.objects.filter(prompt_type='profile_summary', is_active=True).first()
        
        if prompt_obj:
            # Gebruik de prompt uit de database
            prompt = prompt_obj.content + candidate.cv_text[:4000]  # Limiteer input voor OpenAI
        else:
            # Fallback naar hardcoded prompt
            prompt = """Schrijf één zakelijke Nederlandse alinea (80–140 woorden) die de kandidaat samenvat voor matching. Benoem opleiding, jaren ervaring, functietitels, domeinen, vaardigheden, talen, beschikbaarheid. Gebruik alleen info uit de CV.

CV tekst:
""" + candidate.cv_text[:4000]  # Limiteer input voor OpenAI
        
        # OpenAI API call
        try:
            openai_client = get_openai_client()
            messages = [
                {"role": "system", "content": "Je bent een expert in het schrijven van zakelijke profiel samenvattingen voor Nederlandse kandidaten. Schrijf helder en beknopt."},
                {"role": "user", "content": prompt}
            ]
            
            response = openai_client.chat(messages, model="gpt-3.5-turbo")
        except Exception as e:
            logger.error(f"OpenAI API error bij profiel samenvatting voor kandidaat {candidate_id}: {str(e)}")
            raise ValueError(f"OpenAI API fout: {str(e)}")
        
        # Sla profiel tekst op
        candidate.profile_text = response.strip()
        candidate.save(update_fields=['profile_text', 'updated_at'])
        
        logger.info(f"Profiel samenvatting gegenereerd voor kandidaat {candidate_id}")
        return candidate_id
        
    except Exception as e:
        logger.error(f"Fout bij profiel samenvatting voor kandidaat {candidate_id}: {str(e)}")
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('failed', 'Profiel samenvatting', str(e))
        raise


def embed_profile_text(candidate_id):
    """Embed profiel tekst met OpenAI."""
    try:
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('processing', 'Embedding generatie')
        
        if not candidate.profile_text:
            raise ValueError("Geen profiel tekst gevonden")
        
        # OpenAI embedding
        try:
            openai_client = get_openai_client()
            embedding = openai_client.embed(candidate.profile_text, model="text-embedding-3-small")
        except Exception as e:
            logger.error(f"OpenAI API error bij embedding voor kandidaat {candidate_id}: {str(e)}")
            raise ValueError(f"OpenAI API fout: {str(e)}")
        
        # Sla embedding op - detecteer kolom type en gebruik juiste cast
        from django.db import connection
        
        # Converteer naar lijst
        embedding_list = embedding.tolist() if hasattr(embedding, 'tolist') else list(embedding)
        
        # Converteer naar JSON string voor PostgreSQL
        import json
        embedding_json = json.dumps(embedding_list)
        
        # Probeer eerst JSONB, dan vector
        with connection.cursor() as cursor:
            try:
                # Probeer JSONB met JSON string
                cursor.execute(
                    "UPDATE vector_matching_app_candidate SET embedding = %s::jsonb WHERE id = %s",
                    [embedding_json, candidate_id]
                )
                logger.info(f"Embedding opgeslagen als JSONB voor kandidaat {candidate_id}")
            except Exception as jsonb_error:
                logger.warning(f"JSONB cast gefaald voor kandidaat {candidate_id}, probeer vector: {jsonb_error}")
                try:
                    # Probeer vector als fallback
                    cursor.execute(
                        "UPDATE vector_matching_app_candidate SET embedding = %s::vector WHERE id = %s",
                        [embedding_list, candidate_id]
                    )
                    logger.info(f"Embedding opgeslagen als vector voor kandidaat {candidate_id}")
                except Exception as vector_error:
                    logger.error(f"Beide casts gefaald voor kandidaat {candidate_id}: JSONB={jsonb_error}, Vector={vector_error}")
                    raise vector_error
        
        # Update alleen de timestamp via Django ORM
        candidate.save(update_fields=['updated_at'])
        
        logger.info(f"Embedding gegenereerd voor kandidaat {candidate_id}")
        return candidate_id
        
    except Exception as e:
        logger.error(f"Fout bij embedding voor kandidaat {candidate_id}: {str(e)}")
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('failed', 'Embedding generatie', str(e))
        raise


def get_postcode_for_city(city_name):
    """Haal de eerste postcode op voor een plaatsnaam."""
    import requests
    
    try:
        # Probeer eerst Nominatim voor postcode informatie
        nominatim_url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': f"{city_name}, Nederland",
            'format': 'json',
            'limit': 5,
            'countrycodes': 'nl',
            'addressdetails': 1
        }
        
        response = requests.get(nominatim_url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            
            for result in data:
                address = result.get('address', {})
                postcode = address.get('postcode', '')
                
                if postcode and len(postcode) == 6:  # Nederlandse postcode format
                    return postcode
        
        # Fallback: gebruik bekende postcodes voor grote steden
        city_postcodes = {
            'amsterdam': '1011',
            'rotterdam': '3011', 
            'den haag': '2511',
            'utrecht': '3511',
            'eindhoven': '5611',
            'tilburg': '5011',
            'groningen': '9711',
            'almere': '1311',
            'breda': '4811',
            'nijmegen': '6511',
            'wijhe': '8131',  # Toegevoegd voor Wijhe
            'olst': '8121',   # Toegevoegd voor Olst
        }
        
        city_lower = city_name.lower().strip()
        for city, postcode in city_postcodes.items():
            if city in city_lower or city_lower in city:
                return postcode
                
    except Exception as e:
        logger.warning(f"Fout bij ophalen postcode voor {city_name}: {str(e)}")
    
    return None


def geocode_candidate(candidate_id):
    """Geocode kandidaat locatie met PDOK en Nominatim."""
    try:
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('processing', 'Geocoding')
        
        # Auto-vul postcode als alleen plaatsnaam beschikbaar is
        if candidate.city and not candidate.postal_code:
            # Gebruik alleen de eerste deel van de plaatsnaam voor postcode lookup
            city_name = candidate.city.split(',')[0].strip()
            suggested_postcode = get_postcode_for_city(city_name)
            if suggested_postcode:
                candidate.postal_code = suggested_postcode
                candidate.save(update_fields=['postal_code', 'updated_at'])
                logger.info(f"Auto-toegevoegde postcode {suggested_postcode} voor plaats {city_name}")
        
        # Bereid adres voor - probeer verschillende combinaties
        short_city = candidate.city.split(',')[0].strip() if candidate.city else ""
        
        if not short_city:
            logger.warning(f"Geen plaatsnaam gevonden voor kandidaat {candidate_id}")
            candidate.update_status('completed', 'Geocoding', 'Geen plaatsnaam')
            return
        
        # Probeer verschillende adres combinaties
        address_attempts = []
        
        # 1. Postcode + plaats (als beide beschikbaar)
        if candidate.postal_code and candidate.city:
            formatted_postcode = candidate.postal_code.replace(' ', '')
            address_attempts.append(f"{formatted_postcode} {short_city}")
        
        # 2. Alleen plaatsnaam (altijd als fallback)
        address_attempts.append(short_city)
        
        # 3. Volledig adres (als beschikbaar)
        if candidate.street or candidate.house_number:
            address_parts = []
            if candidate.street:
                address_parts.append(candidate.street)
            if candidate.house_number:
                address_parts.append(candidate.house_number)
            if candidate.postal_code:
                address_parts.append(candidate.postal_code)
            address_parts.append(short_city)
            address_attempts.append(', '.join(address_parts))
        
        lat, lon = None, None
        
        # Probeer PDOK met verschillende adres combinaties
        for i, address in enumerate(address_attempts):
            if lat is not None and lon is not None:
                break  # Al gevonden
                
            try:
                logger.info(f"PDOK poging {i+1}: {address}")
                pdok_url = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/suggest"
                params = {
                    'fl': 'weergavenaam,centroide_ll',
                    'q': address,
                    'rows': 1
                }
                
                response = requests.get(pdok_url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('response', {}).get('docs'):
                        doc = data['response']['docs'][0]
                        if 'centroide_ll' in doc:
                            centroide = doc['centroide_ll']
                            # Parse POINT(lon lat) format
                            if centroide.startswith('POINT('):
                                coords = centroide[6:-1]  # Remove 'POINT(' and ')'
                                lon, lat = coords.split(' ')
                            else:
                                lat, lon = centroide.split(' ')
                            lat, lon = float(lat), float(lon)
                            logger.info(f"PDOK geocoding succesvol voor kandidaat {candidate_id} met: {address}")
                            break
            except Exception as e:
                logger.warning(f"PDOK geocoding gefaald voor kandidaat {candidate_id} met '{address}': {str(e)}")
                continue
        
        # Fallback naar Nominatim
        if lat is None or lon is None:
            for i, address in enumerate(address_attempts):
                if lat is not None and lon is not None:
                    break  # Al gevonden
                    
                try:
                    logger.info(f"Nominatim poging {i+1}: {address}")
                    nominatim_url = "https://nominatim.openstreetmap.org/search"
                    params = {
                        'q': address,
                        'format': 'json',
                        'limit': 1,
                        'countrycodes': 'nl'  # Focus op Nederland
                    }
                    
                    response = requests.get(nominatim_url, params=params, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        if data:
                            lat = float(data[0]['lat'])
                            lon = float(data[0]['lon'])
                            logger.info(f"Nominatim geocoding succesvol voor kandidaat {candidate_id} met: {address}")
                            break
                except Exception as e:
                    logger.warning(f"Nominatim geocoding gefaald voor kandidaat {candidate_id} met '{address}': {str(e)}")
                    continue
        
        if lat is not None and lon is not None:
            candidate.latitude = lat
            candidate.longitude = lon
            candidate.embed_status = 'completed'
            candidate.processing_step = 'Voltooid'
            candidate.save(update_fields=['latitude', 'longitude', 'embed_status', 'processing_step', 'updated_at'])
            logger.info(f"Geocoding voltooid voor kandidaat {candidate_id}: {lat}, {lon}")
        else:
            logger.warning(f"Geen locatie gevonden via PDOK of Nominatim voor kandidaat {candidate_id}")
            candidate.update_status('completed', 'Geocoding', 'Geen locatie gevonden')
            return candidate_id
        
        return candidate_id
        
    except Exception as e:
        logger.warning(f"Fout bij geocoding voor kandidaat {candidate_id}: {str(e)}")
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('completed', 'Geocoding', f'Geocoding fout: {str(e)}')
        return candidate_id


def process_candidate_pipeline(candidate_id):
    """Start de volledige verwerkingspipeline voor een kandidaat."""
    try:
        logger.info(f"Verwerkingspipeline gestart voor kandidaat {candidate_id}")
        
        # Voer alle stappen synchroon uit
        extract_pdf_text(candidate_id)
        parse_cv_to_fields(candidate_id)
        generate_profile_summary_text(candidate_id)
        embed_profile_text(candidate_id)
        geocode_candidate(candidate_id)
        
        logger.info(f"Verwerkingspipeline voltooid voor kandidaat {candidate_id}")
        return True
        
    except Exception as e:
        logger.error(f"Fout bij verwerken pipeline voor kandidaat {candidate_id}: {str(e)}")
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('failed', 'Pipeline verwerking', str(e))
        raise


def reprocess_candidate(candidate_id):
    """Herstart alleen de profiel samenvatting en embedding voor een kandidaat."""
    try:
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('processing', 'Opnieuw embedden')
        candidate.error_message = ''
        candidate.save(update_fields=['embed_status', 'processing_step', 'error_message', 'updated_at'])
        
        # Controleer of CV tekst beschikbaar is
        if not candidate.cv_text:
            raise ValueError("Geen CV tekst gevonden - kan niet opnieuw embedden")
        
        # Alleen profiel samenvatting en embedding opnieuw genereren
        generate_profile_summary_text(candidate_id)
        embed_profile_text(candidate_id)
        
        candidate.update_status('completed', 'Opnieuw embedden voltooid')
        logger.info(f"Opnieuw embedden voltooid voor kandidaat {candidate_id}")
        return True
        
    except Exception as e:
        logger.error(f"Fout bij opnieuw embedden voor kandidaat {candidate_id}: {str(e)}")
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('failed', 'Opnieuw embedden mislukt', str(e))
        raise


# Vacature Processing Functions
def generate_vacature_summary(vacature_id):
    """Genereer een AI samenvatting voor een vacature."""
    try:
        vacature = Vacature.objects.get(id=vacature_id)
        
        # Haal de actieve vacature samenvatting prompt op
        try:
            prompt_obj = Prompt.objects.filter(
                prompt_type='vacature_summary',
                is_active=True
            ).first()
            
            if prompt_obj:
                prompt = prompt_obj.content
            else:
                # Fallback prompt
                prompt = """Schrijf één zakelijke Nederlandse alinea (80–140 woorden) die de vacature samenvat voor matching met kandidaten. Focus vooral op:

1. Functietitel en niveau
2. Belangrijkste eisen en kwalificaties
3. Verantwoordelijkheden en taken
4. Gewenste ervaring en opleiding
5. Vaardigheden en competenties
6. Locatie en arbeidsvoorwaarden (indien relevant)

Gebruik alleen informatie uit de vacaturetekst. Maak het geschikt voor matching met kandidatenprofielen.

Vacature tekst:
"""
        except Exception as e:
            logger.warning(f"Kon prompt niet ophalen, gebruik fallback: {str(e)}")
            prompt = """Schrijf één zakelijke Nederlandse alinea (80–140 woorden) die de vacature samenvat voor matching met kandidaten. Focus vooral op functietitel, eisen, verantwoordelijkheden, ervaring en vaardigheden.

Vacature tekst:
"""
        
        # Bereid de vacature tekst voor
        vacature_text = f"""
Titel: {vacature.titel}
Organisatie: {vacature.organisatie}
Locatie: {vacature.plaats}, {vacature.postcode}
Beschrijving: {vacature.beschrijving}
"""
        
        # Genereer samenvatting met OpenAI
        client = get_openai_client()
        messages = [
            {"role": "system", "content": "Je bent een expert in het samenvatten van vacatures voor matching met kandidaten."},
            {"role": "user", "content": f"{prompt}\n\n{vacature_text}"}
        ]
        
        summary = client.chat(messages, model="gpt-4o-mini").strip()
        
        # Sla de samenvatting op
        vacature.samenvatting = summary
        vacature.save()
        
        logger.info(f"Samenvatting gegenereerd voor vacature {vacature_id}")
        return summary
        
    except Exception as e:
        logger.error(f"Fout bij genereren samenvatting voor vacature {vacature_id}: {str(e)}")
        raise


def generate_vacature_embedding(vacature_id):
    """Genereer een embedding voor een vacature."""
    try:
        vacature = Vacature.objects.get(id=vacature_id)
        
        # Gebruik de samenvatting als basis voor de embedding
        text_for_embedding = vacature.samenvatting or vacature.beschrijving or f"{vacature.titel} {vacature.organisatie}"
        
        if not text_for_embedding.strip():
            raise ValueError("Geen tekst beschikbaar voor embedding")
        
        # Genereer embedding met OpenAI
        client = get_openai_client()
        embedding = client.embed(text_for_embedding, model="text-embedding-3-small")
        
        # Sla de embedding op - detecteer kolom type en gebruik juiste cast
        from django.db import connection
        
        # Converteer naar lijst
        embedding_list = embedding.tolist() if hasattr(embedding, 'tolist') else list(embedding)
        
        # Converteer naar JSON string voor PostgreSQL
        import json
        embedding_json = json.dumps(embedding_list)
        
        # Probeer eerst JSONB, dan vector
        with connection.cursor() as cursor:
            try:
                # Probeer JSONB met JSON string
                cursor.execute(
                    "UPDATE vector_matching_app_vacature SET embedding = %s::jsonb WHERE id = %s",
                    [embedding_json, vacature_id]
                )
                logger.info(f"Embedding opgeslagen als JSONB voor vacature {vacature_id}")
            except Exception as jsonb_error:
                logger.warning(f"JSONB cast gefaald voor vacature {vacature_id}, probeer vector: {jsonb_error}")
                try:
                    # Probeer vector als fallback
                    cursor.execute(
                        "UPDATE vector_matching_app_vacature SET embedding = %s::vector WHERE id = %s",
                        [embedding_list, vacature_id]
                    )
                    logger.info(f"Embedding opgeslagen als vector voor vacature {vacature_id}")
                except Exception as vector_error:
                    logger.error(f"Beide casts gefaald voor vacature {vacature_id}: JSONB={jsonb_error}, Vector={vector_error}")
                    raise vector_error
        
        # Update alleen de timestamp via Django ORM
        vacature.save(update_fields=['updated_at'])
        
        logger.info(f"Embedding gegenereerd voor vacature {vacature_id}")
        return embedding
        
    except Exception as e:
        logger.error(f"Fout bij genereren embedding voor vacature {vacature_id}: {str(e)}")
        raise


def process_vacature_embedding(vacature_id):
    """Volledige pipeline voor vacature embedding: samenvatting + embedding."""
    try:
        logger.info(f"Start verwerking vacature {vacature_id}")
        
        # Stap 1: Genereer samenvatting
        generate_vacature_summary(vacature_id)
        
        # Stap 2: Genereer embedding
        generate_vacature_embedding(vacature_id)
        
        logger.info(f"Vacature {vacature_id} succesvol verwerkt")
        
    except Exception as e:
        logger.error(f"Fout bij verwerken vacature {vacature_id}: {str(e)}")
        raise


def reprocess_vacature_embedding(vacature_id):
    """Herverwerk een vacature: genereer nieuwe samenvatting en embedding."""
    try:
        logger.info(f"Start herverwerking vacature {vacature_id}")
        
        # Herverwerk de vacature
        process_vacature_embedding(vacature_id)
        
        logger.info(f"Vacature {vacature_id} succesvol herverwerkt")
        
    except Exception as e:
        logger.error(f"Fout bij herverwerken vacature {vacature_id}: {str(e)}")
        raise


def calculate_cosine_similarity(embedding1, embedding2):
    """Bereken cosine similarity tussen twee embeddings."""
    import numpy as np
    import json
    
    try:
        # Zorg dat beide embeddings numpy arrays zijn
        if isinstance(embedding1, str):
            try:
                # Probeer eerst als JSON te parsen
                embedding1 = json.loads(embedding1)
            except json.JSONDecodeError:
                try:
                    # Probeer als Python literal (voor string representation van lijst)
                    import ast
                    embedding1 = ast.literal_eval(embedding1)
                except (ValueError, SyntaxError):
                    logger.warning(f"Kon embedding1 niet parsen: {embedding1[:100]}...")
                    return 0.0
                
        if isinstance(embedding2, str):
            try:
                # Probeer eerst als JSON te parsen
                embedding2 = json.loads(embedding2)
            except json.JSONDecodeError:
                try:
                    # Probeer als Python literal (voor string representation van lijst)
                    import ast
                    embedding2 = ast.literal_eval(embedding2)
                except (ValueError, SyntaxError):
                    logger.warning(f"Kon embedding2 niet parsen: {embedding2[:100]}...")
                    return 0.0
        
        # Als het al numpy arrays zijn, converteer naar lijsten
        if hasattr(embedding1, 'tolist'):
            embedding1 = embedding1.tolist()
        if hasattr(embedding2, 'tolist'):
            embedding2 = embedding2.tolist()
        
        # Controleer of embeddings geldige lijsten zijn
        if not isinstance(embedding1, (list, tuple)) or not isinstance(embedding2, (list, tuple)):
            logger.warning(f"Embeddings zijn geen lijsten: {type(embedding1)}, {type(embedding2)}")
            return 0.0
            
        if len(embedding1) == 0 or len(embedding2) == 0:
            logger.warning("Een van de embeddings is leeg")
            return 0.0
            
        vec1 = np.array(embedding1, dtype=np.float32)
        vec2 = np.array(embedding2, dtype=np.float32)
        
        # Controleer of de vectoren dezelfde dimensie hebben
        if vec1.shape != vec2.shape:
            logger.warning(f"Embeddings hebben verschillende dimensies: {vec1.shape} vs {vec2.shape}")
            return 0.0
        
        # Bereken cosine similarity
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
            
        similarity = dot_product / (norm1 * norm2)
        return float(similarity)
        
    except Exception as e:
        logger.error(f"Fout bij berekenen cosine similarity: {str(e)}")
        return 0.0


def generate_matches():
    """Genereer de top 250 matches op basis van cosine similarity tussen embeddings."""
    from .models import Match
    import numpy as np
    
    try:
        logger.info("Start genereren matches...")
        
        # Detecteer database type en gebruik juiste filters
        from django.db import connection
        
        is_postgresql = 'postgresql' in connection.vendor
        
        if is_postgresql:
            # PostgreSQL met VectorField - gebruik eenvoudigere filters
            candidates = Candidate.objects.filter(
                embedding__isnull=False,
                embed_status='completed'
            )
            
            vacatures = Vacature.objects.filter(
                embedding__isnull=False,
                actief=True
            )
        else:
            # SQLite met JSONField
            candidates = Candidate.objects.filter(
                embedding__isnull=False,
                embed_status='completed'
            ).exclude(embedding__isnull=True)
            
            vacatures = Vacature.objects.filter(
                embedding__isnull=False,
                actief=True
            ).exclude(embedding__isnull=True)
        
        logger.info(f"Gevonden {candidates.count()} kandidaten en {vacatures.count()} vacatures met embeddings")
        
        if not candidates.exists() or not vacatures.exists():
            logger.warning("Geen kandidaten of vacatures met embeddings gevonden")
            return
        
        # Bereken alle combinaties
        matches_data = []
        
        for candidate in candidates:
            # Check of embedding bestaat en niet leeg is
            if not candidate.embedding:
                continue
            if isinstance(candidate.embedding, list) and len(candidate.embedding) == 0:
                continue
            if isinstance(candidate.embedding, str) and candidate.embedding.strip() == '':
                continue
            if isinstance(candidate.embedding, str) and candidate.embedding.strip() == '[]':
                continue
                
            for vacature in vacatures:
                # Check of embedding bestaat en niet leeg is
                if not vacature.embedding:
                    continue
                if isinstance(vacature.embedding, list) and len(vacature.embedding) == 0:
                    continue
                if isinstance(vacature.embedding, str) and vacature.embedding.strip() == '':
                    continue
                if isinstance(vacature.embedding, str) and vacature.embedding.strip() == '[]':
                    continue
                
                try:
                    # Bereken cosine similarity
                    similarity = calculate_cosine_similarity(candidate.embedding, vacature.embedding)
                    
                    # Converteer naar percentage (0-100)
                    score = round(similarity * 100, 1)
                    
                    # Alleen positieve scores behouden
                    if score > 0:
                        matches_data.append({
                            'candidate': candidate,
                            'vacature': vacature,
                            'score': score,
                            'similarity': similarity
                        })
                        
                except Exception as e:
                    logger.error(f"Fout bij berekenen similarity voor kandidaat {candidate.id} en vacature {vacature.id}: {str(e)}")
                    continue
        
        # Sorteer op score (hoogste eerst) en neem top 250
        matches_data.sort(key=lambda x: x['score'], reverse=True)
        top_matches = matches_data[:250]
        
        logger.info(f"Gevonden {len(top_matches)} matches, opslaan in database...")
        
        # Verwijder bestaande matches
        Match.objects.all().delete()
        logger.info("Bestaande matches verwijderd")
        
        # Maak nieuwe matches
        created_count = 0
        for match_data in top_matches:
            try:
                match, created = Match.objects.get_or_create(
                    kandidaat=match_data['candidate'],
                    vacature=match_data['vacature'],
                    defaults={
                        'score': match_data['score'],
                        'afstand_berekend': False
                    }
                )
                
                if created:
                    created_count += 1
                else:
                    # Update bestaande match
                    match.score = match_data['score']
                    match.afstand_berekend = False
                    match.save()
                    created_count += 1
                    
            except Exception as e:
                logger.error(f"Fout bij opslaan match voor kandidaat {match_data['candidate'].id} en vacature {match_data['vacature'].id}: {str(e)}")
                continue
        
        logger.info(f"Succesvol {created_count} matches opgeslagen")
        
        # Log statistieken
        if created_count > 0:
            avg_score = np.mean([m['score'] for m in top_matches])
            max_score = max([m['score'] for m in top_matches])
            min_score = min([m['score'] for m in top_matches])
            
            logger.info(f"Match statistieken - Gemiddeld: {avg_score:.1f}%, Max: {max_score:.1f}%, Min: {min_score:.1f}%")
        
        return created_count
        
    except Exception as e:
        logger.error(f"Fout bij genereren matches: {str(e)}")
        raise


def calculate_distance_for_match(match):
    """Bereken afstand tussen kandidaat en vacature locatie."""
    import math
    import requests
    
    try:
        # Haal coördinaten op voor kandidaat
        lat1, lon1 = match.kandidaat.latitude, match.kandidaat.longitude
        
        # Geocode vacature plaatsnaam naar coördinaten
        vacature_plaats = match.vacature.plaats
        vacature_postcode = match.vacature.postcode
        
        if not vacature_plaats:
            logger.warning(f"Geen plaatsnaam voor vacature {match.vacature.id}")
            return None
            
        # Geocode vacature plaats met verbeterde logica
        short_plaats = vacature_plaats.split(',')[0].strip() if vacature_plaats else ""
        
        if not short_plaats:
            logger.warning(f"Geen plaatsnaam voor vacature {match.vacature.id}")
            return None
        
        # Probeer verschillende adres combinaties voor vacature
        address_attempts = []
        
        # 1. Postcode + plaats (als beide beschikbaar)
        if vacature_postcode:
            formatted_postcode = vacature_postcode.replace(' ', '')
            address_attempts.append(f"{formatted_postcode} {short_plaats}")
        
        # 2. Alleen plaatsnaam (altijd als fallback)
        address_attempts.append(short_plaats)
        
        lat2, lon2 = None, None
        
        # Probeer PDOK met verschillende adres combinaties
        for i, address in enumerate(address_attempts):
            if lat2 is not None and lon2 is not None:
                break  # Al gevonden
                
            try:
                logger.info(f"Vacature geocoding poging {i+1}: {address}")
                pdok_url = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/suggest"
                params = {
                    'fl': 'weergavenaam,centroide_ll',
                    'q': address,
                    'rows': 1
                }
                
                response = requests.get(pdok_url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('response', {}).get('docs'):
                        doc = data['response']['docs'][0]
                        if 'centroide_ll' in doc:
                            centroide = doc['centroide_ll']
                            if centroide.startswith('POINT('):
                                coords = centroide[6:-1]
                                lon2, lat2 = coords.split(' ')
                            else:
                                lat2, lon2 = centroide.split(' ')
                            lat2, lon2 = float(lat2), float(lon2)
                            logger.info(f"Vacature geocoding succesvol met: {address}")
                            break
            except Exception as e:
                logger.warning(f"Vacature geocoding gefaald met '{address}': {str(e)}")
                continue
        
        # Fallback naar Nominatim
        if lat2 is None or lon2 is None:
            for i, address in enumerate(address_attempts):
                if lat2 is not None and lon2 is not None:
                    break  # Al gevonden
                    
                try:
                    logger.info(f"Vacature Nominatim poging {i+1}: {address}")
                    nominatim_url = "https://nominatim.openstreetmap.org/search"
                    params = {
                        'q': address,
                        'format': 'json',
                        'limit': 1,
                        'countrycodes': 'nl'
                    }
                    
                    response = requests.get(nominatim_url, params=params, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        if data:
                            lat2 = float(data[0]['lat'])
                            lon2 = float(data[0]['lon'])
                            logger.info(f"Vacature Nominatim succesvol met: {address}")
                            break
                except Exception as e:
                    logger.warning(f"Vacature Nominatim gefaald met '{address}': {str(e)}")
                    continue
        
        if not lat2 or not lon2:
            logger.warning(f"Kon vacature plaats {vacature_plaats} niet geocoderen")
            return None
        
        if not all([lat1, lon1, lat2, lon2]):
            logger.warning(f"Ontbrekende coördinaten voor match {match.id}")
            return None
        
        # Haversine formule voor afstand berekening
        R = 6371  # Aardstraal in kilometers
        
        # Converteer naar radialen
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)
        
        # Verschil in coördinaten
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        
        # Haversine formule
        a = (math.sin(dlat/2)**2 + 
             math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2)
        c = 2 * math.asin(math.sqrt(a))
        
        # Afstand in kilometers
        distance = R * c
        
        return round(distance, 1)
        
    except Exception as e:
        logger.error(f"Fout bij berekenen afstand voor match {match.id}: {str(e)}")
        return None


def geocode_place(place_name):
    """Geocode een plaatsnaam naar coördinaten."""
    import requests
    
    try:
        # Probeer eerst PDOK
        pdok_url = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/lookup"
        params = {
            'fl': 'weergavenaam,centroide_ll',
            'q': place_name,
            'rows': 1
        }
        
        response = requests.get(pdok_url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('response', {}).get('docs'):
                doc = data['response']['docs'][0]
                if 'centroide_ll' in doc:
                    lat, lon = doc['centroide_ll'].split(' ')
                    return float(lat), float(lon)
    except Exception as e:
        logger.warning(f"PDOK geocoding gefaald voor {place_name}: {str(e)}")
    
    # Fallback naar Nominatim
    try:
        nominatim_url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': f"{place_name}, Nederland",
            'format': 'json',
            'limit': 1,
            'countrycodes': 'nl'
        }
        
        response = requests.get(nominatim_url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data:
                lat = float(data[0]['lat'])
                lon = float(data[0]['lon'])
                return lat, lon
    except Exception as e:
        logger.warning(f"Nominatim geocoding gefaald voor {place_name}: {str(e)}")
    
    return None, None
