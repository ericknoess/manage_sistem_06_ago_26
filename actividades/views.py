# actividades/views.py

from rest_framework import viewsets
from .models import Equipo, MaterialInsumo, ActividadSemanal
from .serializers import EquipoSerializer, MaterialInsumoSerializer, ActividadSemanalSerializer

class EquipoViewSet(viewsets.ModelViewSet):
    """
    API endpoint para gestionar el catálogo maestro de equipos críticos.
    """
    queryset = Equipo.objects.all()
    serializer_class = EquipoSerializer


class MaterialInsumoViewSet(viewsets.ModelViewSet):
    """
    API endpoint para gestionar el catálogo maestro de materiales e insumos.
    """
    queryset = MaterialInsumo.objects.all()
    serializer_class = MaterialInsumoSerializer


class ActividadSemanalViewSet(viewsets.ModelViewSet):
    """
    API endpoint para la planificación, asignación de múltiples operadores 
    y recursos en el tablero semanal de bioprocesos Upstream.
    """
    # Usamos prefetch_related para optimizar las consultas Many-to-Many y evitar errores de campos obsoletos
    queryset = ActividadSemanal.objects.prefetch_related(
        'operadores_asignados', 
        'equipos', 
        'materiales'
    ).all().order_by('fecha', 'hora_inicio')
    
    serializer_class = ActividadSemanalSerializer