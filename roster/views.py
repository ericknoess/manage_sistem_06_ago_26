# roster/views.py

from datetime import datetime
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    TipoTurno, 
    Cuadrilla, 
    RolOperador,  
    Operador, 
    SecuenciaRol, 
    TurnoDia, 
    IncidenciaTurno
)
from .serializers import (
    TipoTurnoSerializer,
    CuadrillaSerializer,
    RolOperadorSerializer,  
    MoverColaboradoresSerializer,
    OperadorSerializer,
    SecuenciaRolSerializer,
    TurnoDiaSerializer,
    UserRegistrationSerializer,
    IncidenciaTurnoSerializer,
)
from .services import aplicar_carga_masiva, expandir_secuencia
from auditoria.mixins import AuditoriaMixin
from auditoria.services import registrar


class RosterDashboardView(TemplateView):
    template_name = 'roster/index.html'


class RolOperadorViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """
    ViewSet para la gestión y consulta del catálogo maestro de Roles y Competencias (Skills).
    Permite listar roles activos para el planificador CPM y administración de personal.
    """
    auditoria_categoria, auditoria_nombre = 'ROSTER', 'rol de operador'
    queryset = RolOperador.objects.all().order_by('nombre')
    serializer_class = RolOperadorSerializer
    permiso_escritura = 'gestionar_roster'

    def get_queryset(self):
        queryset = super().get_queryset()
        activo_param = self.request.query_params.get('activo')
        if activo_param is not None:
            is_active = activo_param.lower() in ['true', '1', 'yes']
            queryset = queryset.filter(activo=is_active)
        return queryset


class TipoTurnoViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """ViewSet para la gestión del catálogo maestro de Tipos de Turno y sus propiedades visuales HEX."""
    auditoria_categoria, auditoria_nombre = 'ROSTER', 'tipo de turno'

    queryset = TipoTurno.objects.all().order_by('codigo')
    serializer_class = TipoTurnoSerializer
    permiso_escritura = 'gestionar_roster'

    def get_queryset(self):
        queryset = TipoTurno.objects.all().order_by('codigo')
        activo_param = self.request.query_params.get('activo')
        if activo_param is not None:
            is_active = activo_param.lower() in ['true', '1', 'yes']
            queryset = queryset.filter(activo=is_active)
        return queryset


class CuadrillaViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """ViewSet para la gestión de Cuadrillas y filtrado jerárquico de operadores y turnos por mes/año."""
    auditoria_categoria, auditoria_nombre = 'ROSTER', 'cuadrilla'
    auditoria_excluir = ('operadores',)

    queryset = Cuadrilla.objects.all().order_by('identificador')
    serializer_class = CuadrillaSerializer
    permiso_escritura = 'gestionar_roster'

    def list(self, request, *args, **kwargs):
        try:
            return super().list(request, *args, **kwargs)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response(
                {'error': f'Error interno en CuadrillaViewSet: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

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
                    queryset=TurnoDia.objects.filter(fecha__year=y, fecha__month=m).select_related('tipo_turno', 'incidencia'),
                )
                queryset = queryset.prefetch_related(turnos_prefetch, 'operadores')
            except ValueError:
                pass
        else:
            queryset = queryset.prefetch_related('operadores__turnos__tipo_turno', 'operadores__turnos__incidencia', 'operadores')
        return queryset


class OperadorViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """ViewSet para la gestión de operadores con soporte para archivos multimedia (fotos) y filtrado por estado activo."""
    auditoria_categoria, auditoria_nombre = 'ROSTER', 'operador'
    auditoria_excluir = ('turnos',)

    queryset = Operador.objects.all().order_by('nombre')
    serializer_class = OperadorSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    permiso_escritura = 'gestionar_roster'

    def get_queryset(self):
        queryset = super().get_queryset()
        activo_param = self.request.query_params.get('activo')

        if activo_param is not None:
            is_active = activo_param.lower() in ['true', '1', 'yes']
            queryset = queryset.filter(activo=is_active)

        return queryset


class SecuenciaRolViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """ViewSet para la gestión de Secuencias de Rol y sus patrones de turnos."""
    auditoria_categoria, auditoria_nombre = 'ROSTER', 'secuencia de rol'

    queryset = (
        SecuenciaRol.objects.all().prefetch_related('detalles').order_by('-creado_en')
    )
    serializer_class = SecuenciaRolSerializer
    permiso_escritura = 'gestionar_roster'


class TurnoDiaViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """ViewSet para el registro individual (upsert por celda), mutación de turnos diarios y operaciones masivas (GxP Ready)."""
    auditoria_categoria, auditoria_nombre = 'ROSTER', 'turno'
    auditoria_campos = ('operador', 'fecha', 'codigo_turno')

    queryset = TurnoDia.objects.all()
    serializer_class = TurnoDiaSerializer
    permiso_escritura = 'gestionar_roster'

    def get_queryset(self):
        """
        Soporta filtrado estándar y consulta por rango de fechas (start_date y end_date) 
        para abastecer vistas de consulta bi-semanales.
        """
        queryset = TurnoDia.objects.select_related('operador', 'tipo_turno', 'incidencia').all().order_by('fecha', 'operador__nombre')
        
        start_date = self.request.query_params.get('start_date', None)
        end_date = self.request.query_params.get('end_date', None)

        if start_date and end_date:
            try:
                f_inicio = datetime.strptime(start_date, '%Y-%m-%d').date()
                f_fin = datetime.strptime(end_date, '%Y-%m-%d').date()
                queryset = queryset.filter(fecha__range=[f_inicio, f_fin])
            except ValueError:
                pass
        return queryset

    def create(self, request, *args, **kwargs):
        """Permite crear o actualizar (Upsert) un turno individual asociado al catálogo maestro TipoTurno con manejo de errores seguro."""
        try:
            operador_id = request.data.get('operador')
            fecha = request.data.get('fecha')
            codigo_turno = request.data.get('codigo_turno') or request.data.get('tipo_turno')

            if not all([operador_id, fecha]):
                return Response(
                    {'error': 'Se requiere operador y fecha.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            operador = get_object_or_404(Operador, id=operador_id)
            previo = TurnoDia.objects.filter(operador=operador, fecha=fecha).select_related('tipo_turno').first()
            codigo_previo = previo.tipo_turno.codigo if previo and previo.tipo_turno_id else None

            if not codigo_turno or str(codigo_turno).strip() == '':
                TurnoDia.objects.filter(operador=operador, fecha=fecha).delete()
                if codigo_previo:
                    registrar(request, 'ROSTER', 'ELIMINAR', f"Turno limpiado: {operador.nombre} {fecha}",
                              objeto=operador, cambios={'turno': [codigo_previo, None]})
                return Response(
                    {'status': 'success', 'mensaje': 'Turno limpiado correctamente.'},
                    status=status.HTTP_200_OK,
                )

            codigo_upper = str(codigo_turno).upper().strip()
            tipo_turno, _ = TipoTurno.objects.get_or_create(
                codigo=codigo_upper,
                defaults={
                    'nombre': f'Turno {codigo_upper}',
                    'color_fondo': '#3b82f6',
                    'color_texto': '#ffffff',
                    'es_descanso': False,
                    'activo': True
                }
            )

            with transaction.atomic():
                turno_obj, created = TurnoDia.objects.update_or_create(
                    operador=operador,
                    fecha=fecha,
                    defaults={'tipo_turno': tipo_turno},
                )
                if codigo_previo != tipo_turno.codigo:
                    registrar(request, 'ROSTER', 'CREAR' if created else 'EDITAR', f"Turno {tipo_turno.codigo}: {operador.nombre} {fecha}",
                              objeto=turno_obj, cambios={'turno': [codigo_previo, tipo_turno.codigo]})

            serializer = self.get_serializer(turno_obj)
            return Response(
                {'status': 'success', 'created': created, 'data': serializer.data},
                status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response(
                {'error': f'Error interno en servidor: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=['post'], url_path='previsualizar-carga-masiva')
    def previsualizar_carga_masiva(self, request):
        tipo = request.data.get('tipo')
        referencia_id = request.data.get('id')
        secuencia_id = request.data.get('secuencia_id')
        fecha_inicio_str = request.data.get('fecha_inicio')
        fecha_fin_str = request.data.get('fecha_fin')

        if not all([tipo, referencia_id, secuencia_id, fecha_inicio_str, fecha_fin_str]):
            return Response(
                {'error': 'Faltan parámetros obligatorios en la solicitud.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
        except ValueError:
            return Response(
                {'error': 'Formato de fecha inválido. Utilice el formato YYYY-MM-DD.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if fecha_fin < fecha_inicio:
            return Response(
                {'error': 'La fecha final debe ser posterior o igual a la fecha inicial.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        secuencia = get_object_or_404(SecuenciaRol, id=secuencia_id, activa=True)

        operadores = []
        if tipo == 'operador':
            op = get_object_or_404(Operador, id=referencia_id, activo=True)
            operadores = [op]
        elif tipo == 'cuadrilla':
            cuadrilla = get_object_or_404(Cuadrilla, id=referencia_id, activa=True)
            operadores = list(cuadrilla.operadores.filter(activo=True))
        else:
            return Response(
                {'error': "Tipo de asignación inválido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        plan_turnos = expandir_secuencia(secuencia, fecha_inicio, fecha_fin)

        preview_data = []
        for op in operadores:
            turnos_op = [
                {'fecha': item['fecha'].strftime('%Y-%m-%d'), 'codigo': item['codigo']}
                for item in plan_turnos
            ]
            preview_data.append({
                'operador_id': op.id,
                'operador_nombre': op.nombre,
                'codigo_empleado': op.codigo_empleado,
                'turnos': turnos_op,
            })

        return Response(
            {
                'total_colaboradores': len(operadores),
                'total_registros': len(operadores) * len(plan_turnos),
                'secuencia_nombre': secuencia.nombre,
                'fecha_inicio': fecha_inicio_str,
                'fecha_fin': fecha_fin_str,
                'previsualizacion': preview_data,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=['post'], url_path='carga-masiva')
    def carga_masiva(self, request):
        tipo = request.data.get('tipo')
        referencia_id = request.data.get('id')
        secuencia_id = request.data.get('secuencia_id')
        fecha_inicio_str = request.data.get('fecha_inicio')
        fecha_fin_str = request.data.get('fecha_fin')
        estrategia = request.data.get('estrategia', 'mantener')

        if not all([tipo, referencia_id, secuencia_id, fecha_inicio_str, fecha_fin_str]):
            return Response(
                {'error': 'Faltan parámetros obligatorios en la solicitud.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
        except ValueError:
            return Response(
                {'error': 'Formato de fecha inválido. Utilice el formato YYYY-MM-DD.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if fecha_fin < fecha_inicio:
            return Response(
                {'error': 'La fecha final debe ser posterior o igual a la fecha inicial.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        secuencia = get_object_or_404(SecuenciaRol, id=secuencia_id, activa=True)

        operadores = []
        if tipo == 'operador':
            op = get_object_or_404(Operador, id=referencia_id, activo=True)
            operadores = [op]
        elif tipo == 'cuadrilla':
            cuadrilla = get_object_or_404(Cuadrilla, id=referencia_id, activa=True)
            operadores = list(cuadrilla.operadores.filter(activo=True))
        else:
            return Response(
                {'error': 'Tipo de asignación inválido.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not operadores:
            return Response(
                {'error': 'No se encontraron colaboradores activos para aplicar la secuencia.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            registros_creados = aplicar_carga_masiva(
                operadores=operadores,
                secuencia=secuencia,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                estrategia=estrategia,
            )
        except Exception as e:
            return Response(
                {'error': f'Error crítico durante la transacción atómica: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        registrar(request, 'ROSTER', 'CARGA_MASIVA',
                  f"Carga masiva de la secuencia {secuencia} a {len(operadores)} colaborador(es), {fecha_inicio} a {fecha_fin}",
                  objeto=secuencia, cambios={'operadores': [None, [o.nombre for o in operadores]],
                                             'estrategia': [None, estrategia], 'registros': [None, registros_creados]})
        return Response(
            {
                'status': 'success',
                'mensaje': f'Carga masiva aplicada correctamente. Se generaron {registros_creados} registros.',
                'registros_creados': registros_creados,
            },
            status=status.HTTP_201_CREATED,
        )


class IncidenciaTurnoViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """
    ViewSet exclusivo para gestionar las incidencias y notas operacionales asociadas a un Turno.
    """
    auditoria_categoria, auditoria_nombre = 'ROSTER', 'incidencia'
    queryset = IncidenciaTurno.objects.all().select_related('turno_dia__operador')
    serializer_class = IncidenciaTurnoSerializer
    permiso_escritura = 'gestionar_roster'

    def get_queryset(self):
        queryset = super().get_queryset()
        turno_id = self.request.query_params.get('turno_dia')
        if turno_id:
            queryset = queryset.filter(turno_dia_id=turno_id)
        return queryset


class MoverColaboradoresAPIView(APIView):
    """Endpoint API REST para la reasignación atómica de colaboradores."""

    permiso_escritura = 'gestionar_roster'

    def post(self, request, *args, **kwargs):
        serializer = MoverColaboradoresSerializer(
            data=request.data, context={'request': request}
        )

        if not serializer.is_valid():
            detalles_error = []
            for campo, mensajes in serializer.errors.items():
                detalles_error.append(f"{campo}: {', '.join(str(m) for m in mensajes)}")
            mensaje_formateado = " | ".join(detalles_error)

            return Response(
                {'success': False, 'message': f'Error de validación GxP: {mensaje_formateado}', 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        operador_ids = data['operador_ids']
        cuadrilla_destino_id = data['cuadrilla_destino_id']

        try:
            with transaction.atomic():
                cuadrilla_destino = Cuadrilla.objects.select_for_update().get(id=cuadrilla_destino_id)
                operadores = Operador.objects.select_for_update().filter(id__in=operador_ids)

                cuadrilla_origen = Cuadrilla.objects.get(id=operadores.first().cuadrilla_id)

                updated_operators = []
                for operador in operadores:
                    operador.cuadrilla = cuadrilla_destino
                    fields_to_update = ['cuadrilla']
                    if hasattr(operador, 'actualizado_en'):
                        fields_to_update.append('actualizado_en')
                    operador.save(update_fields=fields_to_update)

                    updated_operators.append({
                        'id': operador.id,
                        'nombre': operador.nombre,
                        'nueva_cuadrilla': cuadrilla_destino.nombre,
                    })

                registrar(request, 'ROSTER', 'MOVER_CUADRILLA',
                          f"{len(updated_operators)} colaborador(es) movidos de {cuadrilla_origen.nombre} a {cuadrilla_destino.nombre}",
                          objeto=cuadrilla_destino, cambios={'cuadrilla': [cuadrilla_origen.nombre, cuadrilla_destino.nombre],
                                                             'operadores': [None, [o['nombre'] for o in updated_operators]]})

            return Response(
                {
                    'success': 'true',
                    'message': 'Colaboradores movidos correctamente',
                    'moved_count': len(updated_operators),
                    'source_group_id': cuadrilla_origen.id,
                    'source_group_name': cuadrilla_origen.nombre,
                    'destination_group_id': cuadrilla_destino.id,
                    'destination_group_name': cuadrilla_destino.nombre,
                    'operators': updated_operators,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {'success': False, 'message': 'No fue posible completar el movimiento.', 'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )


class UserRegistrationViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    # Los datos de usuarios solo los ve y cambia quien administra usuarios (staff de Django)
    permission_classes = [permissions.IsAdminUser]