# procesos/views.py

from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import RestrictedError
from django.utils import timezone
from rest_framework import mixins, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
 
from .models import (
    ProcesoMaestro, EtapaProceso, OperacionProceso, RequerimientoPersonalFase,
    LoteProduccion, FaseLote, AsignacionFaseOperador, MaterialOperacion, MaterialFase
)
from actividades.models import MaterialInsumo
from roster.models import Operador
from .serializers import (
    ProcesoMaestroSerializer, EtapaProcesoSerializer, OperacionProcesoSerializer,
    LoteProduccionSerializer, FaseLoteSerializer, AsignacionFaseOperadorSerializer,
    MaterialFaseSerializer, RequerimientoMaterialSerializer
)
from .services import (
    CPMCalculatorService, validar_disponibilidad_personal_fase, construir_fases_lote,
    validar_inicio_contra_predecesora, propagar_programacion, buscar_conflicto_operador,
    generar_materiales_lote, ajustar_material_fase, agregar_material_fase, retirar_material_fase,
    requerimientos_materiales, ErrorMaterialFase
)


# ==============================================================================
# 1. VIEWSETS MAESTROS (DISEÑO Y PLANIFICACIÓN)
# ==============================================================================

class ProcesoMaestroViewSet(viewsets.ModelViewSet):
    queryset = ProcesoMaestro.objects.prefetch_related('operaciones__materiales__material', 'operaciones__requerimientos_rol__rol', 'etapas').all().order_by('-created_at')
    serializer_class = ProcesoMaestroSerializer

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
                personal_requerido=op.personal_requerido,
                tipo_equipo_requerido=op.tipo_equipo_requerido
            )
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

        return Response({"mensaje": f"Plantilla clonada exitosamente como '{nuevo_nombre}'.", "nuevo_id": nuevo_proceso.id}, status=status.HTTP_201_CREATED)


class EtapaProcesoViewSet(viewsets.ModelViewSet):
    queryset = EtapaProceso.objects.all().order_by('proceso', 'orden')
    serializer_class = EtapaProcesoSerializer


class OperacionProcesoViewSet(viewsets.ModelViewSet):
    queryset = OperacionProceso.objects.prefetch_related('materiales__material').all().order_by('proceso', 'orden', 'id')
    serializer_class = OperacionProcesoSerializer

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
        for index, op_id in enumerate(ids_ordenados):
            try:
                operacion = OperacionProceso.objects.get(id=op_id)
                operacion.orden = index + 1
                operacion.save(update_fields=['orden'])
            except OperacionProceso.DoesNotExist:
                return Response({"error": f"La operación con ID {op_id} no existe."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"mensaje": "Secuencia de operaciones actualizada correctamente."}, status=status.HTTP_200_OK)


# ==============================================================================
# 2. VIEWSETS TRANSACCIONALES (EJECUCIÓN DE LOTES Y REGLAS GxP)
# ==============================================================================

