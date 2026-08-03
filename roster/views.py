# roster/views.py

from django.views.generic import TemplateView
from rest_framework import viewsets
from .models import Cuadrilla, Operador, TurnoDia
from .serializers import CuadrillaSerializer, OperadorSerializer, TurnoDiaSerializer

class RosterDashboardView(TemplateView):
    """
    Vista basada en clases para renderizar el Dashboard HTML principal
    del Módulo Control en Proceso (Upstream GxP).
    """
    template_name = 'roster/index.html'

class CuadrillaViewSet(viewsets.ModelViewSet):
    """
    ViewSet para listar, crear, actualizar y eliminar Cuadrillas.
    """
    queryset = Cuadrilla.objects.all().order_by('identificador')
    serializer_class = CuadrillaSerializer

class OperadorViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar Operadores y su asignación de cuadrilla.
    """
    queryset = Operador.objects.all().order_by('nombre')
    serializer_class = OperadorSerializer

class TurnoDiaViewSet(viewsets.ModelViewSet):
    """
    ViewSet para el registro y mutación de turnos diarios.
    """
    queryset = TurnoDia.objects.all()
    serializer_class = TurnoDiaSerializer