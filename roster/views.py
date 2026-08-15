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

from .models import Cuadrilla, Operador, SecuenciaRol, TurnoDia
from .serializers import (
    CuadrillaSerializer,
    MoverColaboradoresSerializer,
    OperadorSerializer,
    SecuenciaRolSerializer,
    TurnoDiaSerializer,
    UserRegistrationSerializer,
)
from .services import aplicar_carga_masiva, expandir_secuencia


class RosterDashboardView(TemplateView):
    template_name = 'roster/index.html'


class CuadrillaViewSet(viewsets.ModelViewSet):
    """ViewSet para la gestión de Cuadrillas y filtrado jerárquico de operadores y turnos por mes/año."""

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
                    queryset=TurnoDia.objects.filter(fecha__year=y, fecha__month=m),
                )
                queryset = queryset.prefetch_related(turnos_prefetch, 'operadores')
            except ValueError:
                pass
        else:
            queryset = queryset.prefetch_related('operadores__turnos', 'operadores')
        return queryset


class OperadorViewSet(viewsets.ModelViewSet):
    """ViewSet para la gestión de operadores con soporte para archivos multimedia (fotos) y filtrado por estado activo."""

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


class SecuenciaRolViewSet(viewsets.ModelViewSet):
    """ViewSet para la gestión de Secuencias de Rol y sus patrones de turnos."""

    # Se actualizó el ordenamiento al nuevo estándar GxP
    queryset = (
        SecuenciaRol.objects.all().prefetch_related('detalles').order_by('-creado_en')
    )
    serializer_class = SecuenciaRolSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class TurnoDiaViewSet(viewsets.ModelViewSet):
    """ViewSet para el registro individual (upsert por celda), mutación de turnos diarios y operaciones masivas (GxP Ready)."""

    queryset = TurnoDia.objects.all()
    serializer_class = TurnoDiaSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def create(self, request, *args, **kwargs):
        """Permite crear o actualizar (Upsert) un turno individual para un operador en una fecha específica."""
        operador_id = request.data.get('operador')
        fecha = request.data.get('fecha')
        codigo_turno = request.data.get('codigo_turno')

        if not all([operador_id, fecha]):
            return Response(
                {'error': 'Se requiere operador y fecha.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        operador = get_object_or_404(Operador, id=operador_id)

        if not codigo_turno or codigo_turno.strip() == '':
            TurnoDia.objects.filter(operador=operador, fecha=fecha).delete()
            return Response(
                {'status': 'success', 'mensaje': 'Turno limpiado correctamente.'},
                status=status.HTTP_200_OK,
            )

        turno_obj, created = TurnoDia.objects.update_or_create(
            operador=operador,
            fecha=fecha,
            defaults={'codigo_turno': codigo_turno.upper()},
        )

        serializer = self.get_serializer(turno_obj)
        return Response(
            {'status': 'success', 'created': created, 'data': serializer.data},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
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

        return Response(
            {
                'status': 'success',
                'mensaje': f'Carga masiva aplicada correctamente. Se generaron {registros_creados} registros.',
                'registros_creados': registros_creados,
            },
            status=status.HTTP_201_CREATED,
        )


class MoverColaboradoresAPIView(APIView):
    """Endpoint API REST para la reasignación atómica de colaboradores."""

    permission_classes = [permissions.IsAuthenticated]

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
                    # Se actualizó el chequeo a 'actualizado_en' (estándar GxP)
                    if hasattr(operador, 'actualizado_en'):
                        fields_to_update.append('actualizado_en')
                    operador.save(update_fields=fields_to_update)

                    updated_operators.append({
                        'id': operador.id,
                        'nombre': operador.nombre,
                        'nueva_cuadrilla': cuadrilla_destino.nombre,
                    })

            return Response(
                {
                    'success': True,
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
    permission_classes = [permissions.IsAdminUser]