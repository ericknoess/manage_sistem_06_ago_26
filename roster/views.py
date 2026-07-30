# roster/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Cuadrilla, Operador, TurnoDia
from .serializers import CuadrillaSerializer, OperadorSerializer, TurnoDiaSerializer, TurnoDiaUpdateSerializer
from datetime import date, timedelta
from django.views.generic import TemplateView
from django.db.models import Prefetch
from roster.models import Cuadrilla, TurnoDia

    
class CuadrillaViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CuadrillaSerializer

    def get_queryset(self):
        # Capturamos parámetros de la URL: /api/cuadrillas/?month=7&year=2026
        month = self.request.query_params.get('month')
        year = self.request.query_params.get('year')
        
        # Filtro base para los turnos
        turnos_qs = TurnoDia.objects.all()
        if month and year:
            turnos_qs = turnos_qs.filter(fecha__month=month, fecha__year=year)
            
        # Aplicamos el filtro al prefetch (Eficiencia: 1 solo query para todo)
        return Cuadrilla.objects.prefetch_related(
            Prefetch('operadores__turnos', queryset=turnos_qs)
        ).all()

class OperadorViewSet(viewsets.ModelViewSet):
    queryset = Operador.objects.all()
    serializer_class = OperadorSerializer

    @action(detail=True, methods=['patch'])
    def move_to_cuadrilla(self, request, pk=None):
        operador = self.get_object()
        nueva_cuadrilla_id = request.data.get('cuadrilla_id')
        try:
            nueva_cuadrilla = Cuadrilla.objects.get(id=nueva_cuadrilla_id)
            operador.cuadrilla = nueva_cuadrilla
            operador.save()
            return Response({'status': 'Operador reasignado'})
        except Cuadrilla.DoesNotExist:
            return Response({'error': 'Cuadrilla no encontrada'}, status=status.HTTP_404_NOT_FOUND)

class TurnoDiaViewSet(viewsets.ModelViewSet):
    queryset = TurnoDia.objects.all()
    serializer_class = TurnoDiaSerializer
    
    def get_serializer_class(self):
        if self.action in ['update', 'partial_update']:
            return TurnoDiaUpdateSerializer
        return TurnoDiaSerializer
    


class RosterView(TemplateView):
    template_name = 'roster/index.html'