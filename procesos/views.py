# procesos/views.py

from datetime import datetime, timedelta
from django.db import transaction
from django.db.models import RestrictedError
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
 
from .models import (
    ProcesoMaestro, EtapaProceso, OperacionProceso, RequerimientoPersonalFase,
    LoteProduccion, FaseLote, AsignacionFaseOperador
)
from roster.models import Operador
from .serializers import (
    ProcesoMaestroSerializer, EtapaProcesoSerializer, OperacionProcesoSerializer,
    LoteProduccionSerializer, FaseLoteSerializer, AsignacionFaseOperadorSerializer
)
from .services import CPMCalculatorService, validar_disponibilidad_personal_fase


# ==============================================================================
# 1. VIEWSETS MAESTROS (DISEÑO Y PLANIFICACIÓN)
# ==============================================================================

class ProcesoMaestroViewSet(viewsets.ModelViewSet):
    queryset = ProcesoMaestro.objects.prefetch_related('operaciones__materiales_requeridos', 'etapas').all().order_by('-created_at')
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
            nueva_op.materiales_requeridos.set(op.materiales_requeridos.all())
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
    queryset = OperacionProceso.objects.prefetch_related('materiales_requeridos').all().order_by('proceso', 'orden', 'id')
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
    def get_queryset(self):
        return LoteProduccion.objects.filter(archivado=False).exclude(estado='ABORTADO').prefetch_related('fases__operadores_asignados').order_by('-created_at')

    serializer_class = LoteProduccionSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lote = serializer.save()

        operaciones_maestras = lote.proceso_maestro.operaciones.all()
        calculadora = CPMCalculatorService(operaciones_maestras)
        resultado_cpm = calculadora.calcular_cpm()
        cpm_dict = {item['id']: item for item in resultado_cpm['operaciones_cpm']}
        
        inicio_lote = lote.fecha_inicio_planeada
        fases_a_crear = []
        
        for op in operaciones_maestras:
            cpm_info = cpm_dict.get(op.id)
            if cpm_info:
                dt_inicio = inicio_lote + timedelta(hours=cpm_info['es'])
                dt_fin = inicio_lote + timedelta(hours=cpm_info['ef'])
                fases_a_crear.append(
                    FaseLote(
                        lote=lote, operacion_maestra=op, estado='PENDIENTE',
                        fecha_base_cpm=dt_inicio.date(), hora_inicio_base_cpm=dt_inicio.time(), hora_fin_base_cpm=dt_fin.time(),
                        fecha_programada=dt_inicio.date(), hora_inicio_programada=dt_inicio.time(), hora_fin_programada=dt_fin.time()
                    )
                )
                if op.tipo_operacion == 'INCUBACION' and op.frecuencia_muestreo_horas > 0:
                    cantidad_muestreos = int(op.duracion_horas // op.frecuencia_muestreo_horas)
                    for i in range(1, cantidad_muestreos + 1):
                        dt_muestreo_inicio = dt_inicio + timedelta(hours=i * op.frecuencia_muestreo_horas)
                        dt_muestreo_fin = dt_muestreo_inicio + timedelta(hours=op.duracion_muestreo_horas)
                        tiempo_transcurrido = i * op.frecuencia_muestreo_horas
                        if tiempo_transcurrido == int(tiempo_transcurrido): tiempo_transcurrido = int(tiempo_transcurrido)
                        nombre_dinamico = f"M-{tiempo_transcurrido}h - {op.nombre}"
                        
                        fases_a_crear.append(
                            FaseLote(
                                lote=lote, operacion_maestra=op, estado='PENDIENTE',
                                es_subtarea_muestreo=True, indice_muestreo=i, nombre_tarea_dinamica=nombre_dinamico,
                                fecha_base_cpm=dt_muestreo_inicio.date(), hora_inicio_base_cpm=dt_muestreo_inicio.time(), hora_fin_base_cpm=dt_muestreo_fin.time(),
                                fecha_programada=dt_muestreo_inicio.date(), hora_inicio_programada=dt_muestreo_inicio.time(), hora_fin_programada=dt_muestreo_fin.time()
                            )
                        )
            else:
                fases_a_crear.append(FaseLote(lote=lote, operacion_maestra=op, estado='PENDIENTE'))

        FaseLote.objects.bulk_create(fases_a_crear)
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


class FaseLoteViewSet(viewsets.ModelViewSet):
    serializer_class = FaseLoteSerializer

    def get_queryset(self):
        return FaseLote.objects.select_related('operacion_maestra', 'lote').filter(lote__archivado=False).exclude(lote__estado='ABORTADO').order_by('operacion_maestra__identificador_paso', 'indice_muestreo')

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

        # =====================================================================
        # STRICT CPM SNAPPING (Enganche Estricto por Hora Final)
        # =====================================================================
        fases_actualizadas_count = 0
        if ejecutar_auto_ajuste:
            todas_fases_lote = list(fase.lote.fases.all().select_related('operacion_maestra'))
            fases_a_actualizar = []
            fases_procesadas = {fase.id}
            cola_propagacion = [fase]

            while cola_propagacion:
                fase_actual = cola_propagacion.pop(0)
                
                # 1. Extraer hora de inicio y fin EXACTA de la fase predecesora (fase_actual)
                if fase_actual.estado == 'COMPLETADA' and fase_actual.fecha_fin_real:
                    tz = timezone.get_current_timezone()
                    dt_actual_fin = timezone.make_naive(fase_actual.fecha_fin_real, tz)
                    dt_actual_inicio = timezone.make_naive(fase_actual.fecha_inicio_real, tz) if fase_actual.fecha_inicio_real else dt_actual_fin
                else:
                    dt_actual_inicio = datetime.combine(fase_actual.fecha_programada, fase_actual.hora_inicio_programada)
                    dt_actual_fin = datetime.combine(fase_actual.fecha_programada, fase_actual.hora_fin_programada)
                    # Corrección si la tarea cruzó la medianoche
                    if dt_actual_fin < dt_actual_inicio:
                        dt_actual_fin += timedelta(days=1)
                
                # 2. Iterar sobre los hijos directos y engancharlos matemáticamente
                for f in todas_fases_lote:
                    if not f.es_subtarea_muestreo and f.operacion_maestra.predecesora_id == fase_actual.operacion_maestra_id:
                        if f.id not in fases_procesadas and f.estado == 'PENDIENTE':
                            tipo_dep = f.operacion_maestra.tipo_dependencia or 'FS'
                            desfase = timedelta(hours=f.operacion_maestra.desfase_horas or 0.0)
                            
                            # AQUÍ ESTÁ LA MAGIA DEL SNAPPING (Adiós traslapes)
                            if tipo_dep in ['SS', 'OFFSET']:
                                dt_f_nuevo_inicio = dt_actual_inicio + desfase
                            else: # Finish to Start (FS)
                                dt_f_nuevo_inicio = dt_actual_fin + desfase
                                
                            dt_f_nuevo_fin = dt_f_nuevo_inicio + timedelta(hours=f.operacion_maestra.duracion_horas)
                            
                            f.fecha_programada = dt_f_nuevo_inicio.date()
                            f.hora_inicio_programada = dt_f_nuevo_inicio.time()
                            f.hora_fin_programada = dt_f_nuevo_fin.time()
                            f.motivo_reprogramacion = 'PRODUCCION'
                            f.notas_reprogramacion = f"(Auto-Ajuste) Enganche automático con el término real de [{fase_actual.operacion_maestra.identificador_paso}]."
                            
                            fases_a_actualizar.append(f)
                            fases_procesadas.add(f.id)
                            cola_propagacion.append(f)
                
                # 3. Propagación para Muestreos
                if not fase_actual.es_subtarea_muestreo:
                    muestreos_hijos = [f for f in todas_fases_lote if f.es_subtarea_muestreo and f.operacion_maestra_id == fase_actual.operacion_maestra_id]
                    for m in muestreos_hijos:
                        if m.id not in fases_procesadas and m.estado == 'PENDIENTE':
                            horas_desfase_muestreo = m.indice_muestreo * m.operacion_maestra.frecuencia_muestreo_horas
                            dt_m_nuevo_inicio = dt_actual_inicio + timedelta(hours=horas_desfase_muestreo)
                            dt_m_nuevo_fin = dt_m_nuevo_inicio + timedelta(hours=m.operacion_maestra.duracion_muestreo_horas)
                            
                            m.fecha_programada = dt_m_nuevo_inicio.date()
                            m.hora_inicio_programada = dt_m_nuevo_inicio.time()
                            m.hora_fin_programada = dt_m_nuevo_fin.time()
                            m.motivo_reprogramacion = 'PRODUCCION'
                            m.notas_reprogramacion = f"(Auto-Ajuste) Muestreo alineado con el inicio real de [{fase_actual.operacion_maestra.identificador_paso}]."
                            
                            fases_a_actualizar.append(m)
                            fases_procesadas.add(m.id)

            if fases_a_actualizar:
                FaseLote.objects.bulk_update(
                    fases_a_actualizar, 
                    ['fecha_programada', 'hora_inicio_programada', 'hora_fin_programada', 'motivo_reprogramacion', 'notas_reprogramacion']
                )
                fases_actualizadas_count = len(fases_a_actualizar)

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

        dt_nuevo_inicio = datetime.combine(nueva_fecha, nueva_hora)

        # =====================================================================
        # ESCUDO GxP: PREVENCIÓN DE PARADOJAS TEMPORALES (Corregido Midnight Bug)
        # =====================================================================
        if not fase_origen.es_subtarea_muestreo:
            predecesora_maestra = fase_origen.operacion_maestra.predecesora
            if predecesora_maestra:
                try:
                    fase_pred = FaseLote.objects.get(lote=fase_origen.lote, operacion_maestra=predecesora_maestra, es_subtarea_muestreo=False)
                    if fase_pred.fecha_programada and fase_pred.hora_inicio_programada and fase_pred.hora_fin_programada:
                        dt_pred_inicio = datetime.combine(fase_pred.fecha_programada, fase_pred.hora_inicio_programada)
                        dt_pred_fin = datetime.combine(fase_pred.fecha_programada, fase_pred.hora_fin_programada)
                        if dt_pred_fin < dt_pred_inicio:
                            dt_pred_fin += timedelta(days=1) # Corrección Midnight Bug
                        
                        tipo_dep = fase_origen.operacion_maestra.tipo_dependencia or 'FS'
                        desfase = timedelta(hours=fase_origen.operacion_maestra.desfase_horas or 0.0)
                        
                        if tipo_dep in ['SS', 'OFFSET']:
                            limite_inferior = dt_pred_inicio + desfase
                            mensaje_regla = f"Inicio a Inicio (SS) con la fase [{predecesora_maestra.identificador_paso}]"
                        else:
                            limite_inferior = dt_pred_fin + desfase
                            mensaje_regla = f"Fin a Inicio (FS) tras la fase [{predecesora_maestra.identificador_paso}]"
                        
                        if dt_nuevo_inicio < limite_inferior:
                            return Response({
                                "error": f"Violación GxP (Colisión Lógica): La tarea no puede iniciar a las {dt_nuevo_inicio.strftime('%Y-%m-%d %H:%M')}. "
                                         f"Por regla de dependencia {mensaje_regla}, lo más temprano que puede iniciar es a las {limite_inferior.strftime('%Y-%m-%d %H:%M')}."
                            }, status=status.HTTP_400_BAD_REQUEST)
                except FaseLote.DoesNotExist:
                    pass

        duracion_operacion = fase_origen.operacion_maestra.duracion_muestreo_horas if fase_origen.es_subtarea_muestreo else fase_origen.operacion_maestra.duracion_horas
        dt_nuevo_fin = dt_nuevo_inicio + timedelta(hours=duracion_operacion)

        fase_origen.fecha_programada = dt_nuevo_inicio.date()
        fase_origen.hora_inicio_programada = dt_nuevo_inicio.time()
        fase_origen.hora_fin_programada = dt_nuevo_fin.time()
        fase_origen.motivo_reprogramacion = motivo
        fase_origen.notas_reprogramacion = notas
        fase_origen.save()

        # =====================================================================
        # STRICT CPM SNAPPING (Propagación manual hacia adelante)
        # =====================================================================
        fases_actualizadas = 1
        todas_fases_lote = list(fase_origen.lote.fases.all().select_related('operacion_maestra'))
        fases_a_actualizar = []
        fases_procesadas = {fase_origen.id}
        cola_propagacion = [fase_origen]

        while cola_propagacion:
            fase_actual = cola_propagacion.pop(0)
            
            dt_actual_inicio = datetime.combine(fase_actual.fecha_programada, fase_actual.hora_inicio_programada)
            dt_actual_fin = datetime.combine(fase_actual.fecha_programada, fase_actual.hora_fin_programada)
            if dt_actual_fin < dt_actual_inicio:
                dt_actual_fin += timedelta(days=1)
            
            for f in todas_fases_lote:
                if not f.es_subtarea_muestreo and f.operacion_maestra.predecesora_id == fase_actual.operacion_maestra_id:
                    if f.id not in fases_procesadas and f.estado == 'PENDIENTE':
                        tipo_dep = f.operacion_maestra.tipo_dependencia or 'FS'
                        desfase = timedelta(hours=f.operacion_maestra.desfase_horas or 0.0)
                        
                        if tipo_dep in ['SS', 'OFFSET']:
                            dt_f_nuevo_inicio = dt_actual_inicio + desfase
                        else:
                            dt_f_nuevo_inicio = dt_actual_fin + desfase
                            
                        dt_f_nuevo_fin = dt_f_nuevo_inicio + timedelta(hours=f.operacion_maestra.duracion_horas)
                        
                        f.fecha_programada = dt_f_nuevo_inicio.date()
                        f.hora_inicio_programada = dt_f_nuevo_inicio.time()
                        f.hora_fin_programada = dt_f_nuevo_fin.time()
                        f.motivo_reprogramacion = 'PRODUCCION'
                        f.notas_reprogramacion = f"(Auto-Ajuste) Re-alineación automática originada por el supervisor en [{fase_origen.operacion_maestra.identificador_paso}]."
                        
                        fases_a_actualizar.append(f)
                        fases_procesadas.add(f.id)
                        cola_propagacion.append(f)
            
            if not fase_actual.es_subtarea_muestreo:
                muestreos_hijos = [f for f in todas_fases_lote if f.es_subtarea_muestreo and f.operacion_maestra_id == fase_actual.operacion_maestra_id]
                for m in muestreos_hijos:
                    if m.id not in fases_procesadas and m.estado == 'PENDIENTE':
                        horas_desfase_muestreo = m.indice_muestreo * m.operacion_maestra.frecuencia_muestreo_horas
                        dt_m_nuevo_inicio = dt_actual_inicio + timedelta(hours=horas_desfase_muestreo)
                        dt_m_nuevo_fin = dt_m_nuevo_inicio + timedelta(hours=m.operacion_maestra.duracion_muestreo_horas)
                        
                        m.fecha_programada = dt_m_nuevo_inicio.date()
                        m.hora_inicio_programada = dt_m_nuevo_inicio.time()
                        m.hora_fin_programada = dt_m_nuevo_fin.time()
                        m.motivo_reprogramacion = 'PRODUCCION'
                        m.notas_reprogramacion = f"(Auto-Ajuste) Muestreo alineado solidariamente."
                        
                        fases_a_actualizar.append(m)
                        fases_procesadas.add(m.id)
        
        if fases_a_actualizar:
            FaseLote.objects.bulk_update(
                fases_a_actualizar, 
                ['fecha_programada', 'hora_inicio_programada', 'hora_fin_programada', 'motivo_reprogramacion', 'notas_reprogramacion']
            )
            fases_actualizadas += len(fases_a_actualizar)

        return Response({
            "mensaje": f"Ajuste completado. El sistema auto-alineó estrictamente {fases_actualizadas - 1} tareas sucesoras evitando cualquier traslape (Snapping).",
            "fase": self.get_serializer(fase_origen).data
        }, status=status.HTTP_200_OK)


class AsignacionFaseOperadorViewSet(viewsets.ModelViewSet):
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

        if fase_actual.fecha_programada and fase_actual.hora_inicio_programada and fase_actual.hora_fin_programada:
            asignaciones_existentes = AsignacionFaseOperador.objects.filter(
                operador_id=operador_id, fase_lote__fecha_programada=fase_actual.fecha_programada
            ).exclude(fase_lote=fase_actual).select_related('fase_lote')

            ini_nueva = fase_actual.hora_inicio_programada
            fin_nueva = fase_actual.hora_fin_programada

            for asig in asignaciones_existentes:
                fase_existente = asig.fase_lote
                ini_ex = fase_existente.hora_inicio_programada
                fin_ex = fase_existente.hora_fin_programada

                if ini_ex and fin_ex:
                    if ini_nueva < fin_ex and fin_nueva > ini_ex:
                        nombre_tarea = fase_existente.nombre_tarea_dinamica if fase_existente.es_subtarea_muestreo else fase_existente.operacion_maestra.nombre
                        return Response({"error": f"Conflicto de turnos GxP: El operador ya está asignado a [{fase_existente.operacion_maestra.identificador_paso}] {nombre_tarea} de {ini_ex.strftime('%H:%M')} a {fin_ex.strftime('%H:%M')}."}, status=status.HTTP_400_BAD_REQUEST)

        return super().create(request, *args, **kwargs)


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
        ).order_by('fase_lote__fecha_programada', 'fase_lote__hora_inicio_programada')
        
        tareas_data = []
        for asig in asignaciones:
            fase = asig.fase_lote
            tareas_data.append({
                "fase_id": fase.id, "lote_identificador": fase.lote.identificador_lote, "proceso_nombre": fase.lote.proceso_maestro.nombre,
                "tarea_nombre": fase.nombre_tarea_dinamica if fase.es_subtarea_muestreo else fase.operacion_maestra.nombre,
                "identificador_paso": fase.operacion_maestra.identificador_paso, "tipo_operacion": fase.operacion_maestra.tipo_operacion,
                "estado": fase.estado, "fecha_programada": fase.fecha_programada, "hora_inicio_programada": fase.hora_inicio_programada,
                "hora_fin_programada": fase.hora_fin_programada, "rol_asignado": asig.rol_ejercido.nombre
            })
            
        return Response({"tareas_pendientes": tareas_data}, status=status.HTTP_200_OK)