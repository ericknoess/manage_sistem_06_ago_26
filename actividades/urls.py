# actividades/urls.py

from django.urls import path, include
from django.views.generic import TemplateView
from rest_framework.routers import DefaultRouter
from .views import EquipoViewSet, MaterialInsumoViewSet, ActividadSemanalViewSet

# Configuración del enrutador para la API REST
router = DefaultRouter()
router.register(r'equipos', EquipoViewSet, basename='equipo')
router.register(r'materiales', MaterialInsumoViewSet, basename='material')
router.register(r'actividades-semanales', ActividadSemanalViewSet, basename='actividad-semanal')

urlpatterns = [
    # Endpoints REST expuestos bajo /api/
    path('api/', include(router.urls)),
    
    # Vista HTML del Tablero Operativo Semanal
    # Usamos TemplateView para renderizar directamente el template, 
    # asumiendo que tu archivo se encuentra en 'actividades/index.html'
    path('tablero/', TemplateView.as_view(template_name='actividades/index.html'), name='tablero-semanal'),
]