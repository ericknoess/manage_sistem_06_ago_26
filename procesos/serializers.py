# procesos/serializers.py

from rest_framework import serializers
from django.db import transaction
from .models import (
    ProcesoMaestro, EtapaProceso, OperacionProceso, RequerimientoPersonalFase,
    LoteProduccion, FaseLote, AsignacionFaseOperador
)
from actividades.serializers import MaterialInsumoSerializer, EquipoSerializer
from roster.models import RolOperador


# ==============================================================================
# 1. SERIALIZADORES MAESTROS (PLANTILLAS Y DISEÑO)
# ==============================================================================

class EtapaProcesoSerializer(serializers.ModelSerializer):
    """
    Serializer para el nuevo nivel jerárquico ISA-88 (Etapas).
    """
    class Meta:
        model = EtapaProceso
        fields = ['id', 'proceso', 'nombre', 'orden', 'created_at', 'updated_at']


class RequerimientoPersonalFaseSerializer(serializers.ModelSerializer):
    rol_nombre = serializers.CharField(source='rol.nombre', read_only=True)

    class Meta:
        model = RequerimientoPersonalFase
        fields = ['id', 'rol', 'rol_nombre', 'cantidad']


class OperacionProcesoSerializer(serializers.ModelSerializer):
    materiales_requeridos_detalles = MaterialInsumoSerializer(source='materiales_requeridos', many=True, read_only=True)
    requerimientos_rol = RequerimientoPersonalFaseSerializer(many=True, required=False)
    requerimientos_rol_detalles = RequerimientoPersonalFaseSerializer(source='requerimientos_rol', many=True, read_only=True)

    class Meta:
        model = OperacionProceso
        fields = [
            'id', 'proceso', 'etapa', 'identificador_paso', 'nombre', 'tipo_operacion',
            'duracion_horas', 'frecuencia_muestreo_horas', 'duracion_muestreo_horas',
            'ops_muestreo', 'predecesora', 'tipo_dependencia', 'desfase_horas',
            'personal_requerido', 'tipo_equipo_requerido', 'materiales_requeridos',
            'materiales_requeridos_detalles', 'requerimientos_rol', 'requerimientos_rol_detalles'
        ]
        extra_kwargs = {
            'etapa': {'required': False, 'allow_null': True},
            'materiales_requeridos': {'required': False},
            'predecesora': {'required': False, 'allow_null': True},
            'tipo_dependencia': {'required': False},
            'desfase_horas': {'required': False},
            'requerimientos_rol': {'required': False},
        }

    def validate(self, data):
        predecesora = data.get('predecesora', None)
        
        if self.instance and predecesora and self.instance.id == predecesora.id:
            raise serializers.ValidationError({"predecesora": "Una operación no puede depender de sí misma."})

        if self.instance and predecesora:
            actual_pred = predecesora
            visitados = set()
            
            while actual_pred:
                if actual_pred.id == self.instance.id:
                    raise serializers.ValidationError({
                        "predecesora": "⚠️ Referencia circular detectada. La predecesora ya depende de esta operación."
                    })
                if actual_pred.id in visitados:
                    break
                visitados.add(actual_pred.id)
                actual_pred = actual_pred.predecesora

        return data

    @transaction.atomic
    def create(self, validated_data):
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
    # DUAL EXPOSURE: Mantenemos 'operaciones' plano para el algoritmo matemático CPM, 
    # y enviamos 'etapas' para que el frontend dibuje la estructura jerárquica.
    etapas = EtapaProcesoSerializer(many=True, read_only=True)
    operaciones = OperacionProcesoSerializer(many=True, read_only=True)

    class Meta:
        model = ProcesoMaestro
        fields = [
            'id', 'nombre', 'descripcion', 'activo', 'etapas', 'operaciones', 'created_at', 'updated_at'
        ]

# ==============================================================================
# 2. SERIALIZADORES TRANSACCIONALES (EJECUCIÓN DE LOTES Y MES)
# ==============================================================================

