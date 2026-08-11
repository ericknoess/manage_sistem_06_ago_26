# core/urls.py

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('roster/', include('roster.urls')),
    path('api/', include('roster.api_urls')),
]

# Configuración para servir archivos multimedia en entorno de desarrollo (DEBUG = True)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)