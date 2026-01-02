"""
URL configuration for SignifyAI project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import FileResponse
import os

def serve_results_file(request, filename):
    """Serve files from results folder"""
    file_path = settings.RESULTS_FOLDER / filename
    if os.path.exists(file_path):
        return FileResponse(open(file_path, 'rb'))
    from django.http import Http404
    raise Http404("File not found")

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Main apps
    path('', include('apps.contracts.urls')),
    path('ocr/', include('apps.ocr.urls')),
    path('api/', include('apps.api.urls')),
    
    # Results file serving
    path('results/<str:filename>', serve_results_file, name='serve_results'),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
