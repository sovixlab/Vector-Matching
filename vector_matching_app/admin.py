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
    list_display = ['name', 'email', 'education_level', 'years_experience', 'embed_status', 'created_at']
    list_filter = ['embed_status', 'created_at', 'updated_at']
    search_fields = ['name', 'email', 'education_level']
    readonly_fields = ['created_at', 'updated_at']
    list_editable = ['embed_status']
