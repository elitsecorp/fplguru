from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('app.api.urls')),
    path('analyze/result/', TemplateView.as_view(template_name='analyze_result.html'), name='analyze_result'),
    path('', TemplateView.as_view(template_name='analyze.html'), name='home'),
]
