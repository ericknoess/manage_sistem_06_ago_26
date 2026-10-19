# procesos/serializers.py

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
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
    operacion_nombre = serializers.SerializerMethodField()
    operacion_id_paso = serializers.CharField(source='operacion_maestra.identificador_paso', read_only=True)
    duracion_estimada = serializers.SerializerMethodField()
    
    # [NUEVO] Inyectamos el tipo_operacion ('ACTIVA' o 'INCUBACION') para ocultar labores pasivas en los tableros
    tipo_operacion = serializers.CharField(source='operacion_maestra.tipo_operacion', read_only=True)
    
    etapa_nombre = serializers.CharField(source='operacion_maestra.etapa.nombre', read_only=True, default='Actividades Sueltas (Sin Etapa)')
    etapa_orden = serializers.IntegerField(source='operacion_maestra.etapa.orden', read_only=True, default=999999)
    
    lote_codigo = serializers.CharField(source='lote.identificador_lote', read_only=True)
    personal_requerido = serializers.IntegerField(source='operacion_maestra.personal_requerido', read_only=True)
    
    operadores_asignados = AsignacionFaseOperadorSerializer(many=True, read_only=True)
    
    equipos_detalles = EquipoSerializer(source='equipos_asignados', many=True, read_only=True)
    materiales_detalles = MaterialInsumoSerializer(source='materiales_asignados', many=True, read_only=True)
    
    duracion_real_horas = serializers.SerializerMethodField()
    desviacion_horas = serializers.SerializerMethodField()

    # Campos derivados en hora local para las pantallas que trabajan por día y hora
    fecha_programada = serializers.SerializerMethodField()
    hora_inicio_programada = serializers.SerializerMethodField()
    hora_fin_programada = serializers.SerializerMethodField()
    fecha_base_cpm = serializers.SerializerMethodField()
    hora_inicio_base_cpm = serializers.SerializerMethodField()

    class Meta:
        model = FaseLote
        fields = [
            'id', 'lote', 'lote_codigo', 'operacion_maestra', 'operacion_nombre', 'operacion_id_paso',
            'tipo_operacion', # <-- Añadido explícitamente a los fields
            'etapa_nombre', 'etapa_orden',
            'estado', 
            'inicio_programado', 'fin_programado', 'inicio_base_cpm', 'fin_base_cpm',
            'fecha_programada', 'hora_inicio_programada', 'hora_fin_programada',
            'fecha_base_cpm', 'hora_inicio_base_cpm',
            'motivo_reprogramacion', 'notas_reprogramacion',
            'es_subtarea_muestreo', 'indice_muestreo',
            'equipos_asignados', 'equipos_detalles', 'materiales_asignados', 'materiales_detalles',
            'fecha_inicio_real', 'fecha_fin_real', 'duracion_estimada', 'duracion_real_horas', 
            'desviacion_horas', 'personal_requerido', 'operadores_asignados'
        ]
        # Estado y horarios solo cambian vía las acciones `cambiar-estado` y `reprogramar`
        read_only_fields = [
            'lote', 'operacion_maestra', 'estado',
            'inicio_programado', 'fin_programado', 'inicio_base_cpm', 'fin_base_cpm',
            'motivo_reprogramacion', 'notas_reprogramacion', 'es_subtarea_muestreo', 'indice_muestreo',
            'fecha_inicio_real', 'fecha_fin_real',
        ]
        extra_kwargs = {
            'equipos_asignados': {'required': False},
            'materiales_asignados': {'required': False},
        }

    @staticmethod
    def _local(valor):
        return timezone.localtime(valor) if valor else None

    def get_fecha_programada(self, obj):
        inicio = self._local(obj.inicio_programado)
        return inicio.date().isoformat() if inicio else None

    def get_hora_inicio_programada(self, obj):
        inicio = self._local(obj.inicio_programado)
        return inicio.strftime('%H:%M:%S') if inicio else None

    def get_hora_fin_programada(self, obj):
        fin = self._local(obj.fin_programado)
        return fin.strftime('%H:%M:%S') if fin else None

    def get_fecha_base_cpm(self, obj):
        inicio = self._local(obj.inicio_base_cpm)
        return inicio.date().isoformat() if inicio else None

    def get_hora_inicio_base_cpm(self, obj):
        inicio = self._local(obj.inicio_base_cpm)
        return inicio.strftime('%H:%M:%S') if inicio else None

    def get_duracion_estimada(self, obj):
        return obj.duracion_planeada.total_seconds() / 3600.0

    def get_operacion_nombre(self, obj):
        if obj.es_subtarea_muestreo and obj.nombre_tarea_dinamica:
            return obj.nombre_tarea_dinamica
        return obj.operacion_maestra.nombre

    def get_duracion_real_horas(self, obj):
        if obj.fecha_inicio_real and obj.fecha_fin_real:
            delta = obj.fecha_fin_real - obj.fecha_inicio_real
            return round(delta.total_seconds() / 3600.0, 4)
        return None

    def get_desviacion_horas(self, obj):
        duracion_real = self.get_duracion_real_horas(obj)
        if duracion_real is not None:
            return round(duracion_real - self.get_duracion_estimada(obj), 4)
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
        # El estado del lote lo gobiernan sus fases y las acciones abortar/archivar
        read_only_fields = ['estado']

    def get_progreso_porcentual(self, obj):
        fases_totales = obj.fases.all()
        total = len(fases_totales)
        if total == 0:
            return 0.0
        completadas = sum(1 for f in fases_totales if f.estado in ['COMPLETADA', 'OMITIDA'])
        return round((completadas / total) * 100, 1)