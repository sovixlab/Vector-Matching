from django.contrib import admin
from .models import Document, Candidate


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'created_at', 'updated_at']
    list_filter = ['created_at', 'updated_at']
    search_fields = ['title', 'content']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'city', 'education_level', 'years_experience', 'embed_status', 'processing_step', 'created_at']
    list_filter = ['embed_status', 'processing_step', 'created_at', 'updated_at']
    search_fields = ['name', 'email', 'education_level', 'city', 'phone']
    readonly_fields = ['created_at', 'updated_at', 'cv_text', 'extract_json', 'profile_text', 'embedding', 'latitude', 'longitude']
    list_editable = ['embed_status']
    fieldsets = (
        ('Basis Informatie', {
            'fields': ('name', 'email', 'phone')
        }),
        ('Adres', {
            'fields': ('street', 'house_number', 'postal_code', 'city', 'latitude', 'longitude')
        }),
        ('Professioneel', {
            'fields': ('education_level', 'job_titles', 'years_experience')
        }),
        ('CV & Verwerking', {
            'fields': ('cv_pdf', 'cv_text', 'extract_json', 'profile_text', 'embedding')
        }),
        ('Status', {
            'fields': ('embed_status', 'processing_step', 'error_message')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
