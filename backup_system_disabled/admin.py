from django.contrib import admin
from .models import Backup


@admin.register(Backup)
class BackupAdmin(admin.ModelAdmin):
    list_display = ['name', 'backup_type', 'status', 'file_size_mb', 'created_at', 'created_by']
    list_filter = ['backup_type', 'status', 'created_at']
    search_fields = ['name', 'notes', 'created_by__username']
    readonly_fields = ['file_size', 'created_at', 'completed_at']
    ordering = ['-created_at']
    
    fieldsets = (
        ('Backup Informatie', {
            'fields': ('name', 'backup_type', 'status', 'notes')
        }),
        ('Bestand Informatie', {
            'fields': ('file_path', 'file_size', 'file_size_mb')
        }),
        ('Tijdsinformatie', {
            'fields': ('created_at', 'completed_at')
        }),
        ('Gebruiker', {
            'fields': ('created_by',)
        }),
        ('Foutmelding', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        }),
    )
    
    def file_size_mb(self, obj):
        return f"{obj.file_size_mb} MB"
    file_size_mb.short_description = 'Grootte (MB)'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('created_by')