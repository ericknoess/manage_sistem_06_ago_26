# actividades/serializers.py

from rest_framework import serializers
from .models import Equipo, MaterialInsumo, ActividadSemanal
from roster.models import Operador

class EquipoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Equipo
        fields = ['id', 'nombre', 'tipo', 'activo']

class MaterialInsumoSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaterialInsumo
        fields = ['id', 'nombre', 'stock_controlado', 'activo']

class OperadorSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Operador
        fields = ['id', 'nombre', 'foto', 'nivel_expertiz']

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