# actividades/views.py

from django.db.models import Count, Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Equipo, MaterialInsumo, ActividadSemanal
from .serializers import EquipoSerializer, MaterialInsumoSerializer, ActividadSemanalSerializer

class EquipoViewSet(viewsets.ModelViewSet):
    """
    API endpoint para gestionar el catálogo maestro de equipos críticos.
    """
    queryset = Equipo.objects.all()
    serializer_class = EquipoSerializer
    permiso_escritura = 'gestionar_catalogos'


class MaterialInsumoViewSet(viewsets.ModelViewSet):
    """
    API endpoint para gestionar el catálogo maestro de materiales e insumos.
    Filtros: ?q= (código, nombre, código ERP o proveedor), ?categoria=, ?activo=true|false.
    Sin DELETE: un material se da de baja con `activo=false` (trazabilidad GxP).
    """
    http_method_names = ['get', 'post', 'put', 'patch', 'head', 'options']
    serializer_class = MaterialInsumoSerializer
    permiso_escritura = 'gestionar_catalogos'

    def get_queryset(self):
        qs = MaterialInsumo.objects.annotate(usos_en_recetas=Count('usos_en_operaciones')).order_by('nombre')
        params = self.request.query_params
        if params.get('q'):
            q = params['q'].strip()
            qs = qs.filter(Q(id__icontains=q) | Q(nombre__icontains=q) | Q(codigo_erp__icontains=q) | Q(proveedor__icontains=q))
        if params.get('categoria'):
            qs = qs.filter(categoria=params['categoria'])
        if params.get('activo') in ('true', 'false'):
            qs = qs.filter(activo=params['activo'] == 'true')
        return qs

    @action(detail=False, methods=['get'], url_path='opciones')
    def opciones(self, request):
        """Catálogos de valores válidos (categorías, unidades, almacenamiento) para los formularios."""
        como_lista = lambda choices: [{'valor': v, 'etiqueta': e} for v, e in choices]
        return Response({
            'categorias': como_lista(MaterialInsumo.CATEGORIA_CHOICES),
            'unidades': como_lista(MaterialInsumo.UNIDAD_CHOICES),
            'almacenamiento': como_lista(MaterialInsumo.ALMACENAMIENTO_CHOICES),
        })


class ActividadSemanalViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Histórico del tablero semanal retirado, solo lectura.
    La asignación de operadores y materiales se hace en Planificación (FaseLote).
    """
    # Usamos prefetch_related para optimizar las consultas Many-to-Many y evitar errores de campos obsoletos
    queryset = ActividadSemanal.objects.prefetch_related(
        'operadores_asignados', 
        'equipos', 
        'materiales'
    ).all().order_by('fecha', 'hora_inicio')
    
    serializer_class = ActividadSemanalSerializer