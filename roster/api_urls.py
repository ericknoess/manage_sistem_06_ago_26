# api_urls.py

from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    TipoTurnoViewSet,
    CuadrillaViewSet,
    OperadorViewSet,
    SecuenciaRolViewSet,
    TurnoDiaViewSet,
    IncidenciaTurnoViewSet,
    UserRegistrationViewSet,
    MoverColaboradoresAPIView,
)

router = DefaultRouter()
router.register(r'tipos-turno', TipoTurnoViewSet, basename='tipoturno')
router.register(r'cuadrillas', CuadrillaViewSet, basename='cuadrilla')
router.register(r'operadores', OperadorViewSet, basename='operador')
router.register(r'secuencias', SecuenciaRolViewSet, basename='secuencia')
router.register(r'turnos', TurnoDiaViewSet, basename='turno')
# Registrar el nuevo endpoint de incidencias operativas
router.register(r'incidencias', IncidenciaTurnoViewSet, basename='incidencia')
router.register(r'users', UserRegistrationViewSet, basename='user')

urlpatterns = router.urls + [
    path('roster/mover-cuadrilla/', MoverColaboradoresAPIView.as_view(), name='mover-cuadrilla'),
]