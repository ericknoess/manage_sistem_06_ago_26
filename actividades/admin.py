# actividades/admin.py

from django.contrib import admin
from .models import Equipo, MaterialInsumo, ActividadSemanal, TipoEquipo

@admin.register(TipoEquipo)
class TipoEquipoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'activo')
    search_fields = ('codigo', 'nombre')

@admin.register(Equipo)
class EquipoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'tipo', 'area', 'estado', 'calibracion_vence', 'activo')
    search_fields = ('id', 'nombre', 'tipo__nombre', 'area')
    list_filter = ('tipo', 'estado', 'activo')

@admin.register(MaterialInsumo)
class MaterialInsumoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'categoria', 'unidad_medida', 'condicion_almacenamiento', 'codigo_erp', 'activo')
    search_fields = ('id', 'nombre', 'codigo_erp', 'proveedor')
    list_filter = ('categoria', 'condicion_almacenamiento', 'stock_controlado', 'activo')

@admin.register(ActividadSemanal)
class ActividadSemanalAdmin(admin.ModelAdmin):
    list_display = ('lote_codigo', 'titulo', 'fecha', 'hora_inicio', 'hora_fin', 'turno_req', 'personal_requerido', 'get_operadores')
    search_fields = ('lote_codigo', 'titulo')
    list_filter = ('fecha', 'turno_req')
    filter_horizontal = ('operadores_asignados', 'equipos', 'materiales')
    date_hierarchy = 'fecha'

    # Tablero retirado: se conserva como histórico GxP, sin altas, cambios ni borrado.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_operadores(self, obj):
        return ", ".join([op.nombre for op in obj.operadores_asignados.all()])
    get_operadores.short_description = 'Operadores Asignados'