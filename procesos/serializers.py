# procesos/serializers.py

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from .models import (
    ProcesoMaestro, EtapaProceso, OperacionProceso, RequerimientoPersonalFase,
    LoteProduccion, FaseLote, AsignacionFaseOperador, MaterialOperacion, MaterialFase,
    EquipoOperacion, EquipoFase, ReservaEquipo,
)
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


class MaterialOperacionSerializer(serializers.ModelSerializer):
    material_nombre = serializers.CharField(source='material.nombre', read_only=True)
    unidad_medida = serializers.CharField(source='material.unidad_medida', read_only=True)
    material_activo = serializers.BooleanField(source='material.activo', read_only=True)

    class Meta:
        model = MaterialOperacion
        fields = ['id', 'material', 'material_nombre', 'unidad_medida', 'material_activo', 'cantidad', 'anticipacion_horas', 'aplica_a']

    def validate_cantidad(self, valor):
        if valor <= 0:
            raise serializers.ValidationError("La cantidad debe ser mayor que cero.")
        return valor

    def validate_anticipacion_horas(self, valor):
        if valor < 0:
            raise serializers.ValidationError("La anticipación no puede ser negativa.")
        return valor


class EquipoOperacionSerializer(serializers.ModelSerializer):
    tipo_nombre = serializers.CharField(source='tipo.nombre', read_only=True)
    tipo_activo = serializers.BooleanField(source='tipo.activo', read_only=True)

    class Meta:
        model = EquipoOperacion
        fields = ['id', 'tipo', 'tipo_nombre', 'tipo_activo', 'cantidad', 'horas_preparacion', 'horas_limpieza', 'aplica_a']

    def validate_cantidad(self, valor):
        if valor < 1:
            raise serializers.ValidationError("La cantidad debe ser al menos 1.")
        return valor

    def validate(self, data):
        for campo in ('horas_preparacion', 'horas_limpieza'):
            if (data.get(campo) or 0) < 0:
                raise serializers.ValidationError({campo: "Las horas no pueden ser negativas."})
        return data


