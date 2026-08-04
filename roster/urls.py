# roster/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import RosterDashboardView, CuadrillaViewSet, OperadorViewSet, TurnoDiaViewSet

# Instanciamos el enrutador de Django REST Framework para los ViewSets
router = DefaultRouter()
router.register(r'cuadrillas', CuadrillaViewSet, basename='cuadrilla')
router.register(r'operadores', OperadorViewSet, basename='operador')
router.register(r'turnos', TurnoDiaViewSet, basename='turno')

urlpatterns = [
    # Ruta para el Dashboard HTML principal del módulo Upstream
    path('', RosterDashboardView.as_view(), name='roster-dashboard'),
    
    # Endpoints REST de la API bajo el subprefijo 'api/'
    path('api/', include(router.urls)),
]