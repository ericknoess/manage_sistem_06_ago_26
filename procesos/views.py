# procesos/views.py

from datetime import datetime
from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import (
    ProcesoMaestro, OperacionProceso,
    LoteProduccion, FaseLote, AsignacionFaseOperador
)
from .serializers import (
    ProcesoMaestroSerializer, OperacionProcesoSerializer,
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
    queryset = ProcesoMaestro.objects.prefetch_related('operaciones__materiales_requeridos').all().order_by('-created_at')
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
    """
    queryset = LoteProduccion.objects.prefetch_related('fases__operadores_asignados').all().order_by('-created_at')
    serializer_class = LoteProduccionSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lote = serializer.save()

        operaciones_maestras = lote.proceso_maestro.operaciones.all()
        fases_a_crear = [
            FaseLote(lote=lote, operacion_maestra=op, estado='PENDIENTE')
            for op in operaciones_maestras
        ]
        FaseLote.objects.bulk_create(fases_a_crear)

        headers = self.get_success_headers(serializer.data)
        response_serializer = self.get_serializer(lote)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class FaseLoteViewSet(viewsets.ModelViewSet):
    """
    API endpoint para gestionar el progreso y tiempos reales de las fases instanciadas.
    """
    queryset = FaseLote.objects.select_related('operacion_maestra').all().order_by('operacion_maestra__identificador_paso')
    serializer_class = FaseLoteSerializer

    @action(detail=True, methods=['post'], url_path='cambiar-estado')
    @transaction.atomic
    def cambiar_estado(self, request, pk=None):
        fase = self.get_object()
        
        # REGLA GxP 3: Bloqueo de Inmutabilidad de Lote (Data Lock)
        if fase.lote.estado == 'COMPLETADO':
            return Response({
                "error": "Violación GxP (Data Lock): El Lote de Producción ya está cerrado y liberado. Sus registros son estrictamente inmutables."
            }, status=status.HTTP_403_FORBIDDEN)

        nuevo_estado = request.data.get('estado')

        estados_validos = dict(FaseLote.ESTADO_FASE_CHOICES).keys()
        if nuevo_estado not in estados_validos:
            return Response({"error": "Estado GxP no válido."}, status=status.HTTP_400_BAD_REQUEST)

        # REGLA GxP 1: Prevención de Tareas Fantasma
        if nuevo_estado == 'COMPLETADA' and not fase.operadores_asignados.exists():
            return Response({
                "error": "Violación GxP: No se puede completar una fase operativa sin haber asignado al menos a un operador responsable."
            }, status=status.HTTP_400_BAD_REQUEST)

        tiempo_actual = timezone.now()
        
        if nuevo_estado == 'EN_PROGRESO' and fase.estado == 'PENDIENTE':
            fase.fecha_inicio_real = tiempo_actual
        elif nuevo_estado == 'COMPLETADA' and fase.estado == 'EN_PROGRESO':
            fase.fecha_fin_real = tiempo_actual
            
        fase.estado = nuevo_estado
        fase.save()

        # Automatización del Lote (Padre)
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


class AsignacionFaseOperadorViewSet(viewsets.ModelViewSet):
    """
    API endpoint para auditar y registrar a los operadores en tareas específicas GxP.
    """
    queryset = AsignacionFaseOperador.objects.select_related('operador', 'rol_ejercido').all()
    serializer_class = AsignacionFaseOperadorSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """
        Sobreescritura para inyectar validación de estado de la fase y del lote antes de asignar.
        """
        fase_id = request.data.get('fase_lote')
        
        try:
            fase = FaseLote.objects.get(id=fase_id)
        except FaseLote.DoesNotExist:
            return Response({"error": "La fase especificada no existe."}, status=status.HTTP_404_NOT_FOUND)

        # REGLA GxP 3: Bloqueo de Inmutabilidad de Lote (Data Lock)
        if fase.lote.estado == 'COMPLETADO':
            return Response({
                "error": "Violación GxP (Data Lock): No se puede asignar personal a un Lote de Producción que ya fue cerrado y liberado."
            }, status=status.HTTP_403_FORBIDDEN)

        # REGLA GxP 2: Prevención de Asignaciones Póstumas a fases individuales
        if fase.estado in ['COMPLETADA', 'OMITIDA']:
            return Response({
                "error": f"Violación GxP: No se puede modificar el registro de personal de una fase que ya se encuentra {fase.estado}."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Flujo normal de creación provisto por DRF si pasa las validaciones
        return super().create(request, *args, **kwargs)