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
    """Model voor kandidaten met CV uploads."""
    
    EMBED_STATUS_CHOICES = [
        ('queued', 'In wachtrij'),
        ('processing', 'Wordt verwerkt'),
        ('completed', 'Voltooid'),
        ('failed', 'Mislukt'),
    ]
    
    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    education_level = models.CharField(max_length=100, blank=True)
    years_experience = models.IntegerField(null=True, blank=True)
    cv_pdf = models.FileField(upload_to='cvs/', blank=True, null=True)
    embed_status = models.CharField(
        max_length=20, 
        choices=EMBED_STATUS_CHOICES, 
        default='queued'
    )
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
