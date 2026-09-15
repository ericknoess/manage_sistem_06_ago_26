# procesos/views.py

from datetime import datetime, timedelta
from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
 
from .models import (
    ProcesoMaestro, EtapaProceso, OperacionProceso,
    LoteProduccion, FaseLote, AsignacionFaseOperador
)
from .serializers import (
    ProcesoMaestroSerializer, EtapaProcesoSerializer, OperacionProcesoSerializer,
    LoteProduccionSerializer, FaseLoteSerializer, AsignacionFaseOperadorSerializer
)
from .services import CPMCalculatorService, validar_disponibilidad_personal_fase


# ==============================================================================
# 1. VIEWSETS MAESTROS (DISEÑO Y PLANIFICACIÓN)
# ==============================================================================

class ProcesoMaestroViewSet(viewsets.ModelViewSet):
    """
    API endpoint para gestionar las recetas maestras de bioprocesos (CPM).
    """
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


class EtapaProcesoViewSet(viewsets.ModelViewSet):
    """
    API endpoint para gestionar las Etapas lógicas (Agrupadores ISA-88) de un Proceso Maestro.
    """
    queryset = EtapaProceso.objects.all().order_by('proceso', 'orden')
    serializer_class = EtapaProcesoSerializer


class OperacionProcesoViewSet(viewsets.ModelViewSet):
    """
    API endpoint para gestionar las fases individuales de los procesos maestros.
    """
    queryset = OperacionProceso.objects.prefetch_related('materiales_requeridos').all().order_by('proceso', 'identificador_paso')
    serializer_class = OperacionProcesoSerializer

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


# ==============================================================================
# 2. VIEWSETS TRANSACCIONALES (EJECUCIÓN DE LOTES Y REGLAS GxP)
# ==============================================================================