class OperacionProcesoSerializer(serializers.ModelSerializer):
    materiales = MaterialOperacionSerializer(many=True, required=False)
    equipos = EquipoOperacionSerializer(many=True, required=False)
    requerimientos_rol = RequerimientoPersonalFaseSerializer(many=True, required=False)
    requerimientos_rol_detalles = RequerimientoPersonalFaseSerializer(source='requerimientos_rol', many=True, read_only=True)

    class Meta:
        model = OperacionProceso
        fields = [
            'id', 'proceso', 'etapa', 'identificador_paso', 'nombre', 'tipo_operacion',
            'duracion_horas', 'frecuencia_muestreo_horas', 'duracion_muestreo_horas',
            'ops_muestreo', 'predecesora', 'tipo_dependencia', 'desfase_horas',
            'tolerancia_antes_horas', 'tolerancia_despues_horas',
            'personal_requerido', 'materiales', 'equipos',
            'requerimientos_rol', 'requerimientos_rol_detalles'
        ]
        extra_kwargs = {
            'etapa': {'required': False, 'allow_null': True},
            'predecesora': {'required': False, 'allow_null': True},
            'tipo_dependencia': {'required': False},
            'desfase_horas': {'required': False},
            'requerimientos_rol': {'required': False},
        }

    def validate(self, data):
        for campo in ('tolerancia_antes_horas', 'tolerancia_despues_horas'):
            if data.get(campo) is not None and data[campo] < 0:
                raise serializers.ValidationError({campo: "La tolerancia no puede ser negativa."})

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

        materiales = data.get('materiales')
        if materiales:
            vistos = set()
            for m in materiales:
                clave = (m['material'].id, m.get('aplica_a', 'ACTIVIDAD'))
                if clave in vistos:
                    raise serializers.ValidationError({"materiales": f"El material [{m['material'].id}] está repetido."})
                vistos.add(clave)

            # Los materiales por muestreo solo tienen sentido si la operación genera muestreos
            valor = lambda campo: data.get(campo, getattr(self.instance, campo, None))
            genera_muestreos = valor('tipo_operacion') == 'INCUBACION' and (valor('frecuencia_muestreo_horas') or 0) > 0
            if not genera_muestreos and any(m.get('aplica_a') == 'MUESTREO' for m in materiales):
                raise serializers.ValidationError({"materiales": "Solo una incubación con frecuencia de muestreo puede tener materiales por muestreo."})

        equipos = data.get('equipos')
        if equipos:
            vistos = set()
            for e in equipos:
                clave = (e['tipo'].codigo, e.get('aplica_a', 'ACTIVIDAD'))
                if clave in vistos:
                    raise serializers.ValidationError({"equipos": f"El tipo de equipo {e['tipo'].nombre} está repetido."})
                vistos.add(clave)
            valor = lambda campo: data.get(campo, getattr(self.instance, campo, None))
            genera_muestreos = valor('tipo_operacion') == 'INCUBACION' and (valor('frecuencia_muestreo_horas') or 0) > 0
            if not genera_muestreos and any(e.get('aplica_a') == 'MUESTREO' for e in equipos):
                raise serializers.ValidationError({"equipos": "Solo una incubación con frecuencia de muestreo puede pedir equipo por muestreo."})

        return data

    @staticmethod
    def _guardar_equipos(operacion, equipos_data):
        operacion.equipos.all().delete()
        EquipoOperacion.objects.bulk_create([EquipoOperacion(operacion=operacion, **e) for e in equipos_data])

    @staticmethod
    def _guardar_materiales(operacion, materiales_data):
        operacion.materiales.all().delete()
        MaterialOperacion.objects.bulk_create([MaterialOperacion(operacion=operacion, **m) for m in materiales_data])

    @transaction.atomic
    def create(self, validated_data):
        requerimientos_data = validated_data.pop('requerimientos_rol', [])
        materiales_data = validated_data.pop('materiales', [])
        equipos_data = validated_data.pop('equipos', [])

        operacion = OperacionProceso.objects.create(**validated_data)
        self._guardar_materiales(operacion, materiales_data)
        self._guardar_equipos(operacion, equipos_data)
            
        for req in requerimientos_data:
            RequerimientoPersonalFase.objects.create(operacion=operacion, **req)
            
        return operacion

    @transaction.atomic
    def update(self, instance, validated_data):
        requerimientos_data = validated_data.pop('requerimientos_rol', None)
        materiales_data = validated_data.pop('materiales', None)
        equipos_data = validated_data.pop('equipos', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if materiales_data is not None:
            self._guardar_materiales(instance, materiales_data)
        if equipos_data is not None:
            self._guardar_equipos(instance, equipos_data)

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


class MaterialFaseSerializer(serializers.ModelSerializer):
    material_nombre = serializers.CharField(source='material.nombre', read_only=True)
    categoria = serializers.CharField(source='material.categoria', read_only=True)
    condicion_almacenamiento = serializers.CharField(source='material.condicion_almacenamiento', read_only=True)
    momento_requerido = serializers.DateTimeField(read_only=True)
    ajustado = serializers.SerializerMethodField()

    class Meta:
        model = MaterialFase
        fields = [
            'id', 'fase', 'material', 'material_nombre', 'unidad_medida', 'categoria', 'condicion_almacenamiento',
            'cantidad', 'cantidad_receta', 'anticipacion_horas', 'momento_requerido',
            'activo', 'ajustado', 'motivo_ajuste', 'ajustado_en',
        ]
        read_only_fields = fields

    def get_ajustado(self, obj):
        return obj.ajustado_en is not None


class RequerimientoMaterialSerializer(MaterialFaseSerializer):
    """Fila del monitor de materiales: el requerimiento con el contexto de su lote y actividad."""
    lote_id = serializers.IntegerField(source='fase.lote_id', read_only=True)
    lote_codigo = serializers.CharField(source='fase.lote.identificador_lote', read_only=True)
    lote_estado = serializers.CharField(source='fase.lote.estado', read_only=True)
    fase_estado = serializers.CharField(source='fase.estado', read_only=True)
    paso = serializers.CharField(source='fase.operacion_maestra.identificador_paso', read_only=True)
    actividad = serializers.SerializerMethodField()
    inicio_actividad = serializers.DateTimeField(source='fase.inicio_programado', read_only=True)

    class Meta(MaterialFaseSerializer.Meta):
        fields = MaterialFaseSerializer.Meta.fields + [
            'lote_id', 'lote_codigo', 'lote_estado', 'fase_estado', 'paso', 'actividad', 'inicio_actividad',
        ]
        read_only_fields = fields

    def get_actividad(self, obj):
        fase = obj.fase
        return fase.nombre_tarea_dinamica if fase.es_subtarea_muestreo and fase.nombre_tarea_dinamica else fase.operacion_maestra.nombre


class ReservaEquipoSerializer(serializers.ModelSerializer):
    equipo_nombre = serializers.CharField(source='equipo.nombre', read_only=True)
    equipo_estado = serializers.CharField(source='equipo.estado', read_only=True)
    vigente = serializers.BooleanField(read_only=True)
    inicio = serializers.SerializerMethodField()
    fin = serializers.SerializerMethodField()

    class Meta:
        model = ReservaEquipo
        fields = ['id', 'equipo', 'equipo_nombre', 'equipo_estado', 'desde', 'hasta', 'activo', 'vigente',
                  'motivo', 'creado_en', 'inicio', 'fin']
        read_only_fields = fields

    def get_inicio(self, obj):
        return obj.ventana()[0]

    def get_fin(self, obj):
        return obj.ventana()[1]


class EquipoFaseSerializer(serializers.ModelSerializer):
    tipo_nombre = serializers.CharField(source='tipo.nombre', read_only=True)
    reservas = ReservaEquipoSerializer(many=True, read_only=True)
    reservados = serializers.SerializerMethodField()
    ocupacion_inicio = serializers.SerializerMethodField()
    ocupacion_fin = serializers.SerializerMethodField()
    ajustado = serializers.SerializerMethodField()

    class Meta:
        model = EquipoFase
        fields = [
            'id', 'fase', 'tipo', 'tipo_nombre', 'cantidad', 'cantidad_receta', 'horas_preparacion', 'horas_limpieza',
            'activo', 'ajustado', 'motivo_ajuste', 'ajustado_en', 'reservas', 'reservados',
            'ocupacion_inicio', 'ocupacion_fin',
        ]
        read_only_fields = fields

    def get_reservados(self, obj):
        """Equipos reservados vigentes (los cerrados por un cambio quedan como historial)."""
        return sum(1 for r in obj.reservas.all() if r.vigente)

    def get_ocupacion_inicio(self, obj):
        return obj.ventana_ocupacion()[0]

    def get_ocupacion_fin(self, obj):
        return obj.ventana_ocupacion()[1]

    def get_ajustado(self, obj):
        return obj.ajustado_en is not None


class FaseLoteSerializer(serializers.ModelSerializer):
    operacion_nombre = serializers.SerializerMethodField()
    operacion_id_paso = serializers.CharField(source='operacion_maestra.identificador_paso', read_only=True)
    duracion_estimada = serializers.SerializerMethodField()
    
    # [NUEVO] Inyectamos el tipo_operacion ('ACTIVA' o 'INCUBACION') para ocultar labores pasivas en los tableros
    tipo_operacion = serializers.CharField(source='operacion_maestra.tipo_operacion', read_only=True)
    
    etapa_nombre = serializers.CharField(source='operacion_maestra.etapa.nombre', read_only=True, default='Actividades Sueltas (Sin Etapa)')
    etapa_orden = serializers.IntegerField(source='operacion_maestra.etapa.orden', read_only=True, default=999999)
    # null cuando la actividad no tiene etapa en la receta (el Gantt lo usa para agrupar)
    etapa_id = serializers.IntegerField(source='operacion_maestra.etapa_id', read_only=True)
    
    lote_codigo = serializers.CharField(source='lote.identificador_lote', read_only=True)
    personal_requerido = serializers.IntegerField(source='operacion_maestra.personal_requerido', read_only=True)
    
    operadores_asignados = AsignacionFaseOperadorSerializer(many=True, read_only=True)
    
    equipos = EquipoFaseSerializer(many=True, read_only=True)
    materiales = MaterialFaseSerializer(many=True, read_only=True)
    
    duracion_real_horas = serializers.SerializerMethodField()
    desviacion_horas = serializers.SerializerMethodField()

    # Campos derivados en hora local para las pantallas que trabajan por día y hora
    fecha_programada = serializers.SerializerMethodField()
    hora_inicio_programada = serializers.SerializerMethodField()
    hora_fin_programada = serializers.SerializerMethodField()
    fecha_base_cpm = serializers.SerializerMethodField()
    hora_inicio_base_cpm = serializers.SerializerMethodField()

    # Ventana en que la fase puede iniciar sin desviación (tolerancia de la receta)
    tolerancia_antes_horas = serializers.FloatField(source='operacion_maestra.tolerancia_antes_horas', read_only=True)
    tolerancia_despues_horas = serializers.FloatField(source='operacion_maestra.tolerancia_despues_horas', read_only=True)

    class Meta:
        model = FaseLote
        fields = [
            'id', 'lote', 'lote_codigo', 'operacion_maestra', 'operacion_nombre', 'operacion_id_paso',
            'tipo_operacion', # <-- Añadido explícitamente a los fields
            'etapa_id', 'etapa_nombre', 'etapa_orden',
            'estado', 
            'inicio_programado', 'fin_programado', 'inicio_base_cpm', 'fin_base_cpm',
            'fecha_programada', 'hora_inicio_programada', 'hora_fin_programada',
            'fecha_base_cpm', 'hora_inicio_base_cpm',
            'motivo_reprogramacion', 'notas_reprogramacion',
            'es_subtarea_muestreo', 'indice_muestreo',
            'equipos', 'materiales',
            'fecha_inicio_real', 'fecha_fin_real', 'duracion_estimada', 'duracion_real_horas', 
            'desviacion_horas', 'personal_requerido', 'operadores_asignados',
            'tolerancia_antes_horas', 'tolerancia_despues_horas',
        ]
        # Estado y horarios solo cambian vía las acciones `cambiar-estado` y `reprogramar`
        read_only_fields = [
            'lote', 'operacion_maestra', 'estado',
            'inicio_programado', 'fin_programado', 'inicio_base_cpm', 'fin_base_cpm',
            'motivo_reprogramacion', 'notas_reprogramacion', 'es_subtarea_muestreo', 'indice_muestreo',
            'fecha_inicio_real', 'fecha_fin_real',
        ]

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