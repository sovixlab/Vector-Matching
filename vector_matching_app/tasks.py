import json
import logging
import os
import requests
from celery import shared_task, chain
from django.conf import settings
from django.core.files.base import ContentFile
from .models import Candidate
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


@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 60})
def extract_pdf_text(self, candidate_id):
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
        
        # Sla tekst op
        candidate.cv_text = text.strip()
        candidate.save(update_fields=['cv_text', 'updated_at'])
        
        logger.info(f"PDF tekst geëxtraheerd voor kandidaat {candidate_id}")
        return candidate_id
        
    except Exception as e:
        logger.error(f"Fout bij PDF extractie voor kandidaat {candidate_id}: {str(e)}")
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('failed', 'PDF tekst extractie', str(e))
        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 60})
def parse_cv_to_fields(self, candidate_id):
    """Parse CV tekst naar gestructureerde velden met OpenAI."""
    try:
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('processing', 'CV parsing')
        
        if not candidate.cv_text:
            raise ValueError("Geen CV tekst gevonden")
        
        # OpenAI prompt
        prompt = """Je bent een NL data-extractie-assistent. Antwoord uitsluitend met JSON met deze sleutels:
{ "volledige_naam": "...", "email": "...", "telefoonnummer": "...", "straat": "...", "huisnummer": "...", "postcode": "...", "woonplaats": "...", "opleidingsniveau": "...", "functietitels": ["..."], "jaren_ervaring": 0 }

CV tekst:
""" + candidate.cv_text[:4000]  # Limiteer input voor OpenAI
        
        # OpenAI API call
        openai_client = get_openai_client()
        messages = [
            {"role": "system", "content": "Je bent een expert in het extraheren van gestructureerde data uit Nederlandse CV's. Antwoord altijd met geldige JSON."},
            {"role": "user", "content": prompt}
        ]
        
        response = openai_client.chat(messages, model="gpt-3.5-turbo")
        
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
        
        # Valideer en normaliseer data
        extracted_data = {
            'volledige_naam': extracted_data.get('volledige_naam', ''),
            'email': extracted_data.get('email', ''),
            'telefoonnummer': extracted_data.get('telefoonnummer', ''),
            'straat': extracted_data.get('straat', ''),
            'huisnummer': extracted_data.get('huisnummer', ''),
            'postcode': extracted_data.get('postcode', ''),
            'woonplaats': extracted_data.get('woonplaats', ''),
            'opleidingsniveau': extracted_data.get('opleidingsniveau', ''),
            'functietitels': extracted_data.get('functietitels', []),
            'jaren_ervaring': extracted_data.get('jaren_ervaring', 0)
        }
        
        # Update candidate velden
        candidate.name = extracted_data['volledige_naam']
        candidate.email = extracted_data['email']
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


@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 60})
def generate_profile_summary_text(self, candidate_id):
    """Genereer profiel samenvatting met OpenAI."""
    try:
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('processing', 'Profiel samenvatting')
        
        if not candidate.cv_text:
            raise ValueError("Geen CV tekst gevonden")
        
        # OpenAI prompt
        prompt = """Schrijf één zakelijke Nederlandse alinea (80–140 woorden) die de kandidaat samenvat voor matching. Benoem opleiding, jaren ervaring, functietitels, domeinen, vaardigheden, talen, beschikbaarheid. Gebruik alleen info uit de CV.

CV tekst:
""" + candidate.cv_text[:4000]  # Limiteer input voor OpenAI
        
        # OpenAI API call
        openai_client = get_openai_client()
        messages = [
            {"role": "system", "content": "Je bent een expert in het schrijven van zakelijke profiel samenvattingen voor Nederlandse kandidaten. Schrijf helder en beknopt."},
            {"role": "user", "content": prompt}
        ]
        
        response = openai_client.chat(messages, model="gpt-3.5-turbo")
        
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


