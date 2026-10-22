# actividades/urls.py

from django.urls import path, include
from django.views.generic import RedirectView, TemplateView
from rest_framework.routers import DefaultRouter
from .views import EquipoViewSet, MaterialInsumoViewSet, ActividadSemanalViewSet, TipoEquipoViewSet

# Configuración del enrutador para la API REST
router = DefaultRouter()
router.register(r'equipos', EquipoViewSet, basename='equipo')
router.register(r'tipos-equipo', TipoEquipoViewSet, basename='tipo-equipo')
router.register(r'materiales', MaterialInsumoViewSet, basename='material')
router.register(r'actividades-semanales', ActividadSemanalViewSet, basename='actividad-semanal')

urlpatterns = [
    # Endpoints REST expuestos bajo /api/
    path('api/', include(router.urls)),
    
    # Catálogo maestro de materiales (alta, edición, búsqueda y baja lógica)
    path('materiales/catalogo/', TemplateView.as_view(template_name='actividades/catalogo_materiales.html'), name='catalogo-materiales'),

    # Catálogo maestro de equipos y sus tipos (alta, edición, estado, calificación y baja lógica)
    path('equipos/catalogo/', TemplateView.as_view(template_name='actividades/catalogo_equipos.html'), name='catalogo-equipos'),

    # Tablero semanal retirado: la asignación se hace solo en Planificación. Se redirige para no romper marcadores.
    path('tablero/', RedirectView.as_view(pattern_name='planificacion-semanal', permanent=False)),
]