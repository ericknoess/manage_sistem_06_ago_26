# datos_proceso/urls.py

from django.urls import include, path
from django.views.generic import TemplateView
from rest_framework.routers import DefaultRouter

from .views import CapturaViewSet, ParametroProcesoViewSet

router = DefaultRouter()
router.register(r'parametros-proceso', ParametroProcesoViewSet, basename='parametro-proceso')
router.register(r'captura', CapturaViewSet, basename='captura')

urlpatterns = [
    path('api/', include(router.urls)),
    # Catálogo de parámetros de proceso (alta, edición, fórmulas y baja lógica)
    path('parametros/', TemplateView.as_view(template_name='datos_proceso/catalogo_parametros.html'), name='catalogo-parametros'),
]
