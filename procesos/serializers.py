# procesos/serializers.py

from rest_framework import serializers
from django.db import transaction
from .models import (
    ProcesoMaestro, OperacionProceso, RequerimientoPersonalFase,
    LoteProduccion, FaseLote, AsignacionFaseOperador
)
from actividades.serializers import MaterialInsumoSerializer
from roster.models import RolOperador


# ==============================================================================
# 1. SERIALIZADORES MAESTROS (PLANTILLAS Y DISEÑO)
# ==============================================================================

class RequerimientoPersonalFaseSerializer(serializers.ModelSerializer):
    """
    Serializer para los requerimientos específicos de roles/competencias en una fase CPM.
    """
    rol_nombre = serializers.CharField(source='rol.nombre', read_only=True)

    class Meta:
        model = RequerimientoPersonalFase
        fields = ['id', 'rol', 'rol_nombre', 'cantidad']


class OperacionProcesoSerializer(serializers.ModelSerializer):
    """
    Serializer para las operaciones o fases CPM de un proceso maestro,
    incluyendo soporte para dependencias avanzadas, prevención de ciclos (DAG)
    y requerimientos de personal basados en competencias (Skill-based).
    """
    materiales_requeridos_detalles = MaterialInsumoSerializer(source='materiales_requeridos', many=True, read_only=True)
    
    # Soporte para lectura y escritura de requerimientos múltiples de personal por rol
    requerimientos_rol = RequerimientoPersonalFaseSerializer(many=True, required=False)
    requerimientos_rol_detalles = RequerimientoPersonalFaseSerializer(source='requerimientos_rol', many=True, read_only=True)

    class Meta:
        model = OperacionProceso
        fields = [
            'id',
            'proceso',
            'identificador_paso',
            'nombre',
            'tipo_operacion',
            'duracion_horas',
            'frecuencia_muestreo_horas',
            'duracion_muestreo_horas',
            'ops_muestreo',
            'predecesora',
            'tipo_dependencia',
            'desfase_horas',
            'personal_requerido',
            'tipo_equipo_requerido',
            'materiales_requeridos',
            'materiales_requeridos_detalles',
            'requerimientos_rol',
            'requerimientos_rol_detalles'
        ]
        extra_kwargs = {
            'materiales_requeridos': {'required': False},
            'predecesora': {'required': False, 'allow_null': True},
            'tipo_dependencia': {'required': False},
            'desfase_horas': {'required': False},
            'requerimientos_rol': {'required': False},
        }

    def validate(self, data):
        """
        Validación de integridad del modelo y prevención estricta de ciclos en el grafo (DAG).
        Evita que el algoritmo CPM entre en bucles infinitos.
        """
        predecesora = data.get('predecesora', None)
        
        # 1. Una operación no puede ser predecesora de sí misma
        if self.instance and predecesora and self.instance.id == predecesora.id:
            raise serializers.ValidationError({"predecesora": "Una operación no puede depender de sí misma."})

        # 2. Validación de Referencias Circulares (Búsqueda de ciclos en el árbol de predecesoras)
        if self.instance and predecesora:
            actual_pred = predecesora
            visitados = set()
            
            while actual_pred:
                if actual_pred.id == self.instance.id:
                    raise serializers.ValidationError({
                        "predecesora": "⚠️ Referencia circular detectada. La predecesora seleccionada ya depende directa o indirectamente de esta operación."
                    })
                if actual_pred.id in visitados:
                    break
                visitados.add(actual_pred.id)
                actual_pred = actual_pred.predecesora

        return data

    @transaction.atomic
    def create(self, validated_data):
        """
        Creación atómica de la operación y sus requerimientos múltiples de personal.
        """
        requerimientos_data = validated_data.pop('requerimientos_rol', [])
        materiales_data = validated_data.pop('materiales_requeridos', [])
        
        operacion = OperacionProceso.objects.create(**validated_data)
        
        if materiales_data:
            operacion.materiales_requeridos.set(materiales_data)
            
        for req in requerimientos_data:
            RequerimientoPersonalFase.objects.create(operacion=operacion, **req)
            
        return operacion

    @transaction.atomic
    def update(self, instance, validated_data):
        """
        Actualización atómica de la operación y sincronización de requerimientos por rol.
        """
        requerimientos_data = validated_data.pop('requerimientos_rol', None)
        materiales_data = validated_data.pop('materiales_requeridos', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if materiales_data is not None:
            instance.materiales_requeridos.set(materiales_data)

        if requerimientos_data is not None:
            instance.requerimientos_rol.all().delete()
            for req in requerimientos_data:
                RequerimientoPersonalFase.objects.create(operacion=instance, **req)

        return instance


class ProcesoMaestroSerializer(serializers.ModelSerializer):
    """
    Serializer maestro para el bioproceso, incluyendo sus fases operativas anidadas.
    """
    operaciones = OperacionProcesoSerializer(many=True, read_only=True)

    class Meta:
        model = ProcesoMaestro
        fields = [
            'id',
            'nombre',
            'descripcion',
            'activo',
            'operaciones',
            'created_at',
            'updated_at'
        ]

# ==============================================================================
# 2. SERIALIZADORES TRANSACCIONALES (EJECUCIÓN DE LOTES GxP)
# ==============================================================================

class AsignacionFaseOperadorSerializer(serializers.ModelSerializer):
    """
    Serializer para el registro inmutable de qué operador y bajo qué rol 
    ejecutó una tarea específica en un lote real.
    """
    operador_nombre = serializers.CharField(source='operador.nombre', read_only=True)
    rol_nombre = serializers.CharField(source='rol_ejercido.nombre', read_only=True)

    class Meta:
        model = AsignacionFaseOperador
        fields = [
            'id',
            'fase_lote',
            'operador',
            'operador_nombre',
            'rol_ejercido',
            'rol_nombre',
            'horas_invertidas',
            'asignado_en'
        ]


class FaseLoteSerializer(serializers.ModelSerializer):
    """
    Serializer para la instancia de ejecución de una fase, 
    anidando a los operadores que han sido asignados a ella.
    """
    operacion_nombre = serializers.CharField(source='operacion_maestra.nombre', read_only=True)
    operacion_id_paso = serializers.CharField(source='operacion_maestra.identificador_paso', read_only=True)
    operadores_asignados = AsignacionFaseOperadorSerializer(many=True, read_only=True)

    class Meta:
        model = FaseLote
        fields = [
            'id',
            'lote',
            'operacion_maestra',
            'operacion_nombre',
            'operacion_id_paso',
            'estado',
            'fecha_inicio_real',
            'fecha_fin_real',
            'operadores_asignados'
        ]


class LoteProduccionSerializer(serializers.ModelSerializer):
    """
    Serializer para la instancia principal del Lote de Producción,
    anidando todo el Batch Record Electrónico (eBR).
    """
    proceso_nombre = serializers.CharField(source='proceso_maestro.nombre', read_only=True)
    fases = FaseLoteSerializer(many=True, read_only=True)

    class Meta:
        model = LoteProduccion
        fields = [
            'id',
            'identificador_lote',
            'proceso_maestro',
            'proceso_nombre',
            'estado',
            'fecha_inicio_planeada',
            'fases',
            'created_at',
            'updated_at'
        ]