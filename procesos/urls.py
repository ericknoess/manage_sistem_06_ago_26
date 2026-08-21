# procesos/urls.py

from django.urls import path, include
from django.views.generic import TemplateView  # <-- NUEVA IMPORTACIÓN
from rest_framework.routers import DefaultRouter
from .views import (
    ProcesoMaestroViewSet,
    OperacionProcesoViewSet,
    LoteProduccionViewSet,
    FaseLoteViewSet,
    AsignacionFaseOperadorViewSet
)

# Instanciamos el enrutador por defecto de DRF
router = DefaultRouter()

# 1. Rutas de Datos Maestros (Plantillas CPM)
router.register(r'procesos-maestros', ProcesoMaestroViewSet, basename='proceso-maestro')
router.register(r'operaciones-proceso', OperacionProcesoViewSet, basename='operacion-proceso')

# 2. Rutas Transaccionales (Ejecución de Lotes / eBR)
router.register(r'lotes', LoteProduccionViewSet, basename='lote')
router.register(r'fases-lote', FaseLoteViewSet, basename='fase-lote')
router.register(r'asignaciones-operador', AsignacionFaseOperadorViewSet, basename='asignacion-operador')

urlpatterns = [
    # Ruta visual para el Tablero de Piso de Planta (Ejecución)
    path('ejecucion/', TemplateView.as_view(template_name='procesos/ejecucion.html'), name='ejecucion-lotes'),
    # Ruta visual para el Tablero de Piso de Planta (Ejecución)
    path('procesos/', TemplateView.as_view(template_name='procesos/index.html'), name='ejecucion-lotes'),
    # Rutas generadas automáticamente por el router de la API
    path('api/', include(router.urls)),
]