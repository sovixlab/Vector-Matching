from django.db import models
from pgvector.django import VectorField
from django.contrib.auth.models import User


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


class Prompt(models.Model):
    """Model voor embedding prompts met versiegeschiedenis."""
    
    PROMPT_TYPES = [
        ('cv_parsing', 'CV Parsing'),
        ('profile_summary', 'Profiel Samenvatting'),
        ('custom', 'Aangepast'),
    ]
    
    name = models.CharField(max_length=100)
    prompt_type = models.CharField(max_length=20, choices=PROMPT_TYPES)
    content = models.TextField()
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='versions')
    
    class Meta:
        ordering = ['-version', '-created_at']
        unique_together = ['name', 'version']
    
    def __str__(self):
        return f"{self.name} v{self.version}"
    
    def create_new_version(self, new_content, user=None):
        """Maak een nieuwe versie van deze prompt."""
        # Deactiveer huidige versie
        self.is_active = False
        self.save()
        
        # Maak nieuwe versie
        new_version = Prompt.objects.create(
            name=self.name,
            prompt_type=self.prompt_type,
            content=new_content,
            version=self.version + 1,
            is_active=True,
            created_by=user,
            parent=self
        )
        return new_version
    
    @property
    def all_versions(self):
        """Krijg alle versies van deze prompt."""
        if self.parent:
            return Prompt.objects.filter(parent=self.parent).order_by('-version')
        return Prompt.objects.filter(parent=self).order_by('-version')
    
    @classmethod
    def get_active_prompt(cls, prompt_type):
        """Krijg de actieve prompt voor een bepaald type."""
        return cls.objects.filter(prompt_type=prompt_type, is_active=True).first()


class PromptLog(models.Model):
    """Log voor prompt wijzigingen."""
    
    ACTION_TYPES = [
        ('created', 'Aangemaakt'),
        ('updated', 'Bijgewerkt'),
        ('activated', 'Geactiveerd'),
        ('deactivated', 'Gedeactiveerd'),
        ('deleted', 'Verwijderd'),
    ]
    
    prompt = models.ForeignKey(Prompt, on_delete=models.CASCADE, related_name='logs')
    action = models.CharField(max_length=20, choices=ACTION_TYPES)
    old_content = models.TextField(blank=True, null=True)
    new_content = models.TextField(blank=True, null=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.prompt.name} - {self.get_action_display()} ({self.timestamp})"
