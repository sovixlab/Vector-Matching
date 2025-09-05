from django.db import models
from pgvector.django import VectorField


class Document(models.Model):
    """Model voor documenten met vector embeddings."""
    
    title = models.CharField(max_length=255)
    content = models.TextField()
    embedding = VectorField(dimensions=1536, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return self.title


class Candidate(models.Model):
    """Model voor kandidaten met CV uploads en verwerking."""
    
    EMBED_STATUS_CHOICES = [
        ('queued', 'In wachtrij'),
        ('processing', 'Wordt verwerkt'),
        ('completed', 'Voltooid'),
        ('failed', 'Mislukt'),
    ]
    
    # Basis informatie
    name = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    
    # Adres informatie
    street = models.CharField(max_length=255, blank=True, null=True)
    house_number = models.CharField(max_length=10, blank=True, null=True)
    postal_code = models.CharField(max_length=10, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    
    # Professionele informatie
    education_level = models.CharField(max_length=100, blank=True)
    job_titles = models.JSONField(default=list, blank=True)  # Lijst van functietitels
    years_experience = models.IntegerField(null=True, blank=True)
    
    # CV bestanden en verwerking
    cv_pdf = models.FileField(upload_to='cvs/', blank=True, null=True)
    cv_text = models.TextField(blank=True)  # Geëxtraheerde tekst uit PDF
    extract_json = models.JSONField(default=dict, blank=True)  # Gestructureerde data uit CV
    profile_text = models.TextField(blank=True)  # Samenvatting voor matching
    
    # Embedding en locatie
    embedding = VectorField(dimensions=1536, null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    
    # Status tracking
    embed_status = models.CharField(
        max_length=20, 
        choices=EMBED_STATUS_CHOICES, 
        default='queued'
    )
    processing_step = models.CharField(max_length=50, blank=True)  # Huidige stap in pipeline
    error_message = models.TextField(blank=True)  # Foutmelding bij falen
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name or f"Kandidaat {self.id}"
    
    @property
    def embed_status_badge_class(self):
        """Retourneert de juiste badge class voor de embed status."""
        status_classes = {
            'completed': 'badge-success',
            'queued': 'badge-warning',
            'processing': 'badge-info',
            'failed': 'badge-error',
        }
        return status_classes.get(self.embed_status, 'badge-neutral')
    
    @property
    def embed_status_icon(self):
        """Retourneert het juiste icoon voor de embed status."""
        status_icons = {
            'completed': '✔',
            'queued': '⏳',
            'processing': '🔄',
            'failed': '❌',
        }
        return status_icons.get(self.embed_status, '❓')
    
    @property
    def full_address(self):
        """Retourneert het volledige adres."""
        parts = [self.street, self.house_number, self.postal_code, self.city]
        return ' '.join(filter(None, parts))
    
    def update_status(self, status, step='', error=''):
        """Update de verwerkingsstatus."""
        self.embed_status = status
        self.processing_step = step
        if error:
            self.error_message = error
        self.save(update_fields=['embed_status', 'processing_step', 'error_message', 'updated_at'])