class LoteProduccionViewSet(viewsets.ModelViewSet):
    # Un lote instanciado no se edita: sus cambios pasan por abortar/archivar y por las acciones de sus fases
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        return LoteProduccion.objects.filter(archivado=False).exclude(estado='ABORTADO').prefetch_related('fases__operadores_asignados', 'fases__materiales__material').order_by('-created_at')

    serializer_class = LoteProduccionSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lote = serializer.save()
        FaseLote.objects.bulk_create(construir_fases_lote(lote))
        generar_materiales_lote(lote)
        headers = self.get_success_headers(serializer.data)
        response_serializer = self.get_serializer(lote)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def destroy(self, request, *args, **kwargs):
        lote = self.get_object()
        if lote.estado != 'PLANEADO':
            return Response({"error": f"Violación GxP (Data Integrity): No se puede eliminar el Lote '{lote.identificador_lote}' porque su estado actual es '{lote.estado}'."}, status=status.HTTP_403_FORBIDDEN)
        self.perform_destroy(lote)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='archivar')
    def archivar(self, request, pk=None):
        lote = self.get_object()
        if lote.estado != 'COMPLETADO': return Response({"error": "Solo se pueden archivar lotes COMPLETADOS."}, status=status.HTTP_400_BAD_REQUEST)
        lote.archivado = True
        lote.save()
        return Response({"mensaje": f"El lote {lote.identificador_lote} ha sido archivado."}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='abortar')
    @transaction.atomic
    def abortar(self, request, pk=None):
        lote = self.get_object()
        if lote.estado in ['COMPLETADO', 'ABORTADO']: return Response({"error": f"No es posible abortar un lote en estado: {lote.estado}."}, status=status.HTTP_400_BAD_REQUEST)
        motivo = request.data.get('motivo_aborto')
        if not motivo or len(motivo.strip()) < 10: return Response({"error": "Debe proporcionar un motivo detallado (mínimo 10 caracteres)."}, status=status.HTTP_400_BAD_REQUEST)
        lote.estado = 'ABORTADO'
        lote.motivo_aborto = motivo
        lote.save()
        tiempo_actual = timezone.now()
        fases_activas = lote.fases.exclude(estado__in=['COMPLETADA', 'OMITIDA'])
        for fase in fases_activas:
            if fase.estado == 'EN_PROGRESO': fase.fecha_fin_real = tiempo_actual
            fase.estado = 'OMITIDA'
            fase.save()
        return Response({"mensaje": f"El lote {lote.identificador_lote} ha sido abortado."}, status=status.HTTP_200_OK)


class FaseLoteViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """
    Las fases se crean al instanciar el lote y no se borran. Por PATCH solo se editan equipos
    (el serializer marca el resto como solo lectura); estado y horarios cambian únicamente vía
    `cambiar-estado` y `reprogramar`, que aplican las reglas GxP.
    """
    serializer_class = FaseLoteSerializer

    def get_queryset(self):
        return FaseLote.objects.select_related('operacion_maestra', 'lote').prefetch_related('materiales__material').filter(lote__archivado=False).exclude(lote__estado='ABORTADO').order_by('operacion_maestra__identificador_paso', 'indice_muestreo')

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

        tiempo_actual = timezone.now()
        ejecutar_auto_ajuste = False

        if nuevo_estado == 'EN_PROGRESO' and fase.estado == 'PENDIENTE':
            fase.fecha_inicio_real = tiempo_actual
        elif nuevo_estado == 'COMPLETADA' and fase.estado == 'EN_PROGRESO':
            fase.fecha_fin_real = tiempo_actual
            # Siempre intentaremos re-alinear las tareas siguientes al final REAL de esta tarea
            ejecutar_auto_ajuste = True

        fase.estado = nuevo_estado
        fase.save()

        # Enganche estricto de las sucesoras al término real de esta fase
        fases_actualizadas_count = 0
        if ejecutar_auto_ajuste:
            fases_actualizadas_count = propagar_programacion(
                fase,
                nota_tarea="(Auto-Ajuste) Enganche automático con el término real de [{paso}].",
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

        response_data = self.get_serializer(fase).data
        if ejecutar_auto_ajuste and fases_actualizadas_count > 0:
            response_data['mensaje_cascada'] = f"Se auto-ajustaron {fases_actualizadas_count} tareas posteriores."

        return Response(response_data, status=status.HTTP_200_OK)

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

        return Response({
            "mensaje": f"Ajuste completado. El sistema auto-alineó estrictamente {fases_actualizadas - 1} tareas sucesoras evitando cualquier traslape (Snapping).",
            "fase": self.get_serializer(fase_origen).data
        }, status=status.HTTP_200_OK)


class AsignacionFaseOperadorViewSet(viewsets.ModelViewSet):
    # Sin PUT/PATCH: cambiar una asignación saltaría la validación de cruces; se elimina y se crea de nuevo
    http_method_names = ['get', 'post', 'delete', 'head', 'options']
    queryset = AsignacionFaseOperador.objects.select_related('operador', 'rol_ejercido').all()
    serializer_class = AsignacionFaseOperadorSerializer

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

    def get_queryset(self):
        qs = MaterialFase.objects.select_related('material', 'fase').order_by('fase', 'material__nombre')
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
        return Response(self.get_serializer(mf).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='ajustar')
    @transaction.atomic
    def ajustar(self, request, pk=None):
        mf = self.get_object()
        try:
            ajustar_material_fase(
                mf, _decimal(request.data.get('cantidad')),
                _horas(request.data.get('anticipacion_horas')), request.data.get('motivo'),
            )
        except ErrorMaterialFase as e:
            return self._error(str(e))
        return Response(self.get_serializer(mf).data)

    @action(detail=True, methods=['post'], url_path='retirar')
    @transaction.atomic
    def retirar(self, request, pk=None):
        mf = self.get_object()
        try:
            retirar_material_fase(mf, request.data.get('motivo'))
        except ErrorMaterialFase as e:
            return self._error(str(e))
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


# ==============================================================================
# 3. VIEWSET MOBILE eBR (EJECUCIÓN EN PISO DE PLANTA)
# ==============================================================================

class MobileeBRViewSet(viewsets.ViewSet):
    @action(detail=False, methods=['post'], url_path='login')
    def login(self, request):
        codigo = request.data.get('codigo_empleado')
        pin = request.data.get('pin_acceso')
        
        if not codigo or not pin: return Response({"error": "Debe ingresar el Número de Empleado y su PIN."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            operador = Operador.objects.get(codigo_empleado=codigo, activo=True)
        except Operador.DoesNotExist:
            return Response({"error": "Credenciales inválidas o usuario inactivo."}, status=status.HTTP_401_UNAUTHORIZED)
            
        if operador.pin_acceso != str(pin): return Response({"error": "Credenciales inválidas."}, status=status.HTTP_401_UNAUTHORIZED)
            
        return Response({
            "operador_id": operador.id, "codigo_empleado": operador.codigo_empleado, "nombre": operador.nombre,
            "rol": operador.rol.nombre if operador.rol else "Operativo Base", "cuadrilla": operador.cuadrilla.nombre
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='tareas-pendientes')
    def tareas_pendientes(self, request, pk=None):
        try:
            operador = Operador.objects.get(id=pk, activo=True)
        except Operador.DoesNotExist:
            return Response({"error": "Operador no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        
        asignaciones = AsignacionFaseOperador.objects.filter(
            operador=operador, fase_lote__lote__archivado=False, fase_lote__lote__estado__in=['PLANEADO', 'EN_PROGRESO']
        ).exclude(fase_lote__estado__in=['COMPLETADA', 'OMITIDA']).select_related(
            'fase_lote', 'fase_lote__lote', 'fase_lote__operacion_maestra', 'fase_lote__lote__proceso_maestro'
        ).order_by('fase_lote__inicio_programado')
        
        tareas_data = []
        for asig in asignaciones:
            fase = asig.fase_lote
            tareas_data.append({
                "fase_id": fase.id, "lote_identificador": fase.lote.identificador_lote, "proceso_nombre": fase.lote.proceso_maestro.nombre,
                "tarea_nombre": fase.nombre_tarea_dinamica if fase.es_subtarea_muestreo else fase.operacion_maestra.nombre,
                "identificador_paso": fase.operacion_maestra.identificador_paso, "tipo_operacion": fase.operacion_maestra.tipo_operacion,
                "estado": fase.estado, "inicio_programado": fase.inicio_programado, "fin_programado": fase.fin_programado,
                "rol_asignado": asig.rol_ejercido.nombre
            })
            
        return Response({"tareas_pendientes": tareas_data}, status=status.HTTP_200_OK)