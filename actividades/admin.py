# actividades/admin.py

from django.contrib import admin
from .models import Equipo, MaterialInsumo, ActividadSemanal

@admin.register(Equipo)
class EquipoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'tipo', 'activo')
    search_fields = ('id', 'nombre', 'tipo')
    list_filter = ('tipo', 'activo')

@admin.register(MaterialInsumo)
class MaterialInsumoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'stock_controlado', 'activo')
    search_fields = ('id', 'nombre')
    list_filter = ('stock_controlado', 'activo')

@admin.register(ActividadSemanal)
class ActividadSemanalAdmin(admin.ModelAdmin):
    list_display = ('lote_codigo', 'titulo', 'fecha', 'hora_inicio', 'hora_fin', 'turno_req', 'operador_asignado')
    search_fields = ('lote_codigo', 'titulo')
    list_filter = ('fecha', 'turno_req', 'operador_asignado')
    filter_horizontal = ('equipos', 'materiales')
    date_hierarchy = 'fecha'