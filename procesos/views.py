# procesos/views.py

from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth import logout as auth_logout
from django.contrib.auth.models import AnonymousUser
from django.db import transaction
from django.db.models import Count, Q, RestrictedError
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import mixins, permissions, viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from auditoria.mixins import AuditoriaMixin
from auditoria.services import diferencias, firmar, quien, registrar
from usuarios.firmas import (
    FirmaRechazada, registrar_fallo_pin, reiniciar_intentos_pin, verificar_firma, SIGNIFICADOS,
)
from usuarios.permisos import PermisoFaseLote, PermisoSurtido, SOLO_SESION, operador_de_sesion


def _firma_o_respuesta(request, accion):
    """(firmante, None) si la firma es válida; (None, Response de error) si no."""
    try:
        return verificar_firma(request, accion), None
    except FirmaRechazada as e:
        return None, Response(e.como_respuesta(), status=e.estado_http)
 
from .models import (
    ProcesoMaestro, EtapaProceso, OperacionProceso, RequerimientoPersonalFase,
    LoteProduccion, FaseLote, AsignacionFaseOperador, MaterialOperacion, MaterialFase,
    EquipoOperacion, EquipoFase, ReservaEquipo, EntregaMaterial,
)
from actividades.models import Equipo, MaterialInsumo, TipoEquipo
from roster.models import Operador
from .serializers import (
    ProcesoMaestroSerializer, EtapaProcesoSerializer, OperacionProcesoSerializer,
    LoteProduccionSerializer, LoteResumenSerializer, FaseLoteSerializer, AsignacionFaseOperadorSerializer,
    MaterialFaseSerializer, RequerimientoMaterialSerializer, EquipoFaseSerializer, ReservaEquipoSerializer,
    EntregaMaterialSerializer,
)
from .services import (
    CPMCalculatorService, validar_disponibilidad_personal_fase, construir_fases_lote,
    validar_inicio_contra_predecesora, propagar_programacion, buscar_conflicto_operador,
    evaluar_inicio, alertas_programacion, formatear_hora,
    generar_materiales_lote, ajustar_material_fase, agregar_material_fase, retirar_material_fase,
    requerimientos_materiales, ErrorMaterialFase,
    generar_equipos_lote, ajustar_equipo_fase, agregar_equipo_fase, retirar_equipo_fase, reservar_equipo,
    liberar_reserva, cambiar_equipo, validar_cambio_equipo, equipos_candidatos, ocupacion_equipos, ErrorEquipoFase,
    registrar_entrega, recibir_entrega, rechazar_entrega, registrar_devolucion, materiales_por_surtir,
    advertencias_surtido, resumen_surtido, disponible_para_devolver, actor_tiene_permiso, puede_recibir_material, en_turno,
    ErrorSurtido, operadores_disponibles, lotes_para_gantt, resumen_gantt,
)
from datos_proceso.services import clonar_indicadores, clonar_secciones, datos_pendientes, generar_plan_captura, resumen_captura


# ==============================================================================
# 1. VIEWSETS MAESTROS (DISEÑO Y PLANIFICACIÓN)
# ==============================================================================

class ProcesoMaestroViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    auditoria_categoria, auditoria_nombre = 'RECETA', 'receta'
    auditoria_excluir = ('etapas', 'operaciones')
    queryset = ProcesoMaestro.objects.prefetch_related('operaciones__materiales__material', 'operaciones__equipos__tipo', 'operaciones__requerimientos_rol__rol', 'operaciones__secciones_captura__parametros__parametro', 'etapas').all().order_by('-created_at')
    serializer_class = ProcesoMaestroSerializer
    permiso_escritura = 'editar_receta'
    permisos_por_accion = {'archivar': 'archivar_receta', 'desarchivar': 'archivar_receta'}

    @action(detail=True, methods=['get'], url_path='cpm-analisis')
    def cpm_analisis(self, request, pk=None):
        proceso = self.get_object()
        operaciones = proceso.operaciones.all()
        calculadora = CPMCalculatorService(operaciones)
        resultado_cpm = calculadora.calcular_cpm()
        return Response({
            "proceso_id": proceso.id,
            "proceso_nombre": proceso.nombre,
            **resultado_cpm
        })

    @action(detail=True, methods=['post'], url_path='archivar')
    def archivar(self, request, pk=None):
        proceso = self.get_object()
        proceso.activo = False
        proceso.save()
        registrar(request, 'RECETA', 'ARCHIVAR', f"Receta archivada: {proceso.nombre}", objeto=proceso, cambios={'activo': [True, False]})
        return Response({
            "mensaje": f"La plantilla '{proceso.nombre}' ha sido archivada. Se conservará para el historial de lotes, pero ya no se podrán instanciar nuevos."
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='desarchivar')
    def desarchivar(self, request, pk=None):
        proceso = self.get_object()
        if proceso.activo:
            return Response({"error": "La plantilla ya se encuentra activa."}, status=status.HTTP_400_BAD_REQUEST)
        proceso.activo = True
        proceso.save()
        registrar(request, 'RECETA', 'RESTAURAR', f"Receta restaurada: {proceso.nombre}", objeto=proceso, cambios={'activo': [False, True]})
        return Response({"mensaje": f"La plantilla '{proceso.nombre}' ha sido restaurada exitosamente y está lista para uso."}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='clonar')
    @transaction.atomic
    def clonar(self, request, pk=None):
        original = self.get_object()
        nuevo_nombre = request.data.get('nuevo_nombre')
        if not nuevo_nombre:
            return Response({"error": "Debe proporcionar un nombre para la nueva plantilla."}, status=status.HTTP_400_BAD_REQUEST)
        if ProcesoMaestro.objects.filter(nombre=nuevo_nombre).exists():
            return Response({"error": f"Ya existe una receta maestra con el nombre '{nuevo_nombre}'."}, status=status.HTTP_400_BAD_REQUEST)

        nuevo_proceso = ProcesoMaestro.objects.create(nombre=nuevo_nombre, descripcion=original.descripcion, activo=True)

        mapa_etapas = {}
        for etapa in original.etapas.all():
            nueva_etapa = EtapaProceso.objects.create(proceso=nuevo_proceso, nombre=etapa.nombre, orden=etapa.orden)
            mapa_etapas[etapa.id] = nueva_etapa

        mapa_ops = {}
        for op in original.operaciones.all():
            nueva_op = OperacionProceso.objects.create(
                proceso=nuevo_proceso,
                etapa=mapa_etapas.get(op.etapa_id) if op.etapa_id else None,
                identificador_paso=op.identificador_paso,
                nombre=op.nombre,
                orden=op.orden,
                tipo_operacion=op.tipo_operacion,
                duracion_horas=op.duracion_horas,
                frecuencia_muestreo_horas=op.frecuencia_muestreo_horas,
                duracion_muestreo_horas=op.duracion_muestreo_horas,
                ops_muestreo=op.ops_muestreo,
                tipo_dependencia=op.tipo_dependencia,
                desfase_horas=op.desfase_horas,
                tolerancia_antes_horas=op.tolerancia_antes_horas,
                tolerancia_despues_horas=op.tolerancia_despues_horas,
                personal_requerido=op.personal_requerido,
                muestreo_inicial=op.muestreo_inicial,
                captura_datos=op.captura_datos,
                edad_cero=op.edad_cero,
                edad_cero_lote=op.edad_cero_lote,
            )
            clonar_secciones(op, nueva_op)
            EquipoOperacion.objects.bulk_create([
                EquipoOperacion(operacion=nueva_op, tipo_id=e.tipo_id, cantidad=e.cantidad, aplica_a=e.aplica_a,
                                horas_preparacion=e.horas_preparacion, horas_limpieza=e.horas_limpieza)
                for e in op.equipos.all()
            ])
            MaterialOperacion.objects.bulk_create([
                MaterialOperacion(operacion=nueva_op, material_id=m.material_id, cantidad=m.cantidad,
                                  anticipacion_horas=m.anticipacion_horas, aplica_a=m.aplica_a)
                for m in op.materiales.all()
            ])
            for req in op.requerimientos_rol.all():
                RequerimientoPersonalFase.objects.create(operacion=nueva_op, rol=req.rol, cantidad=req.cantidad)
            mapa_ops[op.id] = nueva_op

        for op in original.operaciones.all():
            if op.predecesora_id:
                nueva_op_actual = mapa_ops[op.id]
                nueva_op_predecesora = mapa_ops.get(op.predecesora_id)
                if nueva_op_predecesora:
                    nueva_op_actual.predecesora = nueva_op_predecesora
                    nueva_op_actual.save()

        clonar_indicadores(original, nuevo_proceso, mapa_etapas)

        registrar(request, 'RECETA', 'CLONAR', f"Receta '{original.nombre}' clonada como '{nuevo_nombre}'", objeto=nuevo_proceso,
                  cambios={'origen': [None, original.nombre], 'actividades': [None, len(mapa_ops)]})
        return Response({"mensaje": f"Plantilla clonada exitosamente como '{nuevo_nombre}'.", "nuevo_id": nuevo_proceso.id}, status=status.HTTP_201_CREATED)


class EtapaProcesoViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    auditoria_categoria, auditoria_nombre = 'RECETA', 'etapa'
    queryset = EtapaProceso.objects.all().order_by('proceso', 'orden')
    serializer_class = EtapaProcesoSerializer
    permiso_escritura = 'editar_receta'


class OperacionProcesoViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    auditoria_categoria, auditoria_nombre = 'RECETA', 'actividad'
    queryset = OperacionProceso.objects.prefetch_related('materiales__material', 'equipos__tipo', 'secciones_captura__parametros__parametro').all().order_by('proceso', 'orden', 'id')
    serializer_class = OperacionProcesoSerializer
    permiso_escritura = 'editar_receta'
    permisos_por_accion = {'validar_disponibilidad': SOLO_SESION}  # POST de solo consulta

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except RestrictedError:
            return Response({"error": "Violación GxP (Integridad Referencial): No se puede eliminar esta operación porque ya se han fabricado Lotes que dependen de este registro. En su lugar, archive toda la plantilla."}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'], url_path='validar-disponibilidad')
    def validar_disponibilidad(self, request, pk=None):
        operacion = self.get_object()
        fecha_str = request.data.get('fecha')
        if not fecha_str:
            return Response({"error": "El parámetro 'fecha' es obligatorio."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            fecha_evaluacion = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({"error": "Formato de fecha inválido."}, status=status.HTTP_400_BAD_REQUEST)

        resultado = validar_disponibilidad_personal_fase(operacion.id, fecha_evaluacion)
        return Response(resultado, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='bulk-reorder')
    @transaction.atomic
    def bulk_reorder(self, request):
        ids_ordenados = request.data.get('operaciones_ordenadas', [])
        if not isinstance(ids_ordenados, list) or not ids_ordenados:
            return Response({"error": "Se requiere una lista válida 'operaciones_ordenadas' con los IDs de las actividades."}, status=status.HTTP_400_BAD_REQUEST)
        cambios = {}
        for index, op_id in enumerate(ids_ordenados):
            try:
                operacion = OperacionProceso.objects.get(id=op_id)
            except OperacionProceso.DoesNotExist:
                return Response({"error": f"La operación con ID {op_id} no existe."}, status=status.HTTP_404_NOT_FOUND)
            if operacion.orden != index + 1:
                cambios[f"[{operacion.identificador_paso}] {operacion.nombre}"] = [operacion.orden, index + 1]
                operacion.orden = index + 1
                operacion.save(update_fields=['orden'])
        if cambios:
            registrar(request, 'RECETA', 'REORDENAR', f"Reordenamiento de actividades de la receta {operacion.proceso.nombre}",
                      objeto=operacion.proceso, cambios=cambios)
        return Response({"mensaje": "Secuencia de operaciones actualizada correctamente."}, status=status.HTTP_200_OK)


# ==============================================================================
# 2. VIEWSETS TRANSACCIONALES (EJECUCIÓN DE LOTES Y REGLAS GxP)
# ==============================================================================

class LoteProduccionViewSet(viewsets.ModelViewSet):
    # Un lote instanciado no se edita: sus cambios pasan por abortar/archivar y por las acciones de sus fases
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        base = LoteProduccion.objects.filter(archivado=False).exclude(estado='ABORTADO').select_related('proceso_maestro').order_by('-created_at')
        if self.action in ('list', 'gantt'):
            # Listas sin tareas: el avance se cuenta en la base (un lote puede tener miles de tareas)
            return base.annotate(n_fases=Count('fases'),
                                 n_fases_cerradas=Count('fases', filter=Q(fases__estado__in=['COMPLETADA', 'OMITIDA'])))
        return base.prefetch_related('fases__operacion_maestra__etapa', 'fases__operadores_asignados', 'fases__materiales__material', 'fases__materiales__entregas__devoluciones', 'fases__equipos__tipo', 'fases__equipos__reservas__equipo', 'fases__tomas_datos')

    def get_serializer_class(self):
        return LoteResumenSerializer if self.action == 'list' else LoteProduccionSerializer

    @action(detail=False, methods=['get'], url_path='gantt')
    def gantt(self, request):
        """Barras por etapa de los lotes abiertos y de los terminados en los últimos 30 días (`?todos=1`: todos)."""
        lotes, ocultos = lotes_para_gantt(LoteProduccion.objects.filter(archivado=False).exclude(estado='ABORTADO')
                                          .order_by('-created_at'), todos=request.query_params.get('todos') == '1')
        return Response({'lotes': resumen_gantt(lotes), 'ocultos': ocultos})
    permisos_por_accion = {
        'create': 'instanciar_lote',
        'destroy': 'abortar_lote', 'archivar': 'abortar_lote', 'abortar': 'abortar_lote',
    }

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lote = serializer.save()
        FaseLote.objects.bulk_create(construir_fases_lote(lote))
        generar_materiales_lote(lote)
        generar_equipos_lote(lote)
        generar_plan_captura(lote)
        registrar(request, 'LOTE', 'CREAR', f"Lote {lote.identificador_lote} instanciado con la receta {lote.proceso_maestro.nombre}",
                  objeto=lote, lote=lote, cambios={
                      'receta': [None, lote.proceso_maestro.nombre],
                      'inicio_planeado': [None, timezone.localtime(lote.fecha_inicio_planeada).strftime('%Y-%m-%d %H:%M')],
                      'fases': [None, lote.fases.count()],
                  })
        headers = self.get_success_headers(serializer.data)
        response_serializer = self.get_serializer(lote)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def destroy(self, request, *args, **kwargs):
        lote = self.get_object()
        if lote.estado != 'PLANEADO':
            return Response({"error": f"Violación GxP (Data Integrity): No se puede eliminar el Lote '{lote.identificador_lote}' porque su estado actual es '{lote.estado}'."}, status=status.HTTP_403_FORBIDDEN)
        firmante, error = _firma_o_respuesta(request, 'ELIMINAR_LOTE')
        if error:
            return error
        codigo, lote_id = lote.identificador_lote, lote.pk
        self.perform_destroy(lote)
        registro = registrar(request, 'LOTE', 'ELIMINAR', f"Lote planeado {codigo} eliminado", objeto_tipo='loteproduccion',
                             objeto_id=lote_id, lote_codigo=codigo, motivo=firmante['comentario'])
        firmar(registro, firmante)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='archivar')
    def archivar(self, request, pk=None):
        lote = self.get_object()
        if lote.estado != 'COMPLETADO': return Response({"error": "Solo se pueden archivar lotes COMPLETADOS."}, status=status.HTTP_400_BAD_REQUEST)
        firmante, error = _firma_o_respuesta(request, 'ARCHIVAR_LOTE')
        if error:
            return error
        lote.archivado = True
        lote.save()
        firmar(registrar(request, 'LOTE', 'ARCHIVAR', f"Lote {lote.identificador_lote} archivado", objeto=lote, lote=lote,
                         motivo=firmante['comentario'], cambios={'archivado': [False, True]}), firmante)
        return Response({"mensaje": f"El lote {lote.identificador_lote} ha sido archivado."}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='abortar')
    @transaction.atomic
    def abortar(self, request, pk=None):
        lote = self.get_object()
        if lote.estado in ['COMPLETADO', 'ABORTADO']: return Response({"error": f"No es posible abortar un lote en estado: {lote.estado}."}, status=status.HTTP_400_BAD_REQUEST)
        motivo = request.data.get('motivo_aborto')
        if not motivo or len(motivo.strip()) < 10: return Response({"error": "Debe proporcionar un motivo detallado (mínimo 10 caracteres)."}, status=status.HTTP_400_BAD_REQUEST)
        firmante, error = _firma_o_respuesta(request, 'ABORTAR_LOTE')
        if error:
            return error
        estado_anterior = lote.estado
        lote.estado = 'ABORTADO'
        lote.motivo_aborto = motivo
        lote.save()
        firmar(registrar(request, 'LOTE', 'ABORTAR', f"Lote {lote.identificador_lote} abortado", objeto=lote, lote=lote,
                         motivo=motivo, cambios={'estado': [estado_anterior, 'ABORTADO']}), firmante)
        tiempo_actual = timezone.now()
        fases_activas = lote.fases.exclude(estado__in=['COMPLETADA', 'OMITIDA'])
        for fase in fases_activas:
            if fase.estado == 'EN_PROGRESO': fase.fecha_fin_real = tiempo_actual
            fase.estado = 'OMITIDA'
            fase.save()
        return Response({"mensaje": f"El lote {lote.identificador_lote} ha sido abortado."}, status=status.HTTP_200_OK)


class FaseLoteViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Las fases se crean al instanciar el lote y no se borran. Estado y horarios cambian únicamente vía
    `cambiar-estado` y `reprogramar`, que aplican las reglas GxP; los equipos, vía `/api/equipos-fase/`.
    El listado se filtra con `?lote=<id>` y/o `?desde=&hasta=` (fecha-hora ISO; fases cuyo horario programado
    se cruza con esa ventana). Con cientos de lotes de miles de tareas, las pantallas deben pedir siempre un filtro.
    """
    serializer_class = FaseLoteSerializer
    permission_classes = [PermisoFaseLote]
    permisos_por_accion = {
        'reprogramar': 'reprogramar_fase',
        'cambiar_estado': 'ejecutar_fase',
    }

    def get_queryset(self):
        return FaseLote.objects.select_related('operacion_maestra__etapa', 'lote').prefetch_related(
            'materiales__material', 'materiales__entregas__devoluciones', 'materiales__entregas__material_fase__material', 'materiales__entregas__material_fase__fase__lote',
            'operadores_asignados__operador', 'operadores_asignados__rol_ejercido',
            'equipos__tipo', 'equipos__reservas__equipo', 'tomas_datos',
        ).filter(lote__archivado=False).exclude(lote__estado='ABORTADO').order_by('operacion_maestra__identificador_paso', 'indice_muestreo')

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if self.action != 'list':
            return queryset
        params = self.request.query_params
        if params.get('lote'):
            try:
                queryset = queryset.filter(lote_id=int(params['lote']))
            except ValueError:
                raise ValidationError({'lote': 'Debe ser un número.'})
        desde, hasta = self._fecha_param('desde'), self._fecha_param('hasta')
        if hasta:
            queryset = queryset.filter(inicio_programado__lt=hasta)
        if desde:
            queryset = queryset.filter(Q(fin_programado__gte=desde) | Q(fin_programado__isnull=True, inicio_programado__gte=desde))
        return queryset

    def _fecha_param(self, nombre):
        """Fecha-hora ISO (o solo fecha, a medianoche local) de un parámetro; None si no viene."""
        texto = (self.request.query_params.get(nombre) or '').strip().replace(' ', '+')
        if not texto:
            return None
        valor = parse_datetime(texto)
        if valor is None:
            fecha = parse_date(texto)
            valor = datetime.combine(fecha, time.min) if fecha else None
        if valor is None:
            raise ValidationError({nombre: 'Fecha u hora inválida (formato ISO).'})
        return timezone.make_aware(valor) if timezone.is_naive(valor) else valor

    @action(detail=True, methods=['post'], url_path='cambiar-estado')
    @transaction.atomic
    def cambiar_estado(self, request, pk=None):
        fase = self.get_object()
        if fase.lote.estado == 'COMPLETADO': return Response({"error": "El Lote de Producción ya está cerrado."}, status=status.HTTP_403_FORBIDDEN)

        nuevo_estado = request.data.get('estado')
        if nuevo_estado not in dict(FaseLote.ESTADO_FASE_CHOICES).keys(): return Response({"error": "Estado GxP no válido."}, status=status.HTTP_400_BAD_REQUEST)

        if nuevo_estado == 'COMPLETADA' and not fase.operadores_asignados.exists():
            if fase.operacion_maestra.tipo_operacion == 'ACTIVA' or fase.es_subtarea_muestreo:
                return Response({"error": "No se puede completar sin asignar al menos un operador."}, status=status.HTTP_400_BAD_REQUEST)
        if nuevo_estado == fase.estado:
            return Response({"error": f"La fase ya está en estado {nuevo_estado}."}, status=status.HTTP_400_BAD_REQUEST)
        if nuevo_estado == 'COMPLETADA':
            # Los datos de proceso obligatorios se capturan antes de cerrar la tarea
            pendientes = datos_pendientes(fase)
            if pendientes:
                return Response({"error": pendientes, "codigo": "DATOS_PENDIENTES"}, status=status.HTTP_400_BAD_REQUEST)

        tiempo_actual = timezone.now()

        # Al iniciar: la dependencia debe cumplirse y, fuera de la ventana de tolerancia, se exige motivo.
        # Se revisa antes de la firma para no contar como intento fallido algo que no es de la contraseña.
        evaluacion, motivo_desviacion = None, (request.data.get('motivo_desviacion') or '').strip()
        if fase.estado == 'PENDIENTE' and nuevo_estado in ('EN_PROGRESO', 'COMPLETADA'):
            evaluacion = evaluar_inicio(fase, tiempo_actual)
            if evaluacion['bloqueo']:
                return Response({"error": evaluacion['bloqueo'], "codigo": evaluacion['codigo_bloqueo']}, status=status.HTTP_400_BAD_REQUEST)
            if evaluacion['desviacion'] == 'ADELANTO' and not request.user.is_authenticated:
                # En la terminal no se adelanta fuera de tolerancia: lo autoriza un supervisor desde Piso de planta
                return Response({"error": f"Esta tarea aún no está disponible. Puedes iniciarla a partir de las {formatear_hora(evaluacion['desde'])}. "
                                          "Si debe adelantarse, pide a tu supervisor que la inicie desde Piso de planta.",
                                 "codigo": "FUERA_DE_VENTANA"}, status=status.HTTP_403_FORBIDDEN)
            if evaluacion['desviacion'] and len(motivo_desviacion) < 10:
                return Response({"error": f"{evaluacion['mensaje']} Escribe el motivo (mínimo 10 caracteres).",
                                 "codigo": "MOTIVO_REQUERIDO", "desviacion": evaluacion['desviacion']},
                                status=status.HTTP_400_BAD_REQUEST)

        # Registro eBR: cada cambio de estado se firma (contraseña en web, PIN en la terminal)
        firmante, error = _firma_o_respuesta(request, f"FASE_{nuevo_estado}")
        if error:
            return error

        # El material incompleto no impide iniciar: se avisa y queda en la bitácora
        advertencia_materiales = advertencias_surtido(fase) if evaluacion is not None else []

        ejecutar_auto_ajuste = False
        estado_anterior = fase.estado
        lote_estado_anterior = fase.lote.estado

        if nuevo_estado == 'EN_PROGRESO' and fase.estado == 'PENDIENTE':
            fase.fecha_inicio_real = tiempo_actual
            # Sus muestreos y sucesoras se recalculan desde el inicio real (si arrancó antes o después)
            ejecutar_auto_ajuste = True
        elif nuevo_estado == 'COMPLETADA' and fase.estado == 'EN_PROGRESO':
            fase.fecha_fin_real = tiempo_actual
            # Siempre intentaremos re-alinear las tareas siguientes al final REAL de esta tarea
            ejecutar_auto_ajuste = True

        fase.estado = nuevo_estado
        fase.save()

        # Enganche estricto de las sucesoras al término real de esta fase
        fases_actualizadas_count = 0
        if ejecutar_auto_ajuste:
            momento = 'inicio' if nuevo_estado == 'EN_PROGRESO' else 'término'
            fases_actualizadas_count = propagar_programacion(
                fase,
                nota_tarea=f"(Auto-Ajuste) Enganche automático con el {momento} real de [{{paso}}].",
                nota_muestreo="(Auto-Ajuste) Muestreo alineado con el inicio real de [{paso}].",
            )

        lote = fase.lote
        todas_fases = lote.fases.all()
        todas_completadas = all(f.estado == 'COMPLETADA' or f.estado == 'OMITIDA' for f in todas_fases)
        alguna_en_progreso = any(f.estado in ['EN_PROGRESO', 'COMPLETADA'] for f in todas_fases)

        if todas_completadas:
            lote.estado = 'COMPLETADO'
            lote.save()
        elif alguna_en_progreso and lote.estado == 'PLANEADO':
            lote.estado = 'EN_PROGRESO'
            lote.save()

        textos = {'EN_PROGRESO': 'iniciada', 'COMPLETADA': 'completada', 'PENDIENTE': 'regresada a pendiente', 'OMITIDA': 'omitida'}
        cambios = {'estado': [estado_anterior, nuevo_estado]}
        if fases_actualizadas_count:
            cambios['sucesoras_reajustadas'] = [None, fases_actualizadas_count]
        if advertencia_materiales:
            cambios['materiales_incompletos'] = [None, advertencia_materiales]
        motivo = firmante['comentario']
        if evaluacion and evaluacion['desviacion']:
            cambios['desviacion_inicio'] = [None, evaluacion['mensaje']]
            motivo = f"{evaluacion['desviacion'].capitalize()}: {motivo_desviacion}" + (f" · {motivo}" if motivo else '')
        registro = registrar(request, 'FASE', f"FASE_{nuevo_estado}", f"Fase {textos.get(nuevo_estado, nuevo_estado)}: {self._nombre_fase(fase)}",
                             objeto=fase, fase=fase, cambios=cambios, motivo=motivo)
        firmar(registro, firmante)
        if lote.estado != lote_estado_anterior:
            registrar(request, 'LOTE', f"LOTE_{lote.estado}", f"Lote {lote.identificador_lote} pasa a {lote.get_estado_display()}",
                      objeto=lote, lote=lote, cambios={'estado': [lote_estado_anterior, lote.estado]})

        response_data = self.get_serializer(fase).data
        if advertencia_materiales:
            response_data['advertencia_materiales'] = advertencia_materiales
        if ejecutar_auto_ajuste and fases_actualizadas_count > 0:
            mensaje = f"Se auto-ajustaron {fases_actualizadas_count} tareas posteriores."
            # Lo que el ajuste dejó mal (cruces, turnos, materiales) se avisa aquí y Planificación lo marca
            alertas = alertas_programacion(lote.fases.select_related('operacion_maestra', 'lote'))
            if alertas:
                total = sum(len(v) for v in alertas.values())
                mensaje += f"\n\n⚠️ Revisa Planificación: {total} alerta(s) de personal o materiales en este lote."
            response_data['mensaje_cascada'] = mensaje

        return Response(response_data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='disponibles')
    def disponibles(self, request, pk=None):
        """Operadores con turno a la hora de la actividad y sin otra tarea encimada (panel de Planificación)."""
        return Response(operadores_disponibles(self.get_object()))

    @action(detail=False, methods=['get'], url_path='alertas')
    def alertas(self, request):
        """{fase_id: [mensajes]} de las fases por iniciar con cruces de personal, operadores sin turno
        o materiales que por un adelanto debían estar listos antes de ahora."""
        # Consulta ligera: las alertas hacen sus propias consultas y de cada fase solo usan horarios y estado
        fases = (FaseLote.objects.filter(estado='PENDIENTE', lote__estado__in=['PLANEADO', 'EN_PROGRESO'], lote__archivado=False,
                                         fin_programado__gt=timezone.now())
                 .select_related('operacion_maestra', 'lote').defer('plan_captura'))
        return Response(alertas_programacion(fases))

    @staticmethod
    def _nombre_fase(fase):
        nombre = fase.nombre_tarea_dinamica if fase.es_subtarea_muestreo and fase.nombre_tarea_dinamica else fase.operacion_maestra.nombre
        return f"[{fase.operacion_maestra.identificador_paso}] {nombre} · lote {fase.lote.identificador_lote}"

    @action(detail=True, methods=['post'], url_path='reprogramar')
    @transaction.atomic
    def reprogramar(self, request, pk=None):
        fase_origen = self.get_object()
        
        if fase_origen.lote.estado == 'COMPLETADO': return Response({"error": "El Lote está cerrado, no se admiten ajustes."}, status=status.HTTP_403_FORBIDDEN)
        if fase_origen.estado in ['COMPLETADA', 'EN_PROGRESO']: return Response({"error": "No se puede alterar el Forecast de una tarea que ya inició o finalizó en planta."}, status=status.HTTP_403_FORBIDDEN)

        nueva_fecha_str = request.data.get('fecha_programada')
        nueva_hora_str = request.data.get('hora_inicio_programada')
        motivo = request.data.get('motivo_reprogramacion')
        notas = request.data.get('notas_reprogramacion', '')

        if not all([nueva_fecha_str, nueva_hora_str, motivo]): return Response({"error": "Faltan campos obligatorios."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            nueva_fecha = datetime.strptime(nueva_fecha_str, '%Y-%m-%d').date()
            nueva_hora = datetime.strptime(nueva_hora_str, '%H:%M').time()
        except ValueError:
            return Response({"error": "Formato de fecha u hora inválido."}, status=status.HTTP_400_BAD_REQUEST)

        nuevo_inicio = timezone.make_aware(datetime.combine(nueva_fecha, nueva_hora))

        error_dependencia = validar_inicio_contra_predecesora(fase_origen, nuevo_inicio)
        if error_dependencia:
            return Response({"error": error_dependencia}, status=status.HTTP_400_BAD_REQUEST)

        formato = '%Y-%m-%d %H:%M'
        inicio_anterior = timezone.localtime(fase_origen.inicio_programado).strftime(formato) if fase_origen.inicio_programado else None
        fase_origen.inicio_programado = nuevo_inicio
        fase_origen.fin_programado = nuevo_inicio + fase_origen.duracion_planeada
        fase_origen.motivo_reprogramacion = motivo
        fase_origen.notas_reprogramacion = notas
        fase_origen.save()

        # Propagación hacia adelante de las sucesoras pendientes
        fases_actualizadas = 1 + propagar_programacion(
            fase_origen,
            nota_tarea="(Auto-Ajuste) Re-alineación automática originada por el supervisor en [{origen}].",
            nota_muestreo="(Auto-Ajuste) Muestreo alineado solidariamente.",
        )

        registrar(request, 'FASE', 'REPROGRAMAR', f"Fase reprogramada: {self._nombre_fase(fase_origen)}",
                  objeto=fase_origen, fase=fase_origen, motivo=f"{fase_origen.get_motivo_reprogramacion_display()}. {notas}".strip(' .'),
                  cambios={'inicio_programado': [inicio_anterior, timezone.localtime(nuevo_inicio).strftime(formato)],
                           'sucesoras_reajustadas': [None, fases_actualizadas - 1]})

        return Response({
            "mensaje": f"Ajuste completado. El sistema auto-alineó estrictamente {fases_actualizadas - 1} tareas sucesoras evitando cualquier traslape (Snapping).",
            "fase": self.get_serializer(fase_origen).data
        }, status=status.HTTP_200_OK)


class AsignacionFaseOperadorViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    auditoria_categoria, auditoria_nombre = 'ASIGNACION', 'asignación'

    def _auditoria_contexto(self, instancia):
        return {'fase': instancia.fase_lote}

    def _auditoria_datos(self, instancia):
        return {'operador': instancia.operador.nombre, 'rol': instancia.rol_ejercido.nombre if instancia.rol_ejercido_id else None,
                'fase': FaseLoteViewSet._nombre_fase(instancia.fase_lote)}

    # Sin PUT/PATCH: cambiar una asignación saltaría la validación de cruces; se elimina y se crea de nuevo
    http_method_names = ['get', 'post', 'delete', 'head', 'options']
    queryset = AsignacionFaseOperador.objects.select_related('operador', 'rol_ejercido').all()
    serializer_class = AsignacionFaseOperadorSerializer
    permiso_escritura = 'asignar_personal'

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        fase_id = request.data.get('fase_lote')
        operador_id = request.data.get('operador')
        
        try:
            fase_actual = FaseLote.objects.get(id=fase_id)
        except FaseLote.DoesNotExist:
            return Response({"error": "La fase no existe."}, status=status.HTTP_404_NOT_FOUND)

        if fase_actual.lote.estado == 'COMPLETADO': return Response({"error": "Lote cerrado."}, status=status.HTTP_403_FORBIDDEN)
        if fase_actual.estado in ['COMPLETADA', 'OMITIDA']: return Response({"error": f"Fase en estado {fase_actual.estado}."}, status=status.HTTP_400_BAD_REQUEST)

        conflicto = buscar_conflicto_operador(operador_id, fase_actual)
        if conflicto:
            fase_existente = conflicto.fase_lote
            nombre_tarea = fase_existente.nombre_tarea_dinamica if fase_existente.es_subtarea_muestreo else fase_existente.operacion_maestra.nombre
            formato = '%d/%m %H:%M'
            return Response({"error": (
                f"Conflicto de turnos GxP: El operador ya está asignado a [{fase_existente.operacion_maestra.identificador_paso}] {nombre_tarea} "
                f"de {timezone.localtime(fase_existente.inicio_programado).strftime(formato)} a {timezone.localtime(fase_existente.fin_programado).strftime(formato)}."
            )}, status=status.HTTP_400_BAD_REQUEST)

        return super().create(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        asignacion = self.get_object()
        if asignacion.fase_lote.estado != 'PENDIENTE':
            return Response({"error": f"Violación GxP: No se puede retirar al operador de una fase en estado {asignacion.fase_lote.estado}."}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


def _cantidad(mf):
    """Cantidad legible para la bitácora: 2.000 L → '2 L'."""
    return f"{format(mf.cantidad.normalize(), 'f')} {mf.unidad_medida}"


def _decimal(valor):
    try:
        return Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _horas(valor):
    if valor in (None, ''):
        return None
    try:
        horas = float(valor)
    except (TypeError, ValueError):
        raise ErrorMaterialFase("La anticipación debe ser un número de horas.")
    if horas < 0:
        raise ErrorMaterialFase("La anticipación no puede ser negativa.")
    return horas


class MaterialFaseViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Materiales de las fases de lote. Se generan al instanciar el lote; los cambios pasan por
    `agregar`, `ajustar` y `retirar`, que exigen motivo (trazabilidad GxP). Filtro: ?fase=<id>.
    `requerimientos` alimenta el monitor de materiales por día y hora.
    """
    serializer_class = MaterialFaseSerializer
    permiso_escritura = 'ajustar_material_lote'

    def get_queryset(self):
        qs = MaterialFase.objects.select_related('material', 'fase').prefetch_related(
            'entregas__devoluciones', 'entregas__material_fase__material', 'entregas__material_fase__fase__lote',
        ).order_by('fase', 'material__nombre')
        if self.request.query_params.get('fase'):
            qs = qs.filter(fase_id=self.request.query_params['fase'])
        return qs

    def _error(self, mensaje):
        return Response({"error": mensaje}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='agregar')
    @transaction.atomic
    def agregar(self, request):
        try:
            fase = FaseLote.objects.select_related('lote').get(id=request.data.get('fase'))
            material = MaterialInsumo.objects.get(id=request.data.get('material'))
        except (FaseLote.DoesNotExist, MaterialInsumo.DoesNotExist, ValueError):
            return self._error("La fase o el material no existen.")
        try:
            mf = agregar_material_fase(
                fase, material, _decimal(request.data.get('cantidad')),
                _horas(request.data.get('anticipacion_horas')), request.data.get('motivo'),
            )
        except ErrorMaterialFase as e:
            return self._error(str(e))
        registrar(request, 'MATERIAL_LOTE', 'AGREGAR', f"Material {material.id} agregado a {FaseLoteViewSet._nombre_fase(fase)}",
                  objeto=mf, fase=fase, motivo=request.data.get('motivo', ''),
                  cambios={'material': [None, material.nombre], 'cantidad': [None, _cantidad(mf)],
                           'anticipacion_horas': [None, mf.anticipacion_horas]})
        return Response(self.get_serializer(mf).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='ajustar')
    @transaction.atomic
    def ajustar(self, request, pk=None):
        mf = self.get_object()
        antes = {'cantidad': _cantidad(mf), 'anticipacion_horas': mf.anticipacion_horas}
        try:
            ajustar_material_fase(
                mf, _decimal(request.data.get('cantidad')),
                _horas(request.data.get('anticipacion_horas')), request.data.get('motivo'),
            )
        except ErrorMaterialFase as e:
            return self._error(str(e))
        registrar(request, 'MATERIAL_LOTE', 'AJUSTAR', f"Material {mf.material_id} ajustado en {FaseLoteViewSet._nombre_fase(mf.fase)}",
                  objeto=mf, fase=mf.fase, motivo=request.data.get('motivo', ''),
                  cambios=diferencias(antes, {'cantidad': _cantidad(mf), 'anticipacion_horas': mf.anticipacion_horas}))
        return Response(self.get_serializer(mf).data)

    @action(detail=True, methods=['post'], url_path='retirar')
    @transaction.atomic
    def retirar(self, request, pk=None):
        mf = self.get_object()
        try:
            retirar_material_fase(mf, request.data.get('motivo'))
        except ErrorMaterialFase as e:
            return self._error(str(e))
        registrar(request, 'MATERIAL_LOTE', 'RETIRAR', f"Material {mf.material_id} retirado de {FaseLoteViewSet._nombre_fase(mf.fase)}",
                  objeto=mf, fase=mf.fase, motivo=request.data.get('motivo', ''), cambios={'activo': [True, False]})
        return Response(self.get_serializer(mf).data)

    @action(detail=False, methods=['get'], url_path='requerimientos')
    def requerimientos(self, request):
        """?desde=YYYY-MM-DD&hasta=YYYY-MM-DD (ambos días incluidos, en hora local)."""
        try:
            desde = datetime.strptime(request.query_params.get('desde', ''), '%Y-%m-%d').date()
            hasta = datetime.strptime(request.query_params.get('hasta', ''), '%Y-%m-%d').date()
        except ValueError:
            return self._error("Indique 'desde' y 'hasta' con formato YYYY-MM-DD.")
        if hasta < desde or (hasta - desde).days > 62:
            return self._error("El rango debe ser válido y de máximo 62 días.")

        inicio = timezone.make_aware(datetime.combine(desde, time.min))
        fin = timezone.make_aware(datetime.combine(hasta + timedelta(days=1), time.min))
        filas = requerimientos_materiales(inicio, fin)
        return Response(RequerimientoMaterialSerializer(filas, many=True).data)


def _entero(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _horas_equipo(valor):
    if valor in (None, ''):
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        raise ErrorEquipoFase("Las horas deben ser un número.")


class EquipoFaseViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Equipos de las fases de lote. El requerimiento (tipo y cantidad) se copia de la receta al instanciar
    el lote; `agregar`, `ajustar` y `retirar` exigen motivo. Los equipos concretos se reservan con `reservar`
    y se liberan con `liberar`; con la fase en ejecución, `cambiar` sustituye el equipo con motivo y firma.
    Filtro: ?fase=<id>. `ocupacion` alimenta el monitor de equipos.
    """
    serializer_class = EquipoFaseSerializer
    permiso_escritura = 'asignar_personal'
    permisos_por_accion = {
        'agregar': 'ajustar_material_lote', 'ajustar': 'ajustar_material_lote', 'retirar': 'ajustar_material_lote',
        'reservar': 'asignar_personal', 'liberar': 'asignar_personal', 'cambiar': 'asignar_personal',
    }

    def get_queryset(self):
        qs = EquipoFase.objects.select_related('tipo', 'fase__lote', 'fase__operacion_maestra').prefetch_related(
            'reservas__equipo').order_by('fase', 'tipo__nombre')
        if self.request.query_params.get('fase'):
            qs = qs.filter(fase_id=self.request.query_params['fase'])
        return qs

    def _error(self, mensaje, estado=status.HTTP_400_BAD_REQUEST):
        return Response({"error": mensaje}, status=estado)

    def _datos(self, ef):
        ef = self.get_queryset().get(id=ef.id)  # recarga con sus reservas
        return self.get_serializer(ef).data

    @staticmethod
    def _resumen(ef):
        return {'cantidad': ef.cantidad, 'horas_preparacion': ef.horas_preparacion, 'horas_limpieza': ef.horas_limpieza}

    @action(detail=False, methods=['post'], url_path='agregar')
    @transaction.atomic
    def agregar(self, request):
        try:
            fase = FaseLote.objects.select_related('lote').get(id=request.data.get('fase'))
            tipo = TipoEquipo.objects.get(codigo=request.data.get('tipo'))
        except (FaseLote.DoesNotExist, TipoEquipo.DoesNotExist, ValueError):
            return self._error("La fase o el tipo de equipo no existen.")
        try:
            ef = agregar_equipo_fase(fase, tipo, _entero(request.data.get('cantidad')),
                                     _horas_equipo(request.data.get('horas_preparacion')),
                                     _horas_equipo(request.data.get('horas_limpieza')), request.data.get('motivo'))
        except ErrorEquipoFase as e:
            return self._error(str(e))
        registrar(request, 'EQUIPO_LOTE', 'AGREGAR', f"Equipo {tipo.nombre} agregado a {FaseLoteViewSet._nombre_fase(fase)}",
                  objeto=ef, fase=fase, motivo=ef.motivo_ajuste, cambios=diferencias(None, {'tipo': tipo.nombre, **self._resumen(ef)}))
        return Response(self._datos(ef), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='ajustar')
    @transaction.atomic
    def ajustar(self, request, pk=None):
        ef = self.get_object()
        antes = self._resumen(ef)
        try:
            ajustar_equipo_fase(ef, _entero(request.data.get('cantidad')), _horas_equipo(request.data.get('horas_preparacion')),
                                _horas_equipo(request.data.get('horas_limpieza')), request.data.get('motivo'))
        except ErrorEquipoFase as e:
            return self._error(str(e))
        registrar(request, 'EQUIPO_LOTE', 'AJUSTAR', f"Equipo {ef.tipo.nombre} ajustado en {FaseLoteViewSet._nombre_fase(ef.fase)}",
                  objeto=ef, fase=ef.fase, motivo=ef.motivo_ajuste, cambios=diferencias(antes, self._resumen(ef)))
        return Response(self._datos(ef))

    @action(detail=True, methods=['post'], url_path='retirar')
    @transaction.atomic
    def retirar(self, request, pk=None):
        ef = self.get_object()
        try:
            retirar_equipo_fase(ef, request.data.get('motivo'))
        except ErrorEquipoFase as e:
            return self._error(str(e))
        registrar(request, 'EQUIPO_LOTE', 'RETIRAR', f"Equipo {ef.tipo.nombre} retirado de {FaseLoteViewSet._nombre_fase(ef.fase)}",
                  objeto=ef, fase=ef.fase, motivo=ef.motivo_ajuste, cambios={'activo': [True, False]})
        return Response(self._datos(ef))

    @action(detail=True, methods=['get'], url_path='candidatos')
    def candidatos(self, request, pk=None):
        """Equipos del tipo pedido, con el motivo por el que no se pueden reservar (null si están libres).
        ?desde=ahora calcula la disponibilidad desde este momento (para un cambio durante la ejecución)."""
        ef = self.get_object()
        desde = timezone.now() if request.query_params.get('desde') == 'ahora' else None
        return Response([
            {'id': c['equipo'].id, 'nombre': c['equipo'].nombre, 'area': c['equipo'].area,
             'estado': c['equipo'].get_estado_display(), 'disponible': c['motivo'] is None, 'motivo': c['motivo']}
            for c in equipos_candidatos(ef, desde)
        ])

    @action(detail=True, methods=['post'], url_path='reservar')
    @transaction.atomic
    def reservar(self, request, pk=None):
        ef = self.get_object()
        try:
            equipo = Equipo.objects.select_related('tipo').get(id=request.data.get('equipo'))
        except Equipo.DoesNotExist:
            return self._error("El equipo no existe.")
        try:
            reserva = reservar_equipo(ef, equipo)
        except ErrorEquipoFase as e:
            return self._error(str(e))
        inicio, fin = reserva.ventana()
        registrar(request, 'EQUIPO_LOTE', 'RESERVAR', f"Equipo [{equipo.id}] {equipo.nombre} reservado para {FaseLoteViewSet._nombre_fase(ef.fase)}",
                  objeto=reserva, fase=ef.fase, cambios={'equipo': [None, f"[{equipo.id}] {equipo.nombre}"],
                                                         'ocupacion': [None, f"{formatear_hora(inicio)} – {formatear_hora(fin)}"]})
        return Response(self._datos(ef), status=status.HTTP_201_CREATED)

    def _reserva(self, ef, request):
        return ef.reservas.select_related('equipo').get(id=request.data.get('reserva'))

    @action(detail=True, methods=['post'], url_path='liberar')
    @transaction.atomic
    def liberar(self, request, pk=None):
        ef = self.get_object()
        try:
            reserva = self._reserva(ef, request)
            liberar_reserva(reserva, request.data.get('motivo', ''))
        except ReservaEquipo.DoesNotExist:
            return self._error("La reserva no existe en este requerimiento.")
        except ErrorEquipoFase as e:
            return self._error(str(e))
        registrar(request, 'EQUIPO_LOTE', 'LIBERAR', f"Equipo [{reserva.equipo_id}] liberado de {FaseLoteViewSet._nombre_fase(ef.fase)}",
                  objeto=reserva, fase=ef.fase, motivo=reserva.motivo, cambios={'equipo': [f"[{reserva.equipo_id}] {reserva.equipo.nombre}", None]})
        return Response(self._datos(ef))

    @action(detail=True, methods=['post'], url_path='cambiar')
    @transaction.atomic
    def cambiar(self, request, pk=None):
        """Sustituye un equipo con la fase en ejecución. Exige motivo y firma electrónica (CAMBIAR_EQUIPO)."""
        ef = self.get_object()
        try:
            reserva = self._reserva(ef, request)
            nuevo = Equipo.objects.select_related('tipo').get(id=request.data.get('equipo'))
        except (ReservaEquipo.DoesNotExist, Equipo.DoesNotExist):
            return self._error("La reserva o el equipo nuevo no existen.")
        # Reglas de negocio primero: un error de datos no debe contar como firma fallida
        try:
            validar_cambio_equipo(reserva, nuevo, request.data.get('motivo'))
        except ErrorEquipoFase as e:
            return self._error(str(e))

        firmante, error = _firma_o_respuesta(request, 'CAMBIAR_EQUIPO')
        if error:
            return error
        try:
            nueva = cambiar_equipo(reserva, nuevo, request.data.get('motivo'))
        except ErrorEquipoFase as e:
            return self._error(str(e))
        registro = registrar(
            request, 'EQUIPO_LOTE', 'CAMBIAR',
            f"Equipo [{reserva.equipo_id}] sustituido por [{nuevo.id}] durante {FaseLoteViewSet._nombre_fase(ef.fase)}",
            objeto=nueva, fase=ef.fase, motivo=nueva.motivo,
            cambios={'equipo': [f"[{reserva.equipo_id}] {reserva.equipo.nombre}", f"[{nuevo.id}] {nuevo.nombre}"],
                     'momento_del_cambio': [None, formatear_hora(nueva.desde, '%Y-%m-%d %H:%M')]})
        firmar(registro, firmante)
        return Response(self._datos(ef))

    @action(detail=False, methods=['get'], url_path='ocupacion')
    def ocupacion(self, request):
        """?desde=YYYY-MM-DD&hasta=YYYY-MM-DD (ambos días incluidos, hora local): tramos reservados por equipo
        y requerimientos que aún no tienen equipo reservado."""
        try:
            desde = datetime.strptime(request.query_params.get('desde', ''), '%Y-%m-%d').date()
            hasta = datetime.strptime(request.query_params.get('hasta', ''), '%Y-%m-%d').date()
        except ValueError:
            return self._error("Indique 'desde' y 'hasta' con formato YYYY-MM-DD.")
        if hasta < desde or (hasta - desde).days > 62:
            return self._error("El rango debe ser válido y de máximo 62 días.")
        inicio = timezone.make_aware(datetime.combine(desde, time.min))
        fin = timezone.make_aware(datetime.combine(hasta + timedelta(days=1), time.min))
        tramos, pendientes = ocupacion_equipos(inicio, fin)

        def fase_info(fase):
            return {'fase_id': fase.id, 'lote_id': fase.lote_id, 'lote_codigo': fase.lote.identificador_lote,
                    'paso': fase.operacion_maestra.identificador_paso, 'fase_estado': fase.estado,
                    'actividad': fase.nombre_tarea_dinamica if fase.es_subtarea_muestreo else fase.operacion_maestra.nombre,
                    'inicio_actividad': fase.fecha_inicio_real or fase.inicio_programado,
                    'fin_actividad': fase.fecha_fin_real or fase.fin_programado}

        return Response({
            'tramos': [{'reserva_id': r.id, 'equipo': r.equipo_id, 'equipo_nombre': r.equipo.nombre,
                        'tipo': r.equipo.tipo_id, 'inicio': r.ventana()[0], 'fin': r.ventana()[1],
                        'cambiado': r.hasta is not None or r.desde is not None, 'motivo': r.motivo,
                        **fase_info(r.equipo_fase.fase)} for r in tramos],
            'pendientes': [{'equipo_fase_id': ef.id, 'tipo': ef.tipo_id, 'tipo_nombre': ef.tipo.nombre, 'faltan': faltan,
                            'inicio': ef.ventana_ocupacion()[0], 'fin': ef.ventana_ocupacion()[1], **fase_info(ef.fase)}
                           for ef, faltan in pendientes],
        })


# ==============================================================================
# 3. VIEWSET MOBILE eBR (EJECUCIÓN EN PISO DE PLANTA)
# ==============================================================================

class MobileeBRViewSet(viewsets.ViewSet):
    # El operador entra con número de empleado y PIN; su identidad queda en la sesión del servidor
    # (no en lo que mande el navegador) y PermisoFaseLote la usa para validar sus tareas.
    permission_classes = [permissions.AllowAny]

    @action(detail=False, methods=['post'], url_path='login')
    def login(self, request):
        codigo = request.data.get('codigo_empleado')
        pin = request.data.get('pin_acceso')
        
        if not codigo or not pin: return Response({"error": "Debe ingresar el Número de Empleado y su PIN."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            operador = Operador.objects.get(codigo_empleado=codigo, activo=True)
        except Operador.DoesNotExist:
            registrar(request, 'SESION', 'PIN_FALLIDO', f"Intento fallido en la terminal con el número de empleado '{codigo}'",
                      actor=f"Terminal: {codigo}")
            return Response({"error": "Credenciales inválidas o usuario inactivo."}, status=status.HTTP_401_UNAUTHORIZED)

        if operador.pin_bloqueado:
            registrar(request, 'SESION', 'PIN_FALLIDO', f"Intento de ingreso con PIN bloqueado: {operador.nombre} ({codigo})",
                      objeto=operador, actor=f"Terminal: {codigo}")
            return Response({"error": "Tu PIN está bloqueado por intentos fallidos. Pide a tu supervisor o a un administrador que lo desbloquee."},
                            status=status.HTTP_403_FORBIDDEN)

        if operador.pin_acceso != str(pin):
            registrar(request, 'SESION', 'PIN_FALLIDO', f"PIN incorrecto en la terminal para {operador.nombre} ({codigo})",
                      objeto=operador, actor=f"Terminal: {codigo}")
            restantes = registrar_fallo_pin(operador, request, 'ingreso a la terminal')
            if restantes == 0:
                return Response({"error": "PIN incorrecto. Tu PIN quedó bloqueado; pide a tu supervisor o a un administrador que lo desbloquee."},
                                status=status.HTTP_403_FORBIDDEN)
            return Response({"error": f"Credenciales inválidas. Te quedan {restantes} intento(s) antes de bloquear el PIN."},
                            status=status.HTTP_401_UNAUTHORIZED)

        reiniciar_intentos_pin(operador)

        # Si en la tablet quedó abierta una sesión web se cierra: la terminal firma y registra solo como el operador.
        # logout() también renueva la llave de sesión (evita fijación de sesión).
        if request.user.is_authenticated:
            auth_logout(request._request)
            request.user = AnonymousUser()  # DRF guarda su propia copia del usuario de la petición
        else:
            request.session.cycle_key()
        request.session['operador_id'] = operador.id
        registrar(request, 'SESION', 'PIN_LOGIN', f"Ingreso a la terminal de {operador.nombre} ({codigo})", objeto=operador)
        return Response({
            "firmas": SIGNIFICADOS,
            # Permisos del usuario web ligado a esta persona (ej. un planeador que también surte desde la tablet)
            "permisos": [c for c in ('surtir_material',) if actor_tiene_permiso(None, operador, c)],
            "operador_id": operador.id, "codigo_empleado": operador.codigo_empleado, "nombre": operador.nombre,
            "rol": operador.rol.nombre if operador.rol else "Operativo Base", "cuadrilla": operador.cuadrilla.nombre
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='sesion')
    def sesion(self, request):
        """Operador con terminal abierta en esta sesión del servidor (la tablet lo compara con el que muestra)."""
        operador = operador_de_sesion(request)
        return Response({'operador_id': operador.id if operador else None,
                         'usuario_web': request.user.get_username() if request.user.is_authenticated else None})

    @action(detail=False, methods=['post'], url_path='logout')
    def logout(self, request):
        if operador_de_sesion(request):
            registrar(request, 'SESION', 'PIN_LOGOUT', "Salida de la terminal del operador", objeto=operador_de_sesion(request))
        request.session.pop('operador_id', None)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'], url_path='tareas-pendientes')
    def tareas_pendientes(self, request, pk=None):
        operador_sesion = operador_de_sesion(request)
        if not request.user.is_authenticated and not (operador_sesion and str(operador_sesion.id) == str(pk)):
            raise PermissionDenied("Tu sesión expiró. Vuelve a ingresar con tu número de empleado y PIN.")
        try:
            operador = Operador.objects.get(id=pk, activo=True)
        except Operador.DoesNotExist:
            return Response({"error": "Operador no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        
        asignaciones = AsignacionFaseOperador.objects.filter(
            operador=operador, fase_lote__lote__archivado=False, fase_lote__lote__estado__in=['PLANEADO', 'EN_PROGRESO']
        ).exclude(fase_lote__estado__in=['COMPLETADA', 'OMITIDA']).select_related(
            'fase_lote', 'fase_lote__lote', 'fase_lote__operacion_maestra', 'fase_lote__lote__proceso_maestro'
        ).prefetch_related(
            'fase_lote__equipos__reservas__equipo', 'fase_lote__materiales__material', 'fase_lote__materiales__entregas__devoluciones',
            'fase_lote__tomas_datos',
        ).order_by('fase_lote__inicio_programado')
        
        tareas_data = []
        ahora = timezone.now()
        for asig in asignaciones:
            fase = asig.fase_lote
            # Qué tan lista está la tarea para iniciar: dependencia y ventana de tolerancia
            disponibilidad = {'bloqueo': None, 'desviacion': None, 'mensaje': '', 'disponible_desde': None}
            if fase.estado == 'PENDIENTE':
                ev = evaluar_inicio(fase, ahora)
                disponibilidad = {'bloqueo': ev['bloqueo'], 'desviacion': ev['desviacion'], 'mensaje': ev['mensaje'],
                                  'disponible_desde': ev['desde']}
            tareas_data.append({
                "fase_id": fase.id, "lote_identificador": fase.lote.identificador_lote, "proceso_nombre": fase.lote.proceso_maestro.nombre,
                "tarea_nombre": fase.nombre_tarea_dinamica if fase.es_subtarea_muestreo else fase.operacion_maestra.nombre,
                "identificador_paso": fase.operacion_maestra.identificador_paso, "tipo_operacion": fase.operacion_maestra.tipo_operacion,
                "estado": fase.estado, "inicio_programado": fase.inicio_programado, "fin_programado": fase.fin_programado,
                "rol_asignado": asig.rol_ejercido.nombre, **disponibilidad,
                "equipos": [f"[{r.equipo_id}] {r.equipo.nombre}" for ef in fase.equipos.all() if ef.activo
                            for r in ef.reservas.all() if r.vigente],
                "materiales": [_material_terminal(mf) for mf in fase.materiales.all() if mf.activo],
                "captura": resumen_captura(fase),
            })

        # Sobrantes por devolver de tareas que ya terminó (últimos 7 días); los de tareas abiertas van en cada tarjeta
        recibidas = EntregaMaterial.objects.filter(
            tipo='ENTREGA', estado='RECIBIDA', material_fase__fase__estado='COMPLETADA',
            material_fase__fase__operadores_asignados__operador=operador, material_fase__fase__lote__archivado=False,
            material_fase__fase__fecha_fin_real__gte=ahora - timedelta(days=7),
        ).select_related('material_fase__material', 'material_fase__fase__lote', 'material_fase__fase__operacion_maestra'
                         ).prefetch_related('devoluciones').distinct()
        sobrantes = []
        for e in recibidas:
            disponible = disponible_para_devolver(e)
            if disponible > 0:
                fase = e.material_fase.fase
                sobrantes.append({**EntregaMaterialSerializer(e).data, 'disponible_devolver': str(disponible),
                                  'actividad': f"[{fase.operacion_maestra.identificador_paso}] {FaseLoteViewSet._nombre_fase(fase)}"})

        return Response({"tareas_pendientes": tareas_data, "sobrantes": sobrantes}, status=status.HTTP_200_OK)


def _material_terminal(mf):
    """Material de una tarea para la tablet: avance del surtido y entregas por recibir o con sobrante."""
    r = resumen_surtido(mf)
    entregas = []
    for e in mf.entregas.all():
        disponible = disponible_para_devolver(e) if e.tipo == 'ENTREGA' and e.estado == 'RECIBIDA' else None
        entregas.append({
            'id': e.id, 'tipo': e.tipo, 'estado': e.estado, 'estado_display': e.get_estado_display(),
            'cantidad': str(e.cantidad), 'unidad_medida': e.unidad_medida, 'lote_material': e.lote_material,
            'caducidad': e.caducidad, 'entregado_por_nombre': e.entregado_por_nombre, 'entregado_en': e.entregado_en,
            'recibido_por_nombre': e.recibido_por_nombre, 'motivo_rechazo': e.motivo_rechazo,
            'disponible_devolver': str(disponible) if disponible is not None else None,
        })
    return {
        'id': mf.id, 'material': mf.material_id, 'material_nombre': mf.material.nombre, 'cantidad': str(mf.cantidad),
        'unidad_medida': mf.unidad_medida, 'momento_requerido': mf.momento_requerido,
        'surtido': {k: (str(v) if not isinstance(v, str) else v) for k, v in r.items()}, 'entregas': entregas,
    }


# ==============================================================================
# 4. SURTIDO DE MATERIALES (ENTREGA Y RECEPCIÓN CON DOBLE FIRMA)
# ==============================================================================

def _validar_sin_guardar(funcion):
    """Corre la regla de negocio y deshace lo que guarde: valida antes de pedir la firma, para no
    contar como intento fallido algo que no es de la contraseña. Lanza ErrorSurtido si no procede."""
    with transaction.atomic():
        funcion()
        transaction.set_rollback(True)


def _fecha(valor):
    try:
        return datetime.strptime(str(valor or ''), '%Y-%m-%d').date()
    except ValueError:
        return None


class EntregaMaterialViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Surtido de materiales a las fases. Cada paso se firma (contraseña en web, PIN en la terminal):
      - `entregar` (almacén o planeación, permiso `surtir_material`): material, cantidad, lote y caducidad.
      - `recibir` / `rechazar`: la entrega la recibe un operador en turno, el asignado a la fase o un rol con
        `ejecutar_fase` (supervisor, jefatura); la devolución, el almacén (`surtir_material`). Quien entrega no recibe.
      - `devolver` (mismas personas que reciben): sobrante de una entrega recibida.
    Filtros: ?fase, ?material_fase, ?lote, ?tipo, ?estado. `por-surtir` lista lo pendiente de las próximas horas;
    `por-recibir`, las entregas que quien consulta puede recibir.
    """
    serializer_class = EntregaMaterialSerializer
    # Entra el usuario web o la persona con PIN; cada acción revisa `surtir_material` o si es personal de la fase
    permission_classes = [PermisoSurtido]

    def get_queryset(self):
        qs = EntregaMaterial.objects.select_related(
            'material_fase__material', 'material_fase__fase__lote', 'material_fase__fase__operacion_maestra',
        ).prefetch_related('devoluciones').order_by('-entregado_en', '-id')
        p = self.request.query_params
        filtros = {'fase': 'material_fase__fase_id', 'material_fase': 'material_fase_id', 'lote': 'material_fase__fase__lote_id',
                   'tipo': 'tipo', 'estado': 'estado'}
        for param, campo in filtros.items():
            if p.get(param):
                qs = qs.filter(**{campo: p[param]})
        return qs

    def _error(self, mensaje, estado=status.HTTP_400_BAD_REQUEST):
        return Response({"error": mensaje}, status=estado)

    def _actor(self, request):
        usuario = request.user if request.user.is_authenticated else None
        operador = None if usuario else operador_de_sesion(request)
        _, _, nombre, _ = quien(request)
        return {'usuario': usuario, 'operador': operador, 'nombre': nombre}

    def _puede_surtir(self, actor):
        return actor_tiene_permiso(actor['usuario'], actor['operador'], 'surtir_material')

    def _registrar(self, request, accion, descripcion, entrega, firmante, cambios=None, motivo=''):
        registro = registrar(request, 'MATERIAL_LOTE', accion, descripcion, objeto=entrega, fase=entrega.material_fase.fase,
                             cambios=cambios or {}, motivo=motivo or firmante['comentario'])
        firmar(registro, firmante)

    @staticmethod
    def _detalle(e):
        return f"{_cantidad(e)} de {e.material_fase.material.nombre} (lote {e.lote_material}, cad. {e.caducidad:%d/%m/%Y})"

    @action(detail=False, methods=['get'], url_path='por-surtir')
    def por_surtir(self, request):
        """?horas=48: requerimientos por surtir (o ya atrasados) y devoluciones por recibir en el almacén."""
        try:
            horas = min(max(int(request.query_params.get('horas', 48)), 1), 24 * 14)
        except ValueError:
            horas = 48
        devoluciones = self.get_queryset().filter(tipo='DEVOLUCION', estado='EN_TRANSITO')
        return Response({
            'requerimientos': RequerimientoMaterialSerializer(materiales_por_surtir(horas=horas), many=True).data,
            'devoluciones': self.get_serializer(devoluciones, many=True).data,
        })

    @action(detail=False, methods=['get'], url_path='por-recibir')
    def por_recibir(self, request):
        """Entregas pendientes de recibir en lotes abiertos que quien consulta puede recibir (pestaña de la tablet).
        `puede_recibir` indica si está en turno o tiene rol de supervisión; si no, solo ve las de sus fases asignadas."""
        actor = self._actor(request)
        qs = self.get_queryset().filter(
            tipo='ENTREGA', estado='EN_TRANSITO', material_fase__fase__estado__in=['PENDIENTE', 'EN_PROGRESO'],
            material_fase__fase__lote__estado__in=['PLANEADO', 'EN_PROGRESO'], material_fase__fase__lote__archivado=False,
        ).order_by('entregado_en', 'id')
        operador_ids = {actor['operador'].id} if actor['operador'] else set()
        general = actor_tiene_permiso(actor['usuario'], actor['operador'], 'ejecutar_fase') or (operador_ids and en_turno(operador_ids))
        if not general:
            qs = qs.filter(material_fase__fase__operadores_asignados__operador_id__in=operador_ids).distinct()
        datos = []
        for e in qs:
            fase = e.material_fase.fase
            datos.append({**self.get_serializer(e).data, 'actividad': FaseLoteViewSet._nombre_fase(fase),
                          'inicio_actividad': fase.inicio_programado, 'momento_requerido': e.material_fase.momento_requerido})
        return Response({'puede_recibir': bool(general), 'entregas': datos})

    @action(detail=False, methods=['post'], url_path='entregar')
    @transaction.atomic
    def entregar(self, request):
        actor = self._actor(request)
        if not self._puede_surtir(actor):
            return self._error("Tu rol no permite surtir materiales.", status.HTTP_403_FORBIDDEN)
        try:
            mf = MaterialFase.objects.select_related('material', 'fase__lote').get(id=request.data.get('material_fase'))
        except (MaterialFase.DoesNotExist, ValueError, TypeError):
            return self._error("El material de la fase no existe.")
        cantidad, caducidad = _decimal(request.data.get('cantidad')), _fecha(request.data.get('caducidad'))
        try:
            _validar_sin_guardar(lambda: registrar_entrega(mf, cantidad, request.data.get('lote_material'), caducidad, '', actor))
        except ErrorSurtido as e:
            return self._error(str(e))
        firmante, error = _firma_o_respuesta(request, 'ENTREGAR_MATERIAL')
        if error:
            return error
        entrega, avisos = registrar_entrega(mf, cantidad, request.data.get('lote_material'), caducidad,
                                            request.data.get('observaciones'), actor)
        self._registrar(request, 'ENTREGAR', f"Entrega de {self._detalle(entrega)} a {FaseLoteViewSet._nombre_fase(mf.fase)}",
                        entrega, firmante, cambios={'material': [None, mf.material.nombre], 'cantidad': [None, _cantidad(entrega)],
                                                    'lote_material': [None, entrega.lote_material],
                                                    'caducidad': [None, entrega.caducidad], 'estado': [None, 'EN_TRANSITO']},
                        motivo=entrega.observaciones)
        datos = self.get_serializer(entrega).data
        if avisos:
            datos['avisos'] = avisos
        return Response(datos, status=status.HTTP_201_CREATED)

    def _validar_quien_recibe(self, entrega, actor):
        if entrega.tipo == 'DEVOLUCION':
            if not self._puede_surtir(actor):
                return "La devolución la recibe el almacén (permiso para surtir materiales)."
        elif not puede_recibir_material(actor['usuario'], actor['operador'], entrega.material_fase.fase):
            return ("Recibe el material un operador en turno, el personal asignado a la fase, "
                    "un supervisor o jefatura. No tienes turno en este momento.")
        return None

    def _recepcion(self, request, accion_firma, aplicar):
        entrega = self.get_object()
        actor = self._actor(request)
        negado = self._validar_quien_recibe(entrega, actor)
        if negado:
            return self._error(negado, status.HTTP_403_FORBIDDEN)
        try:
            _validar_sin_guardar(lambda: aplicar(entrega, actor))
        except ErrorSurtido as e:
            return self._error(str(e))
        entrega.refresh_from_db()
        firmante, error = _firma_o_respuesta(request, accion_firma)
        if error:
            return error
        aplicar(entrega, actor)
        return entrega, firmante

    @action(detail=True, methods=['post'], url_path='recibir')
    @transaction.atomic
    def recibir(self, request, pk=None):
        resultado = self._recepcion(request, 'RECIBIR_MATERIAL', lambda e, a: recibir_entrega(e, a))
        if isinstance(resultado, Response):
            return resultado
        entrega, firmante = resultado
        que = 'Devolución' if entrega.tipo == 'DEVOLUCION' else 'Entrega'
        self._registrar(request, 'RECIBIR_DEVOLUCION' if entrega.tipo == 'DEVOLUCION' else 'RECIBIR',
                        f"{que} recibida: {self._detalle(entrega)} · entregó {entrega.entregado_por_nombre}",
                        entrega, firmante, cambios={'estado': ['EN_TRANSITO', 'RECIBIDA']})
        return Response(self.get_serializer(entrega).data)

    @action(detail=True, methods=['post'], url_path='rechazar')
    @transaction.atomic
    def rechazar(self, request, pk=None):
        motivo = request.data.get('motivo')
        resultado = self._recepcion(request, 'RECHAZAR_MATERIAL', lambda e, a: rechazar_entrega(e, motivo, a))
        if isinstance(resultado, Response):
            return resultado
        entrega, firmante = resultado
        que = 'Devolución' if entrega.tipo == 'DEVOLUCION' else 'Entrega'
        self._registrar(request, 'RECHAZAR', f"{que} rechazada: {self._detalle(entrega)} · entregó {entrega.entregado_por_nombre}",
                        entrega, firmante, cambios={'estado': ['EN_TRANSITO', 'RECHAZADA']}, motivo=entrega.motivo_rechazo)
        return Response(self.get_serializer(entrega).data)

    @action(detail=True, methods=['post'], url_path='devolver')
    @transaction.atomic
    def devolver(self, request, pk=None):
        entrega = self.get_object()
        actor = self._actor(request)
        if not puede_recibir_material(actor['usuario'], actor['operador'], entrega.material_fase.fase):
            return self._error("El sobrante lo devuelve un operador en turno, el personal asignado a la fase, "
                               "un supervisor o jefatura.", status.HTTP_403_FORBIDDEN)
        cantidad = _decimal(request.data.get('cantidad'))
        try:
            _validar_sin_guardar(lambda: registrar_devolucion(entrega, cantidad, '', actor))
        except ErrorSurtido as e:
            return self._error(str(e))
        firmante, error = _firma_o_respuesta(request, 'DEVOLVER_MATERIAL')
        if error:
            return error
        devolucion = registrar_devolucion(entrega, cantidad, request.data.get('observaciones'), actor)
        self._registrar(request, 'DEVOLVER', f"Devolución de {self._detalle(devolucion)} de {FaseLoteViewSet._nombre_fase(entrega.material_fase.fase)}",
                        devolucion, firmante, cambios={'cantidad': [None, _cantidad(devolucion)], 'estado': [None, 'EN_TRANSITO']},
                        motivo=devolucion.observaciones)
        return Response(self.get_serializer(devolucion).data, status=status.HTTP_201_CREATED)