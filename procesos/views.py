# procesos/views.py

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import ProcesoMaestro, OperacionProceso
from .serializers import ProcesoMaestroSerializer, OperacionProcesoSerializer
from .services import CPMCalculatorService

class ProcesoMaestroViewSet(viewsets.ModelViewSet):
    """
    API endpoint para gestionar las recetas maestras de bioprocesos (CPM).
    """
    queryset = ProcesoMaestro.objects.prefetch_related('operaciones__materiales_requeridos').all().order_by('-created_at')
    serializer_class = ProcesoMaestroSerializer

    @action(detail=True, methods=['get'], url_path='cpm-analisis')
    def cpm_analisis(self, request, pk=None):
        """
        Endpoint REST personalizado que calcula y devuelve la Ruta Crítica, 
        tiempos tempranos, tardíos y holguras de todas las operaciones del proceso.
        """
        proceso = self.get_object()
        operaciones = proceso.operaciones.all()
        
        # Instanciar el servicio de dominio CPM
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