@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 60})
def embed_profile_text(self, candidate_id):
    """Embed profiel tekst met OpenAI."""
    try:
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('processing', 'Embedding generatie')
        
        if not candidate.profile_text:
            raise ValueError("Geen profiel tekst gevonden")
        
        # OpenAI embedding
        openai_client = get_openai_client()
        embedding = openai_client.embed(candidate.profile_text, model="text-embedding-3-small")
        
        # Sla embedding op
        candidate.embedding = embedding
        candidate.save(update_fields=['embedding', 'updated_at'])
        
        logger.info(f"Embedding gegenereerd voor kandidaat {candidate_id}")
        return candidate_id
        
    except Exception as e:
        logger.error(f"Fout bij embedding voor kandidaat {candidate_id}: {str(e)}")
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('failed', 'Embedding generatie', str(e))
        raise


@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 60})
def geocode_candidate(self, candidate_id):
    """Geocode kandidaat locatie met PDOK en Nominatim."""
    try:
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('processing', 'Geocoding')
        
        # Bereid adres voor
        address_parts = []
        if candidate.street:
            address_parts.append(candidate.street)
        if candidate.house_number:
            address_parts.append(candidate.house_number)
        if candidate.postal_code:
            address_parts.append(candidate.postal_code)
        if candidate.city:
            address_parts.append(candidate.city)
        
        if not address_parts:
            raise ValueError("Geen adres informatie gevonden")
        
        address = ', '.join(address_parts)
        lat, lon = None, None
        
        # Probeer eerst PDOK Locatieserver
        try:
            pdok_url = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/lookup"
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
                        lat, lon = doc['centroide_ll'].split(' ')
                        lat, lon = float(lat), float(lon)
                        logger.info(f"PDOK geocoding succesvol voor kandidaat {candidate_id}")
        except Exception as e:
            logger.warning(f"PDOK geocoding gefaald voor kandidaat {candidate_id}: {str(e)}")
        
        # Fallback naar Nominatim
        if lat is None or lon is None:
            try:
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
                        logger.info(f"Nominatim geocoding succesvol voor kandidaat {candidate_id}")
            except Exception as e:
                logger.warning(f"Nominatim geocoding gefaald voor kandidaat {candidate_id}: {str(e)}")
        
        if lat is not None and lon is not None:
            candidate.latitude = lat
            candidate.longitude = lon
            candidate.embed_status = 'completed'
            candidate.processing_step = 'Voltooid'
            candidate.save(update_fields=['latitude', 'longitude', 'embed_status', 'processing_step', 'updated_at'])
            logger.info(f"Geocoding voltooid voor kandidaat {candidate_id}: {lat}, {lon}")
        else:
            raise ValueError("Geen locatie gevonden via PDOK of Nominatim")
        
        return candidate_id
        
    except Exception as e:
        logger.error(f"Fout bij geocoding voor kandidaat {candidate_id}: {str(e)}")
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('failed', 'Geocoding', str(e))
        raise


@shared_task
def process_candidate_pipeline(candidate_id):
    """Start de volledige verwerkingspipeline voor een kandidaat."""
    try:
        # Chain alle tasks
        workflow = chain(
            extract_pdf_text.s(candidate_id),
            parse_cv_to_fields.s(),
            generate_profile_summary_text.s(),
            embed_profile_text.s(),
            geocode_candidate.s()
        )
        
        result = workflow.apply_async()
        logger.info(f"Verwerkingspipeline gestart voor kandidaat {candidate_id}")
        return result.id
        
    except Exception as e:
        logger.error(f"Fout bij starten pipeline voor kandidaat {candidate_id}: {str(e)}")
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('failed', 'Pipeline start', str(e))
        raise


@shared_task
def reprocess_candidate(candidate_id):
    """Herstart de verwerkingspipeline voor een kandidaat."""
    try:
        candidate = Candidate.objects.get(id=candidate_id)
        candidate.update_status('queued', 'Opnieuw verwerken')
        candidate.error_message = ''
        candidate.save(update_fields=['embed_status', 'processing_step', 'error_message', 'updated_at'])
        
        # Start pipeline opnieuw
        return process_candidate_pipeline.delay(candidate_id)
        
    except Exception as e:
        logger.error(f"Fout bij herstarten pipeline voor kandidaat {candidate_id}: {str(e)}")
        raise
