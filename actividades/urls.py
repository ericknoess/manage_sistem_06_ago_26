# actividades/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import EquipoViewSet, MaterialInsumoViewSet, ActividadSemanalViewSet, tablero_semanal_view

# Configuración del enrutador para la API REST del módulo de Actividades
router = DefaultRouter()
router.register(r'equipos', EquipoViewSet)
router.register(r'materiales', MaterialInsumoViewSet)
router.register(r'actividades-semanales', ActividadSemanalViewSet)

urlpatterns = [
    # Endpoints REST expuestos bajo /api/
    path('api/', include(router.urls)),
    
    # Vista HTML del Tablero Operativo Semanal (Maqueta Integrada)
    path('tablero/', tablero_semanal_view, name='tablero-semanal'),
]