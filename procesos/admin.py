# procesos/admin.py

from django.contrib import admin
from .models import ProcesoMaestro, OperacionProceso

class OperacionProcesoInline(admin.TabularInline):
    """
    Permite gestionar las fases y operaciones CPM directamente dentro de la vista del Proceso Maestro.
    """
    model = OperacionProceso
    extra = 1
    autocomplete_fields = ['predecesora']
    filter_horizontal = ['materiales_requeridos']
    fields = (
        'identificador_paso', 
        'nombre', 
        'tipo_operacion', 
        'duracion_horas', 
        'frecuencia_muestreo_horas', 
        'predecesora', 
        'personal_requerido', 
        'tipo_equipo_requerido', 
        'materiales_requeridos'
    )


@admin.register(ProcesoMaestro)
class ProcesoMaestroAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'activo', 'created_at')
    search_fields = ('nombre', 'descripcion')
    list_filter = ('activo', 'created_at')
    inlines = [OperacionProcesoInline]


@admin.register(OperacionProceso)
class OperacionProcesoAdmin(admin.ModelAdmin):
    list_display = ('proceso', 'identificador_paso', 'nombre', 'tipo_operacion', 'duracion_horas', 'personal_requerido')
    search_fields = ('nombre', 'identificador_paso', 'proceso__nombre')
    list_filter = ('tipo_operacion', 'proceso')
    autocomplete_fields = ['proceso', 'predecesora']
    filter_horizontal = ['materiales_requeridos']