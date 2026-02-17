from django.urls import path
from . import views

urlpatterns = [
    path('analyze/', views.analyze_fpl, name='api_analyze_fpl'),
    path('analyze_section/', views.analyze_section, name='api_analyze_section'),
    path('parse_pdf/', views.parse_pdf, name='api_parse_pdf'),
    path('parse_llm/', views.parse_with_llm, name='api_parse_llm'),
    path('upload/', views.upload_view, name='api_upload_view'),
    path('submit_analysis/', views.submit_analysis, name='api_submit_analysis'),
    path('telegram_auth/', views.telegram_auth, name='api_telegram_auth'),
    path('telegram_status/', views.telegram_status, name='api_telegram_status'),
]
