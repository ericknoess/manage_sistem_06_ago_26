# roster/views.py

from django.views.generic import TemplateView
from rest_framework import viewsets, permissions
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from django.contrib.auth.models import User
from django.db.models import Prefetch
from .models import Cuadrilla, Operador, TurnoDia
from .serializers import (
    CuadrillaSerializer, 
    OperadorSerializer, 
    TurnoDiaSerializer, 
    UserRegistrationSerializer
)

class RosterDashboardView(TemplateView):
    """
    Vista basada en clases para renderizar el Dashboard HTML principal
    del Módulo Control en Proceso (Upstream GxP).
    """
    template_name = 'roster/index.html'


class CuadrillaViewSet(viewsets.ModelViewSet):
    """
    ViewSet para listar, crear, actualizar y eliminar Cuadrillas.
    Integra optimización de consultas mediante prefetch_related y filtrado 
    dinámico de turnos por mes y año (?month=X&year=YYYY).
    """
    queryset = Cuadrilla.objects.all().order_by('identificador')
    serializer_class = CuadrillaSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = Cuadrilla.objects.all().order_by('identificador')
        month = self.request.query_params.get('month')
        year = self.request.query_params.get('year')

        if month and year:
            try:
                m = int(month)
                y = int(year)
                turnos_prefetch = Prefetch(
                    'operadores__turnos',
                    queryset=TurnoDia.objects.filter(fecha__year=y, fecha__month=m)
                )
                queryset = queryset.prefetch_related(turnos_prefetch, 'operadores')
            except ValueError:
                pass
        return queryset


class OperadorViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar Operadores y su asignación de cuadrilla.
    Integra soporte para JSON (actualizaciones parciales de cuadrilla), 
    carga de fotografías (MultiPartParser), nivel de expertiz
    y filtrado dinámico por estatus activo (?activo=true/false).
    """
    queryset = Operador.objects.all().order_by('nombre')
    serializer_class = OperadorSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = super().get_queryset()
        activo_param = self.request.query_params.get('activo')
        
        if activo_param is not None:
            is_active = activo_param.lower() in ['true', '1', 'yes']
            queryset = queryset.filter(activo=is_active)
            
        return queryset


class TurnoDiaViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el registro y mutación de turnos diarios.
    Garantiza la trazabilidad GxP de las asignaciones de personal.
    """
    queryset = TurnoDia.objects.all()
    serializer_class = TurnoDiaSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class UserRegistrationViewSet(viewsets.ModelViewSet):
    """
    ViewSet administrativo para el registro y gestión de usuarios del sistema.
    Restringido estrictamente a administradores para cumplir con normativas GxP.
    """
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.IsAdminUser]