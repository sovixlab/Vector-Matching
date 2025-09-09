from django.db import models
from django.contrib.auth.models import User
import os
from django.conf import settings


class Backup(models.Model):
    """Model voor backup records."""
    
    BACKUP_TYPES = [
        ('full', 'Volledige Systeem Backup'),
        ('database', 'Database Structuur'),
        ('schema', 'Alleen Schema (Geen Data)'),
        ('config', 'Systeem Configuratie'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'In Wachtrij'),
        ('running', 'Bezig'),
        ('completed', 'Voltooid'),
        ('failed', 'Mislukt'),
    ]
    
    name = models.CharField(max_length=255, help_text="Naam van de backup")
    backup_type = models.CharField(max_length=20, choices=BACKUP_TYPES, default='full')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    file_path = models.CharField(max_length=500, blank=True, null=True, help_text="Pad naar backup bestand")
    file_size = models.BigIntegerField(default=0, help_text="Grootte van backup bestand in bytes")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    notes = models.TextField(blank=True, help_text="Notities over de backup")
    error_message = models.TextField(blank=True, help_text="Foutmelding bij mislukte backup")
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Backup"
        verbose_name_plural = "Backups"
    
    def __str__(self):
        return f"{self.name} ({self.get_backup_type_display()}) - {self.get_status_display()}"
    
    @property
    def file_size_mb(self):
        """Geeft bestandsgrootte terug in MB."""
        return round(self.file_size / (1024 * 1024), 2)
    
    @property
    def is_completed(self):
        """Geeft terug of backup voltooid is."""
        return self.status == 'completed'
    
    @property
    def is_failed(self):
        """Geeft terug of backup mislukt is."""
        return self.status == 'failed'
    
    def get_absolute_url(self):
        """Geeft URL terug voor backup detail."""
        from django.urls import reverse
        return reverse('backup_system:backup_detail', kwargs={'pk': self.pk})