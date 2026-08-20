# procesos/urls.py

from django.urls import path, include
from django.views.generic import TemplateView
from rest_framework.routers import DefaultRouter
from .views import ProcesoMaestroViewSet, OperacionProcesoViewSet

# Configuración del enrutador para la API REST de procesos y fases CPM
router = DefaultRouter()
router.register(r'procesos-maestros', ProcesoMaestroViewSet, basename='proceso-maestro')
router.register(r'operaciones-proceso', OperacionProcesoViewSet, basename='operacion-proceso')

urlpatterns = [
    # Endpoints REST expuestos bajo /api/
    path('api/', include(router.urls)),
    
    # Vista HTML del Planificador CPM y Rutas de Proceso
    path('procesos/', TemplateView.as_view(template_name='procesos/index.html'), name='gestion-procesos'),
]