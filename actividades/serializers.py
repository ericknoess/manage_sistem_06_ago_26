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
    """Serializer ligero para mostrar la información básica del operador asignado."""
    class Meta:
        model = Operador
        fields = ['id', 'nombre', 'foto', 'nivel_expertiz']


class ActividadSemanalSerializer(serializers.ModelSerializer):
    # Campos anidados para lectura detallada
    operador_asignado_detalles = OperadorSimpleSerializer(source='operador_asignado', read_only=True)
    equipos_detalles = EquipoSerializer(source='equipos', many=True, read_only=True)
    materiales_detalles = MaterialInsumoSerializer(source='materiales', many=True, read_only=True)

    class Meta:
        model = ActividadSemanal
        fields = [
            'id', 
            'lote_codigo', 
            'titulo', 
            'fecha', 
            'hora_inicio', 
            'hora_fin', 
            'turno_req', 
            'operador_asignado', 
            'operador_asignado_detalles',
            'equipos', 
            'equipos_detalles',
            'materiales', 
            'materiales_detalles',
            'created_at', 
            'updated_at'
        ]