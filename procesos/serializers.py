# procesos/serializers.py

from rest_framework import serializers
from .models import ProcesoMaestro, OperacionProceso
from actividades.serializers import MaterialInsumoSerializer

class OperacionProcesoSerializer(serializers.ModelSerializer):
    """
    Serializer para las operaciones o fases CPM de un proceso maestro,
    incluyendo soporte para dependencias avanzadas y validación de grafos acíclicos.
    """
    materiales_requeridos_detalles = MaterialInsumoSerializer(source='materiales_requeridos', many=True, read_only=True)

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
            'duracion_muestreo_horas',  # Nuevo campo: Duración exacta del muestreo
            'ops_muestreo',             # Nuevo campo: Operadores requeridos para el muestreo
            'predecesora',
            'tipo_dependencia',
            'desfase_horas',
            'personal_requerido',
            'tipo_equipo_requerido',
            'materiales_requeridos',
            'materiales_requeridos_detalles'
        ]
        extra_kwargs = {
            'materiales_requeridos': {'required': False},
            'predecesora': {'required': False, 'allow_null': True},
            'tipo_dependencia': {'required': False},
            'desfase_horas': {'required': False},
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
                # Si la predecesora evaluada es la misma que la instancia actual, hay ciclo.
                if actual_pred.id == self.instance.id:
                    raise serializers.ValidationError({
                        "predecesora": "⚠️ Referencia circular detectada. La predecesora seleccionada ya depende directa o indirectamente de esta operación."
                    })
                
                # Protección contra ciclos preexistentes en la base de datos (seguridad GxP)
                if actual_pred.id in visitados:
                    break
                
                visitados.add(actual_pred.id)
                actual_pred = actual_pred.predecesora

        return data


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