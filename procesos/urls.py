# procesos/urls.py

from django.urls import path, include
from django.views.generic import TemplateView
from rest_framework.routers import DefaultRouter
from .views import (
    ProcesoMaestroViewSet,
    EtapaProcesoViewSet,
    OperacionProcesoViewSet,
    LoteProduccionViewSet,
    FaseLoteViewSet,
    AsignacionFaseOperadorViewSet
)

# Instanciamos el enrutador por defecto de DRF
router = DefaultRouter()

# 1. Rutas de Datos Maestros (Plantillas CPM y Estructura ISA-88)
router.register(r'procesos-maestros', ProcesoMaestroViewSet, basename='proceso-maestro')
router.register(r'etapas-proceso', EtapaProcesoViewSet, basename='etapa-proceso')
router.register(r'operaciones-proceso', OperacionProcesoViewSet, basename='operacion-proceso')

# 2. Rutas Transaccionales (Ejecución de Lotes / eBR)
router.register(r'lotes', LoteProduccionViewSet, basename='lote')
router.register(r'fases-lote', FaseLoteViewSet, basename='fase-lote')
router.register(r'asignaciones-operador', AsignacionFaseOperadorViewSet, basename='asignacion-operador')

urlpatterns = [
    # Ruta visual para el Tablero de Piso de Planta (Ejecución eBR)
    path('ejecucion/', TemplateView.as_view(template_name='procesos/ejecucion.html'), name='ejecucion-lotes'),
    
    # Ruta visual para el Tablero de Planificación y Asignación Semanal (MES)
    path('planificacion/', TemplateView.as_view(template_name='procesos/planificacion.html'), name='planificacion-semanal'),
    
    # Ruta visual para el diseño de procesos
    path('procesos/', TemplateView.as_view(template_name='procesos/index.html'), name='procesos-index'),
    
    # [NUEVO] Ruta visual para el Diagrama de Gantt (Master Level Scheduling)
    path('gantt/', TemplateView.as_view(template_name='procesos/gantt.html'), name='gantt-lotes'),
    
    # Rutas generadas automáticamente por el router de la API
    path('api/', include(router.urls)),
]