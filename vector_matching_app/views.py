from django.shortcuts import render
from django.http import JsonResponse
from django.db import connection
from django.conf import settings
import json


def index(request):
    """Homepage met DaisyUI hero component."""
    return render(request, 'index.html')


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
    openai_status = "ok" if settings.OPENAI_API_KEY else "missing"
    
    response_data = {
        "status": "ok",
        "database": db_status,
        "openai": openai_status,
        "debug": settings.DEBUG,
    }
    
    return JsonResponse(response_data)
