# actividades/views.py

from django.db.models import Count, Q
from rest_framework import viewsets

from auditoria.mixins import AuditoriaMixin
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Equipo, MaterialInsumo, ActividadSemanal, TipoEquipo
from .serializers import EquipoSerializer, MaterialInsumoSerializer, ActividadSemanalSerializer, TipoEquipoSerializer

class TipoEquipoViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """
    Tipos de equipo que piden las recetas. Sin DELETE: un tipo se da de baja con `activo=false`.
    """
    auditoria_categoria, auditoria_nombre = 'CATALOGO', 'tipo de equipo'
    auditoria_excluir = ('equipos_registrados', 'usos_en_recetas')
    http_method_names = ['get', 'post', 'put', 'patch', 'head', 'options']
    serializer_class = TipoEquipoSerializer
    permiso_escritura = 'gestionar_catalogos'

    def get_queryset(self):
        qs = TipoEquipo.objects.annotate(
            equipos_registrados=Count('equipos', filter=Q(equipos__activo=True), distinct=True),
            usos_en_recetas=Count('usos_en_operaciones', distinct=True),
        ).order_by('nombre')
        if self.request.query_params.get('activo') in ('true', 'false'):
            qs = qs.filter(activo=self.request.query_params['activo'] == 'true')
        return qs


class EquipoViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """
    Catálogo maestro de equipos críticos. Filtros: ?q= (código, nombre o área), ?tipo=, ?estado=, ?activo=true|false.
    Sin DELETE: un equipo se da de baja con `activo=false` (sus reservas pasadas siguen en el registro del lote).
    """
    auditoria_categoria, auditoria_nombre = 'CATALOGO', 'equipo'
    auditoria_excluir = ('reservas_vigentes', 'dias_calibracion')
    http_method_names = ['get', 'post', 'put', 'patch', 'head', 'options']
    serializer_class = EquipoSerializer
    permiso_escritura = 'gestionar_catalogos'

    def get_queryset(self):
        qs = Equipo.objects.select_related('tipo').annotate(
            reservas_vigentes=Count('reservas', filter=Q(
                reservas__activo=True, reservas__hasta__isnull=True,
                reservas__equipo_fase__activo=True,
                reservas__equipo_fase__fase__estado__in=['PENDIENTE', 'EN_PROGRESO'],
            )),
        ).order_by('id')
        params = self.request.query_params
        if params.get('q'):
            q = params['q'].strip()
            qs = qs.filter(Q(id__icontains=q) | Q(nombre__icontains=q) | Q(area__icontains=q))
        if params.get('tipo'):
            qs = qs.filter(tipo_id=params['tipo'])
        if params.get('estado'):
            qs = qs.filter(estado=params['estado'])
        if params.get('activo') in ('true', 'false'):
            qs = qs.filter(activo=params['activo'] == 'true')
        return qs

    @action(detail=False, methods=['get'], url_path='opciones')
    def opciones(self, request):
        """Estados válidos y tipos activos para los formularios."""
        return Response({
            'estados': [{'valor': v, 'etiqueta': e} for v, e in Equipo.ESTADO_CHOICES],
            'tipos': [{'valor': t.codigo, 'etiqueta': t.nombre} for t in TipoEquipo.objects.filter(activo=True)],
        })


class MaterialInsumoViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    auditoria_categoria, auditoria_nombre = 'CATALOGO', 'material'
    auditoria_excluir = ('usos_en_recetas',)
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