# eventos/serializers.py — Eventos GMP para la API (solo lectura: los cambios pasan por las acciones del ViewSet).

from rest_framework import serializers

from .models import EventoGMP
from .services import es_quien_reporto, nombre_tarea


class EventoGMPSerializer(serializers.ModelSerializer):
    lote_identificador = serializers.CharField(source='lote.identificador_lote', read_only=True)
    proceso = serializers.IntegerField(source='lote.proceso_maestro_id', read_only=True)
    tarea = serializers.SerializerMethodField()
    tipo_nombre = serializers.CharField(source='get_tipo_display', read_only=True)
    origen_nombre = serializers.CharField(source='get_origen_display', read_only=True)
    estado_nombre = serializers.CharField(source='get_estado_display', read_only=True)
    clasificacion_nombre = serializers.CharField(source='get_clasificacion_display', read_only=True)
    equipo_nombre = serializers.SerializerMethodField()
    dato = serializers.SerializerMethodField()
    firma = serializers.SerializerMethodField()
    reporto_yo = serializers.SerializerMethodField()

    class Meta:
        model = EventoGMP
        fields = ['id', 'folio', 'lote', 'lote_identificador', 'proceso', 'fase', 'tarea', 'tipo', 'tipo_nombre',
                  'origen', 'origen_nombre', 'titulo', 'descripcion', 'accion_inmediata', 'ocurrio_en', 'equipo',
                  'equipo_nombre', 'dato', 'reportado_por_nombre', 'reportado_en', 'estado', 'estado_nombre',
                  'clasificacion', 'clasificacion_nombre', 'numero_desviacion', 'evaluacion', 'motivo_anulacion',
                  'cerrado_por_nombre', 'cerrado_en', 'firma', 'reporto_yo']
        read_only_fields = fields

    def get_tarea(self, obj):
        return nombre_tarea(obj.fase)

    def get_equipo_nombre(self, obj):
        return str(obj.equipo) if obj.equipo_id else ''

    def get_dato(self, obj):
        v = obj.valor
        if v is None:
            return None
        from datos_proceso.services import texto_decimal
        return {'parametro': v.parametro.nombre, 'unidad': v.parametro.unidad, 'valor': texto_decimal(v.valor_numero),
                'limites': v.limites, 'vigente': v.vigente}

    def get_firma(self, obj):
        firma = getattr(obj.registro_cierre, 'firma', None) if obj.registro_cierre_id else None
        if not firma:
            return None
        return {'nombre': firma.nombre_firmante, 'significado': firma.significado, 'fecha': firma.fecha,
                'metodo': firma.get_metodo_display()}

    def get_reporto_yo(self, obj):
        """True si quien consulta reportó el evento (no puede evaluarlo: el front oculta los botones)."""
        quien = self.context.get('quien')
        return bool(quien) and es_quien_reporto(obj, quien[0], quien[1])
