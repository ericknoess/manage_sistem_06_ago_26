# roster/api_urls.py

from rest_framework.routers import DefaultRouter
from .views import (
    CuadrillaViewSet,
    OperadorViewSet,
    SecuenciaRolViewSet,
    TurnoDiaViewSet,
    UserRegistrationViewSet
)

router = DefaultRouter()
router.register(r'cuadrillas', CuadrillaViewSet, basename='cuadrilla')
router.register(r'operadores', OperadorViewSet, basename='operador')
router.register(r'secuencias', SecuenciaRolViewSet, basename='secuencia')
router.register(r'turnos', TurnoDiaViewSet, basename='turno')
router.register(r'users', UserRegistrationViewSet, basename='user')

urlpatterns = router.urls