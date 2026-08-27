# roster/urls.py

from django.urls import path
from django.views.generic import TemplateView
from .views import RosterDashboardView, MoverColaboradoresAPIView

urlpatterns = [
    # Vista principal del tablero de turnos y cuadrillas (Frontend renderizado por Django)[cite: 2]
    path('', RosterDashboardView.as_view(), name='roster_dashboard'),
    
    # NUEVA RUTA: Vista de consulta bi-semanal de turnos (14 días - Solo Lectura)
    path('bisemanal/', TemplateView.as_view(template_name='roster/bisemanal.html'), name='roster_bisemanal'),
    
    # Endpoint API REST para reasignación masiva/individual atómica de colaboradores entre cuadrillas[cite: 2]
    path('api/roster/mover-cuadrilla/', MoverColaboradoresAPIView.as_view(), name='api-mover-cuadrilla'),
]