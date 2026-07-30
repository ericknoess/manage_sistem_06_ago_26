from rest_framework import serializers
from .models import Cuadrilla, Operador, TurnoDia

class TurnoDiaSerializer(serializers.ModelSerializer):
    class Meta:
        model = TurnoDia
        fields = ['id', 'fecha', 'codigo_turno', 'operador']

    def validate_codigo_turno(self, value):
        """
        Valida que el código del turno pertenezca a la lista autorizada.
        """
        codigos_permitidos = ['M', 'T', 'N', 'TR', 'OFF', 'INC', 'F']
        value_upper = value.upper()
        
        if value_upper not in codigos_permitidos:
            raise serializers.ValidationError(
                f"El código '{value}' no es válido. Los permitidos son: {', '.join(codigos_permitidos)}"
            )
        
        return value_upper

class OperadorSerializer(serializers.ModelSerializer):
    turnos = TurnoDiaSerializer(many=True, read_only=True)

    class Meta:
        model = Operador
        fields = ['id', 'nombre', 'activo', 'turnos']

class CuadrillaSerializer(serializers.ModelSerializer):
    operadores = OperadorSerializer(many=True, read_only=True)

    class Meta:
        model = Cuadrilla
        fields = ['id', 'identificador', 'nombre', 'activa', 'operadores']

class TurnoDiaUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TurnoDia
        fields = ['codigo_turno']

    def validate_codigo_turno(self, value):
        """
        Reutilizamos la lógica de validación para actualizaciones parciales.
        """
        codigos_permitidos = ['M', 'T', 'N', 'TR', 'OFF', 'INC', 'F']
        value_upper = value.upper()
        
        if value_upper not in codigos_permitidos:
            raise serializers.ValidationError(
                f"El código '{value}' no es válido. Los permitidos son: {', '.join(codigos_permitidos)}"
            )
        return value_upper