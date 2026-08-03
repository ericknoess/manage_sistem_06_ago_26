# roster/serializers.py

from rest_framework import serializers
from .models import Cuadrilla, Operador, TurnoDia

class TurnoDiaSerializer(serializers.ModelSerializer):
    """
    Serializer para el modelo TurnoDia.
    Gestiona la representación JSON de los turnos operacionales.
    """
    class Meta:
        model = TurnoDia
        fields = ['id', 'operador', 'fecha', 'codigo_turno']


class OperadorSerializer(serializers.ModelSerializer):
    """
    Serializer para Operadores. Incluye dinámicamente los turnos
    filtrados por mes y año según los query params de la petición GET.
    """
    turnos = serializers.SerializerMethodField()

    class Meta:
        model = Operador
        fields = ['id', 'nombre', 'cuadrilla', 'activo', 'turnos']

    def get_turnos(self, obj):
        """
        Filtra los turnos del operador basándose en el mes y año 
        enviados en la URL (?month=X&year=YYYY).
        """
        request = self.context.get('request')
        if request:
            month = request.query_params.get('month')
            year = request.query_params.get('year')
            turnos_qs = obj.turnos.all()
            if month and year:
                turnos_qs = turnos_qs.filter(fecha__month=month, fecha__year=year)
            return TurnoDiaSerializer(turnos_qs, many=True).data
        return []


class CuadrillaSerializer(serializers.ModelSerializer):
    """
    Serializer para Cuadrillas, anidando sus operadores y turnos correspondientes.
    """
    operadores = OperadorSerializer(many=True, read_only=True)

    class Meta:
        model = Cuadrilla
        fields = ['id', 'identificador', 'nombre', 'activa', 'operadores']