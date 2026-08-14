# roster/urls.py

from django.urls import path
from .views import RosterDashboardView, MoverColaboradoresAPIView

urlpatterns = [
    # Vista principal del tablero de turnos y cuadrillas (Frontend renderizado por Django)
    path('', RosterDashboardView.as_view(), name='roster_dashboard'),
    
    # Endpoint API REST para reasignación masiva/individual atómica de colaboradores entre cuadrillas
    path('api/roster/mover-cuadrilla/', MoverColaboradoresAPIView.as_view(), name='api-mover-cuadrilla'),
]