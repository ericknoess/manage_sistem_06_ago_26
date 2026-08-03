# roster/urls.py

from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import RosterDashboardView, CuadrillaViewSet, OperadorViewSet, TurnoDiaViewSet

# Instanciamos el enrutador de Django REST Framework
router = DefaultRouter()
router.register(r'cuadrillas', CuadrillaViewSet, basename='cuadrilla')
router.register(r'operadores', OperadorViewSet, basename='operador')
router.register(r'turnos', TurnoDiaViewSet, basename='turnodia')

# Unimos la vista HTML del dashboard con los endpoints REST del router
urlpatterns = [
    path('', RosterDashboardView.as_view(), name='roster-dashboard'),
] + router.urls