# auditoria/serializers.py

from rest_framework import serializers

from .models import FirmaElectronica, RegistroAuditoria


class FirmaElectronicaSerializer(serializers.ModelSerializer):
    metodo_display = serializers.CharField(source='get_metodo_display', read_only=True)

    class Meta:
        model = FirmaElectronica
        fields = ['fecha', 'nombre_firmante', 'significado', 'metodo', 'metodo_display', 'comentario']
        read_only_fields = fields


class RegistroAuditoriaSerializer(serializers.ModelSerializer):
    categoria_display = serializers.CharField(source='get_categoria_display', read_only=True)
    fase_nombre = serializers.SerializerMethodField()
    firma = FirmaElectronicaSerializer(read_only=True)

    class Meta:
        model = RegistroAuditoria
        fields = [
            'id', 'fecha', 'actor', 'roles', 'usuario', 'operador', 'ip',
            'categoria', 'categoria_display', 'accion', 'descripcion', 'objeto_tipo', 'objeto_id',
            'lote', 'lote_codigo', 'fase', 'fase_nombre', 'motivo', 'cambios', 'firma',
        ]
        read_only_fields = fields

    def get_fase_nombre(self, obj):
        if not obj.fase_id:
            return ''
        fase = obj.fase
        nombre = fase.nombre_tarea_dinamica if fase.es_subtarea_muestreo and fase.nombre_tarea_dinamica else fase.operacion_maestra.nombre
        return f"[{fase.operacion_maestra.identificador_paso}] {nombre}"
