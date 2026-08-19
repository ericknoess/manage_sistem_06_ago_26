# core/urls.py (o el archivo urls.py principal de tu proyecto)

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('roster/', include('roster.urls')),
    path('api/', include('roster.api_urls')),
    
    # Integración de los endpoints REST del módulo de Actividades y Recursos Semanales
    path('', include('actividades.urls')),
]

# Configuración para servir archivos multimedia en entorno de desarrollo (DEBUG = True)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)