class LoteProduccionViewSet(viewsets.ModelViewSet):
    """
    API endpoint para la gestión de Lotes Reales (eBR).
    Incluye algoritmo Forward Scheduling para programación de tareas MES y generación de muestreos cíclicos.
    """
    queryset = LoteProduccion.objects.prefetch_related('fases__operadores_asignados').all().order_by('-created_at')
    serializer_class = LoteProduccionSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lote = serializer.save()

        operaciones_maestras = lote.proceso_maestro.operaciones.all()
        
        # --- FORWARD SCHEDULING (Cálculo de Ruta Crítica base) ---
        calculadora = CPMCalculatorService(operaciones_maestras)
        resultado_cpm = calculadora.calcular_cpm()
        cpm_dict = {item['id']: item for item in resultado_cpm['operaciones_cpm']}
        
        inicio_lote = lote.fecha_inicio_planeada
        fases_a_crear = []
        
        for op in operaciones_maestras:
            cpm_info = cpm_dict.get(op.id)
            
            if cpm_info:
                # 1. Proyectar tiempos de la Tarea Principal (Padre)
                dt_inicio = inicio_lote + timedelta(hours=cpm_info['es'])
                dt_fin = inicio_lote + timedelta(hours=cpm_info['ef'])
                
                # Crear la Fase Principal guardando Linea Base y Forecast
                fases_a_crear.append(
                    FaseLote(
                        lote=lote, 
                        operacion_maestra=op, 
                        estado='PENDIENTE',
                        # --- BASELINE (INMUTABLE) ---
                        fecha_base_cpm=dt_inicio.date(),
                        hora_inicio_base_cpm=dt_inicio.time(),
                        hora_fin_base_cpm=dt_fin.time(),
                        # --- FORECAST (PROGRAMABLE) ---
                        fecha_programada=dt_inicio.date(),
                        hora_inicio_programada=dt_inicio.time(),
                        hora_fin_programada=dt_fin.time()
                    )
                )
                
                # 2. ALGORITMO DE GENERACIÓN DE MUESTREOS CÍCLICOS
                if op.tipo_operacion == 'INCUBACION' and op.frecuencia_muestreo_horas > 0:
                    cantidad_muestreos = int(op.duracion_horas // op.frecuencia_muestreo_horas)
                    
                    for i in range(1, cantidad_muestreos + 1):
                        dt_muestreo_inicio = dt_inicio + timedelta(hours=i * op.frecuencia_muestreo_horas)
                        dt_muestreo_fin = dt_muestreo_inicio + timedelta(hours=op.duracion_muestreo_horas)
                        
                        tiempo_transcurrido = i * op.frecuencia_muestreo_horas
                        if tiempo_transcurrido == int(tiempo_transcurrido):
                            tiempo_transcurrido = int(tiempo_transcurrido)
                        
                        nombre_dinamico = f"M-{tiempo_transcurrido}h - {op.nombre}"
                        
                        fases_a_crear.append(
                            FaseLote(
                                lote=lote, 
                                operacion_maestra=op, 
                                estado='PENDIENTE',
                                es_subtarea_muestreo=True,
                                indice_muestreo=i,
                                nombre_tarea_dinamica=nombre_dinamico,
                                # --- BASELINE (INMUTABLE) ---
                                fecha_base_cpm=dt_muestreo_inicio.date(),
                                hora_inicio_base_cpm=dt_muestreo_inicio.time(),
                                hora_fin_base_cpm=dt_muestreo_fin.time(),
                                # --- FORECAST (PROGRAMABLE) ---
                                fecha_programada=dt_muestreo_inicio.date(),
                                hora_inicio_programada=dt_muestreo_inicio.time(),
                                hora_fin_programada=dt_muestreo_fin.time()
                            )
                        )
            else:
                fases_a_crear.append(FaseLote(lote=lote, operacion_maestra=op, estado='PENDIENTE'))

        FaseLote.objects.bulk_create(fases_a_crear)

        headers = self.get_success_headers(serializer.data)
        response_serializer = self.get_serializer(lote)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class FaseLoteViewSet(viewsets.ModelViewSet):
    """
    API endpoint para gestionar el progreso y tiempos reales de las fases instanciadas.
    """
    queryset = FaseLote.objects.select_related('operacion_maestra').all().order_by('operacion_maestra__identificador_paso', 'indice_muestreo')
    serializer_class = FaseLoteSerializer

    @action(detail=True, methods=['post'], url_path='cambiar-estado')
    @transaction.atomic
    def cambiar_estado(self, request, pk=None):
        fase = self.get_object()
        
        if fase.lote.estado == 'COMPLETADO':
            return Response({
                "error": "Violación GxP (Data Lock): El Lote de Producción ya está cerrado y liberado. Sus registros son estrictamente inmutables."
            }, status=status.HTTP_403_FORBIDDEN)

        nuevo_estado = request.data.get('estado')

        estados_validos = dict(FaseLote.ESTADO_FASE_CHOICES).keys()
        if nuevo_estado not in estados_validos:
            return Response({"error": "Estado GxP no válido."}, status=status.HTTP_400_BAD_REQUEST)

        if nuevo_estado == 'COMPLETADA' and not fase.operadores_asignados.exists():
            if fase.operacion_maestra.tipo_operacion == 'ACTIVA' or fase.es_subtarea_muestreo:
                return Response({
                    "error": "Violación GxP: No se puede completar una tarea operativa o de muestreo sin haber asignado al menos a un operador responsable."
                }, status=status.HTTP_400_BAD_REQUEST)

        tiempo_actual = timezone.now()
        
        if nuevo_estado == 'EN_PROGRESO' and fase.estado == 'PENDIENTE':
            fase.fecha_inicio_real = tiempo_actual
        elif nuevo_estado == 'COMPLETADA' and fase.estado == 'EN_PROGRESO':
            fase.fecha_fin_real = tiempo_actual
            
        fase.estado = nuevo_estado
        fase.save()

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

        serializer = self.get_serializer(fase)
        return Response(serializer.data, status=status.HTTP_200_OK)

    # --- [NUEVO] ENDPOINT PARA REPROGRAMACIÓN Y AUDITORÍA GXP ---
    @action(detail=True, methods=['post'], url_path='reprogramar')
    @transaction.atomic
    def reprogramar(self, request, pk=None):
        fase = self.get_object()
        
        if fase.lote.estado == 'COMPLETADO':
            return Response({
                "error": "Violación GxP (Data Lock): El Lote está cerrado, no se admiten ajustes de agenda."
            }, status=status.HTTP_403_FORBIDDEN)

        nueva_fecha_str = request.data.get('fecha_programada')
        nueva_hora_str = request.data.get('hora_inicio_programada')
        motivo = request.data.get('motivo_reprogramacion')
        notas = request.data.get('notas_reprogramacion', '')

        if not all([nueva_fecha_str, nueva_hora_str, motivo]):
            return Response({
                "error": "Los campos 'fecha_programada', 'hora_inicio_programada' y 'motivo_reprogramacion' son obligatorios."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validación de formato GxP
        motivos_validos = dict(FaseLote.MOTIVO_REPROGRAMACION_CHOICES).keys()
        if motivo not in motivos_validos:
            return Response({"error": "El motivo de reprogramación no es válido o no está estandarizado."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            nueva_fecha = datetime.strptime(nueva_fecha_str, '%Y-%m-%d').date()
            nueva_hora = datetime.strptime(nueva_hora_str, '%H:%M').time()
        except ValueError:
            return Response({"error": "Formato de fecha u hora inválido."}, status=status.HTTP_400_BAD_REQUEST)

        # Recálculo matemático de la hora de finalización (Forecast)
        dt_inicio_forecast = datetime.combine(nueva_fecha, nueva_hora)
        
        # Tomar la duración correcta (si es muestreo o fase normal)
        duracion_operacion = fase.operacion_maestra.duracion_muestreo_horas if fase.es_subtarea_muestreo else fase.operacion_maestra.duracion_horas
        
        dt_fin_forecast = dt_inicio_forecast + timedelta(hours=duracion_operacion)

        # Guardado en el modelo
        fase.fecha_programada = dt_inicio_forecast.date()
        fase.hora_inicio_programada = dt_inicio_forecast.time()
        fase.hora_fin_programada = dt_fin_forecast.time()
        fase.motivo_reprogramacion = motivo
        fase.notas_reprogramacion = notas
        fase.save()

        return Response(self.get_serializer(fase).data, status=status.HTTP_200_OK)


class AsignacionFaseOperadorViewSet(viewsets.ModelViewSet):
    """
    API endpoint para auditar y registrar a los operadores en tareas específicas GxP.
    Incluye validación estricta contra solapamiento de horarios (Time Overlap Prevention).
    """
    queryset = AsignacionFaseOperador.objects.select_related('operador', 'rol_ejercido').all()
    serializer_class = AsignacionFaseOperadorSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        fase_id = request.data.get('fase_lote')
        operador_id = request.data.get('operador')
        
        try:
            fase_actual = FaseLote.objects.get(id=fase_id)
        except FaseLote.DoesNotExist:
            return Response({"error": "La fase especificada no existe."}, status=status.HTTP_404_NOT_FOUND)

        if fase_actual.lote.estado == 'COMPLETADO':
            return Response({
                "error": "Violación GxP (Data Lock): No se puede asignar personal a un Lote de Producción cerrado."
            }, status=status.HTTP_403_FORBIDDEN)

        if fase_actual.estado in ['COMPLETADA', 'OMITIDA']:
            return Response({
                "error": f"Violación GxP: No se puede modificar el personal de una fase que ya se encuentra {fase_actual.estado}."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validación de solapamiento
        if fase_actual.fecha_programada and fase_actual.hora_inicio_programada and fase_actual.hora_fin_programada:
            asignaciones_existentes = AsignacionFaseOperador.objects.filter(
                operador_id=operador_id,
                fase_lote__fecha_programada=fase_actual.fecha_programada
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
                        return Response({
                            "error": f"⚠️ Conflicto de turnos GxP: El operador ya está asignado a la tarea [{fase_existente.operacion_maestra.identificador_paso}] {nombre_tarea} en el horario de {ini_ex.strftime('%H:%M')} a {fin_ex.strftime('%H:%M')}."
                        }, status=status.HTTP_400_BAD_REQUEST)

        return super().create(request, *args, **kwargs)