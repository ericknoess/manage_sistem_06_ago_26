from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CuadrillaViewSet, OperadorViewSet, TurnoDiaViewSet, RosterView

# Inicializamos el router
router = DefaultRouter()

# Registramos cada ViewSet con su respectivo 'basename'.
# El basename es la base para los nombres de las URLs (ej: 'cuadrilla-list', 'operador-list')
router.register(r'cuadrillas', CuadrillaViewSet, basename='cuadrilla')
router.register(r'operadores', OperadorViewSet, basename='operador')
router.register(r'turnos', TurnoDiaViewSet, basename='turno')

urlpatterns = [
    # Vista visual del frontend
    path('vista/', RosterView.as_view(), name='roster-view'), 
    
    # API endpoints
    path('api/', include(router.urls)), 
]
