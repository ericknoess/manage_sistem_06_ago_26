# actividades/serializers.py

from rest_framework import serializers
from django.utils import timezone

from .models import Equipo, MaterialInsumo, ActividadSemanal, TipoEquipo
from roster.models import Operador

class TipoEquipoSerializer(serializers.ModelSerializer):
    # Equipos registrados y actividades de receta que piden este tipo (anotados en el ViewSet)
    equipos_registrados = serializers.IntegerField(read_only=True, default=None)
    usos_en_recetas = serializers.IntegerField(read_only=True, default=None)

    class Meta:
        model = TipoEquipo
        fields = ['codigo', 'nombre', 'activo', 'equipos_registrados', 'usos_en_recetas']

    def validate_codigo(self, valor):
        valor = valor.strip().upper().replace(' ', '_')
        if self.instance and valor != self.instance.codigo:
            raise serializers.ValidationError("El código de un tipo de equipo no se puede cambiar.")
        return valor


class EquipoSerializer(serializers.ModelSerializer):
    tipo_nombre = serializers.CharField(source='tipo.nombre', read_only=True)
    estado_display = serializers.CharField(source='get_estado_display', read_only=True)
    # Días para el vencimiento de la calibración (negativo si ya venció; None si no aplica)
    dias_calibracion = serializers.SerializerMethodField()
    reservas_vigentes = serializers.IntegerField(read_only=True, default=None)

    class Meta:
        model = Equipo
        fields = ['id', 'nombre', 'tipo', 'tipo_nombre', 'area', 'capacidad', 'estado', 'estado_display',
                  'calibracion_vence', 'dias_calibracion', 'activo', 'reservas_vigentes']

    def get_dias_calibracion(self, obj):
        if not obj.calibracion_vence:
            return None
        return (obj.calibracion_vence - timezone.localdate()).days

    def validate_id(self, valor):
        # El código es la llave primaria y lo referencian las reservas de los lotes: no se renombra
        if self.instance and valor != self.instance.id:
            raise serializers.ValidationError("El código de un equipo no se puede cambiar.")
        return valor.strip()

    def validate_tipo(self, tipo):
        if not tipo.activo and (not self.instance or self.instance.tipo_id != tipo.codigo):
            raise serializers.ValidationError("Ese tipo de equipo está dado de baja.")
        return tipo

class MaterialInsumoSerializer(serializers.ModelSerializer):
    categoria_display = serializers.CharField(source='get_categoria_display', read_only=True)
    condicion_almacenamiento_display = serializers.CharField(source='get_condicion_almacenamiento_display', read_only=True)
    # Cantidad de operaciones de recetas que lo usan (anotada en el ViewSet del catálogo)
    usos_en_recetas = serializers.SerializerMethodField()

    class Meta:
        model = MaterialInsumo
        fields = [
            'id', 'nombre', 'categoria', 'categoria_display', 'unidad_medida', 'codigo_erp', 'proveedor',
            'condicion_almacenamiento', 'condicion_almacenamiento_display', 'stock_controlado', 'activo',
            'usos_en_recetas',
        ]

    def get_usos_en_recetas(self, obj):
        return getattr(obj, 'usos_en_recetas', None)

    def validate_id(self, valor):
        # El código es la llave primaria y lo referencian recetas y lotes: no se renombra
        if self.instance and valor != self.instance.id:
            raise serializers.ValidationError("El código de un material no se puede cambiar.")
        return valor.strip()

class OperadorSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Operador
        fields = ['id', 'nombre', 'foto', 'rol']

class ActividadSemanalSerializer(serializers.ModelSerializer):
    # Campos detallados para lectura
    operadores_asignados_detalles = OperadorSimpleSerializer(source='operadores_asignados', many=True, read_only=True)
    equipos_detalles = EquipoSerializer(source='equipos', many=True, read_only=True)
    materiales_detalles = MaterialInsumoSerializer(source='materiales', many=True, read_only=True)

    class Meta:
        model = ActividadSemanal
        fields = [
            'id', 'lote_codigo', 'titulo', 'fecha', 'hora_inicio', 'hora_fin', 
            'turno_req', 'personal_requerido', 'operadores_asignados', 
            'operadores_asignados_detalles', 'equipos', 'equipos_detalles',
            'materiales', 'materiales_detalles', 'created_at', 'updated_at'
        ]
        extra_kwargs = {
            'operadores_asignados': {'required': False},
            'equipos': {'required': False},
            'materiales': {'required': False},
        }

    # Sobrescribimos el update para asegurar compatibilidad si el frontend envía un ID único
    def update(self, instance, validated_data):
        if 'operadores_asignados' in validated_data:
            instance.operadores_asignados.set(validated_data.pop('operadores_asignados'))
        return super().update(instance, validated_data)