class AsignacionFaseOperadorSerializer(serializers.ModelSerializer):
    operador_nombre = serializers.CharField(source='operador.nombre', read_only=True)
    rol_nombre = serializers.CharField(source='rol_ejercido.nombre', read_only=True)

    class Meta:
        model = AsignacionFaseOperador
        fields = [
            'id', 'fase_lote', 'operador', 'operador_nombre',
            'rol_ejercido', 'rol_nombre', 'horas_invertidas', 'asignado_en'
        ]


class FaseLoteSerializer(serializers.ModelSerializer):
    """
    Serializer para la fase. Actúa como tarea en el calendario y como registro eBR.
    """
    operacion_nombre = serializers.CharField(source='operacion_maestra.nombre', read_only=True)
    operacion_id_paso = serializers.CharField(source='operacion_maestra.identificador_paso', read_only=True)
    duracion_estimada = serializers.FloatField(source='operacion_maestra.duracion_horas', read_only=True)
    
    # --- NUEVOS CAMPOS: Inyección de la Jerarquía ISA-88 para el eBR ---
    etapa_nombre = serializers.CharField(source='operacion_maestra.etapa.nombre', read_only=True, default='Actividades Sueltas (Sin Etapa)')
    etapa_orden = serializers.IntegerField(source='operacion_maestra.etapa.orden', read_only=True, default=999999)
    
    # Datos inyectados para facilitar el Tablero Semanal (MES)
    lote_codigo = serializers.CharField(source='lote.identificador_lote', read_only=True)
    personal_requerido = serializers.IntegerField(source='operacion_maestra.personal_requerido', read_only=True)
    
    operadores_asignados = AsignacionFaseOperadorSerializer(many=True, read_only=True)
    
    # Detalles de recursos para lectura
    equipos_detalles = EquipoSerializer(source='equipos_asignados', many=True, read_only=True)
    materiales_detalles = MaterialInsumoSerializer(source='materiales_asignados', many=True, read_only=True)
    
    # KPIs calculados
    duracion_real_horas = serializers.SerializerMethodField()
    desviacion_horas = serializers.SerializerMethodField()

    class Meta:
        model = FaseLote
        fields = [
            'id', 'lote', 'lote_codigo', 'operacion_maestra', 'operacion_nombre', 'operacion_id_paso',
            'etapa_nombre', 'etapa_orden', # <-- Incorporados a la respuesta JSON
            'estado', 'fecha_programada', 'hora_inicio_programada', 'hora_fin_programada',
            'equipos_asignados', 'equipos_detalles', 'materiales_asignados', 'materiales_detalles',
            'fecha_inicio_real', 'fecha_fin_real', 'duracion_estimada', 'duracion_real_horas', 
            'desviacion_horas', 'personal_requerido', 'operadores_asignados'
        ]
        extra_kwargs = {
            'equipos_asignados': {'required': False},
            'materiales_asignados': {'required': False},
        }

    def get_duracion_real_horas(self, obj):
        if obj.fecha_inicio_real and obj.fecha_fin_real:
            delta = obj.fecha_fin_real - obj.fecha_inicio_real
            return round(delta.total_seconds() / 3600.0, 4)
        return None

    def get_desviacion_horas(self, obj):
        duracion_real = self.get_duracion_real_horas(obj)
        if duracion_real is not None:
            estimada = obj.operacion_maestra.duracion_horas
            return round(duracion_real - estimada, 4)
        return None


class LoteProduccionSerializer(serializers.ModelSerializer):
    proceso_nombre = serializers.CharField(source='proceso_maestro.nombre', read_only=True)
    fases = FaseLoteSerializer(many=True, read_only=True)
    progreso_porcentual = serializers.SerializerMethodField()

    class Meta:
        model = LoteProduccion
        fields = [
            'id', 'identificador_lote', 'proceso_maestro', 'proceso_nombre',
            'estado', 'fecha_inicio_planeada', 'progreso_porcentual', 'fases',
            'created_at', 'updated_at'
        ]

    def get_progreso_porcentual(self, obj):
        fases_totales = obj.fases.all()
        total = len(fases_totales)
        if total == 0:
            return 0.0
        completadas = sum(1 for f in fases_totales if f.estado in ['COMPLETADA', 'OMITIDA'])
        return round((completadas / total) * 100, 1)