from django.urls import path
from . import views

app_name = 'vector_matching_app'

urlpatterns = [
    path('', views.index, name='index'),
    path('healthz', views.health_check, name='health_check'),
    path('kandidaten/', views.kandidaten_list_view, name='kandidaten'),
    path('kandidaten/upload/', views.kandidaten_upload_view, name='kandidaten_upload'),
    path('kandidaten/<int:candidate_id>/', views.kandidaat_detail_view, name='kandidaat_detail'),
    path('kandidaten/<int:candidate_id>/reprocess/', views.kandidaat_reprocess_view, name='kandidaat_reprocess'),
    path('kandidaten/<int:candidate_id>/cv/', views.kandidaat_cv_view, name='kandidaat_cv'),
    path('kandidaten/<int:candidate_id>/delete/', views.kandidaat_delete_view, name='kandidaat_delete'),
    path('kandidaten/<int:candidate_id>/edit/', views.kandidaat_edit_view, name='kandidaat_edit'),
    path('kandidaten/bulk-delete/', views.kandidaten_bulk_delete_view, name='kandidaten_bulk_delete'),
    path('kandidaten/bulk-reprocess/', views.kandidaten_bulk_reprocess_view, name='kandidaten_bulk_reprocess'),
    
    # Vacature Management URLs
    path('vacatures/', views.vacatures_list_view, name='vacatures'),
    path('vacatures/update/', views.vacatures_update_view, name='vacatures_update'),
    
    # API URLs
    path('api/vacatures/update/', views.api_vacatures_update_view, name='api_vacatures_update'),
    
    # Prompt Management URLs
    path('prompts/', views.prompts_list_view, name='prompts'),
    path('prompts/create/', views.prompt_create_view, name='prompt_create'),
    path('prompts/<int:prompt_id>/', views.prompt_detail_view, name='prompt_detail'),
    path('prompts/<int:prompt_id>/edit/', views.prompt_edit_view, name='prompt_edit'),
    path('prompts/<int:prompt_id>/activate/', views.prompt_activate_view, name='prompt_activate'),
    path('prompts/logs/', views.prompt_logs_view, name='prompt_logs'),
    
    # Authentication URLs
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
]
