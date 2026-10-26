# procesos/serializers.py

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from .models import (
    ProcesoMaestro, EtapaProceso, OperacionProceso, RequerimientoPersonalFase,
    LoteProduccion, FaseLote, AsignacionFaseOperador, MaterialOperacion, MaterialFase,
    EquipoOperacion, EquipoFase, ReservaEquipo, EntregaMaterial,
)
from roster.models import RolOperador
from datos_proceso.serializers import SeccionCapturaSerializer, guardar_secciones, validar_secciones_de_operacion


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
    secciones_captura = SeccionCapturaSerializer(many=True, required=False)

    class Meta:
        model = OperacionProceso
        fields = [
            'id', 'proceso', 'etapa', 'identificador_paso', 'nombre', 'tipo_operacion',
            'duracion_horas', 'frecuencia_muestreo_horas', 'duracion_muestreo_horas',
            'ops_muestreo', 'muestreo_inicial', 'predecesora', 'tipo_dependencia', 'desfase_horas',
            'tolerancia_antes_horas', 'tolerancia_despues_horas',
            'personal_requerido', 'materiales', 'equipos',
            'requerimientos_rol', 'requerimientos_rol_detalles',
            'captura_datos', 'edad_cero', 'edad_cero_lote', 'secciones_captura',
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

        self._validar_datos_proceso(data)
        return data

    def _validar_datos_proceso(self, data):
        """Muestreo inicial, captura de datos y edad 0 (una actividad por etapa y una por lote)."""
        valor = lambda campo, defecto=None: data.get(campo, getattr(self.instance, campo, defecto) if self.instance else defecto)
        es_incubacion = valor('tipo_operacion', 'ACTIVA') == 'INCUBACION'
        frecuencia = valor('frecuencia_muestreo_horas', 0) or 0
        genera_muestreos = es_incubacion and frecuencia > 0
        if valor('muestreo_inicial', False) and not genera_muestreos:
            data['muestreo_inicial'] = False

        captura = valor('captura_datos', 'NINGUNA')
        if captura == 'NINGUNA':
            if 'captura_datos' in data or 'secciones_captura' in data:
                data['secciones_captura'] = []
        elif 'secciones_captura' in data:
            error = validar_secciones_de_operacion(
                data['secciones_captura'], captura, es_incubacion, frecuencia,
                valor('duracion_horas', 0) or 0, bool(valor('muestreo_inicial', False)))
            if error:
                raise serializers.ValidationError({"secciones_captura": error})
        else:
            # Sin secciones en la petición: la forma de captura debe seguir siendo posible con las que ya tiene
            if captura == 'MUESTREOS' and not genera_muestreos:
                raise serializers.ValidationError({"captura_datos": "Solo una incubación con frecuencia de muestreo captura datos en cada muestreo."})
            if not (self.instance and self.instance.secciones_captura.exists()):
                raise serializers.ValidationError({"secciones_captura": "Agrega al menos una sección con parámetros."})

        edad_cero = valor('edad_cero', '') or ''
        edad_cero_lote = bool(valor('edad_cero_lote', False))
        if edad_cero_lote and not edad_cero:
            raise serializers.ValidationError({"edad_cero_lote": "Para ser la edad 0 del lote, la actividad debe definir la edad 0 de su etapa (al iniciar o al completar)."})
        if edad_cero:
            etapa = valor('etapa')
            if not etapa:
                raise serializers.ValidationError({"edad_cero": "Solo una actividad dentro de una etapa puede definir su edad 0."})
            otras = OperacionProceso.objects.filter(proceso=valor('proceso')).exclude(edad_cero='')
            if self.instance:
                otras = otras.exclude(pk=self.instance.pk)
            repetida = otras.filter(etapa=etapa).first()
            if repetida:
                raise serializers.ValidationError({"edad_cero": f"La edad 0 de la etapa «{etapa.nombre}» ya la define [{repetida.identificador_paso}] {repetida.nombre}."})
            repetida = otras.filter(edad_cero_lote=True).first() if edad_cero_lote else None
            if repetida:
                raise serializers.ValidationError({"edad_cero_lote": f"La edad 0 del lote ya la define [{repetida.identificador_paso}] {repetida.nombre}."})

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
        secciones_data = validated_data.pop('secciones_captura', [])

        operacion = OperacionProceso.objects.create(**validated_data)
        self._guardar_materiales(operacion, materiales_data)
        self._guardar_equipos(operacion, equipos_data)
        guardar_secciones(operacion, secciones_data)
            
        for req in requerimientos_data:
            RequerimientoPersonalFase.objects.create(operacion=operacion, **req)
            
        return operacion

    @transaction.atomic
    def update(self, instance, validated_data):
        requerimientos_data = validated_data.pop('requerimientos_rol', None)
        materiales_data = validated_data.pop('materiales', None)
        equipos_data = validated_data.pop('equipos', None)
        secciones_data = validated_data.pop('secciones_captura', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if materiales_data is not None:
            self._guardar_materiales(instance, materiales_data)
        if equipos_data is not None:
            self._guardar_equipos(instance, equipos_data)
        if secciones_data is not None:
            guardar_secciones(instance, secciones_data)

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


class EntregaMaterialSerializer(serializers.ModelSerializer):
    """Entrega o devolución de material, con quién la hizo y quién la recibió o rechazó."""
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)
    estado_display = serializers.CharField(source='get_estado_display', read_only=True)
    material = serializers.CharField(source='material_fase.material_id', read_only=True)
    material_nombre = serializers.CharField(source='material_fase.material.nombre', read_only=True)
    fase = serializers.IntegerField(source='material_fase.fase_id', read_only=True)
    lote_codigo = serializers.CharField(source='material_fase.fase.lote.identificador_lote', read_only=True)
    disponible_devolver = serializers.SerializerMethodField()

    class Meta:
        model = EntregaMaterial
        fields = [
            'id', 'material_fase', 'material', 'material_nombre', 'fase', 'lote_codigo', 'tipo', 'tipo_display',
            'devolucion_de', 'cantidad', 'unidad_medida', 'lote_material', 'caducidad', 'observaciones',
            'estado', 'estado_display', 'entregado_por_nombre', 'entregado_en',
            'recibido_por_nombre', 'recibido_en', 'motivo_rechazo', 'disponible_devolver',
        ]
        read_only_fields = fields

    def get_disponible_devolver(self, obj):
        from .services import disponible_para_devolver
        if obj.tipo != 'ENTREGA' or obj.estado != 'RECIBIDA':
            return None
        return disponible_para_devolver(obj)


class MaterialFaseSerializer(serializers.ModelSerializer):
    material_nombre = serializers.CharField(source='material.nombre', read_only=True)
    categoria = serializers.CharField(source='material.categoria', read_only=True)
    condicion_almacenamiento = serializers.CharField(source='material.condicion_almacenamiento', read_only=True)
    momento_requerido = serializers.DateTimeField(read_only=True)
    ajustado = serializers.SerializerMethodField()
    # Avance del surtido (recibido, en tránsito, estado) y sus entregas y devoluciones
    surtido = serializers.SerializerMethodField()
    entregas = EntregaMaterialSerializer(many=True, read_only=True)

    class Meta:
        model = MaterialFase
        fields = [
            'id', 'fase', 'material', 'material_nombre', 'unidad_medida', 'categoria', 'condicion_almacenamiento',
            'cantidad', 'cantidad_receta', 'anticipacion_horas', 'momento_requerido',
            'activo', 'ajustado', 'motivo_ajuste', 'ajustado_en', 'surtido', 'entregas',
        ]
        read_only_fields = fields

    def get_ajustado(self, obj):
        return obj.ajustado_en is not None

    def get_surtido(self, obj):
        from .services import resumen_surtido
        r = resumen_surtido(obj)
        return {k: (str(v) if not isinstance(v, str) else v) for k, v in r.items()}


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

    # Datos de proceso: qué pide la fase y si ya se capturaron; si admite muestras adicionales (incubación)
    captura = serializers.SerializerMethodField()
    admite_muestra_adicional = serializers.SerializerMethodField()

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
            'tolerancia_antes_horas', 'tolerancia_despues_horas', 'captura', 'admite_muestra_adicional',
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

    def get_captura(self, obj):
        from datos_proceso.services import resumen_captura
        return resumen_captura(obj)

    def get_admite_muestra_adicional(self, obj):
        from datos_proceso.services import operacion_admite_adicional
        return operacion_admite_adicional(obj)

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


class LoteResumenSerializer(serializers.ModelSerializer):
    """Lote para listas (sin sus tareas): con cientos de lotes de miles de tareas, las tareas se piden aparte."""
    proceso_nombre = serializers.CharField(source='proceso_maestro.nombre', read_only=True)
    progreso_porcentual = serializers.SerializerMethodField()

    class Meta:
        model = LoteProduccion
        fields = ['id', 'identificador_lote', 'proceso_maestro', 'proceso_nombre', 'estado', 'fecha_inicio_planeada',
                  'progreso_porcentual', 'created_at', 'updated_at']

    def get_progreso_porcentual(self, obj):
        total = getattr(obj, 'n_fases', None)
        if total is None:
            return LoteProduccionSerializer().get_progreso_porcentual(obj)
        return round(obj.n_fases_cerradas / total * 100, 1) if total else 0.0
