# actividades/views.py

from rest_framework import viewsets
from .models import Equipo, MaterialInsumo, ActividadSemanal
from .serializers import EquipoSerializer, MaterialInsumoSerializer, ActividadSemanalSerializer
from django.shortcuts import render

class EquipoViewSet(viewsets.ModelViewSet):
    queryset = Equipo.objects.all()
    serializer_class = EquipoSerializer


class MaterialInsumoViewSet(viewsets.ModelViewSet):
    queryset = MaterialInsumo.objects.all()
    serializer_class = MaterialInsumoSerializer


class ActividadSemanalViewSet(viewsets.ModelViewSet):
    queryset = ActividadSemanal.objects.all().select_related('operador_asignado').prefetch_related('equipos', 'materiales')
    serializer_class = ActividadSemanalSerializer

    def get_queryset(self):
        """Permite filtrar opcionalmente por rango de fechas mediante parámetros GET (start_date, end_date)."""
        queryset = super().get_queryset()
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        
        if start_date and end_date:
            queryset = queryset.filter(fecha__gte=start_date, fecha__lte=end_date)
        return queryset



def tablero_semanal_view(request):
    return render(request, 'actividades/index.html')