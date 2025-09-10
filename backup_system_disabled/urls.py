from django.urls import path
from . import views

app_name = 'backup_system'

urlpatterns = [
    path('', views.backup_list_view, name='backup_list'),
    path('stats/', views.backup_stats_view, name='backup_stats'),
    path('create/', views.create_backup_view, name='create_backup'),
    path('<int:pk>/', views.backup_detail_view, name='backup_detail'),
    path('<int:pk>/download/', views.download_backup_view, name='download_backup'),
    path('<int:pk>/delete/', views.delete_backup_view, name='delete_backup'),
    path('<int:pk>/restore/', views.restore_backup_view, name='restore_backup'),
    path('<int:pk>/status/', views.backup_status_view, name='backup_status'),
]
