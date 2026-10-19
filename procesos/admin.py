# procesos/admin.py

from django.contrib import admin
from .models import ProcesoMaestro, OperacionProceso, RequerimientoPersonalFase, MaterialOperacion

class RequerimientoPersonalFaseInline(admin.TabularInline):
    """
    Permite gestionar de forma anidada (inline) los roles y cantidades de personal 
    requeridos directamente dentro de la vista de administración de una Operación/Fase.
    """
    model = RequerimientoPersonalFase
    extra = 1
    autocomplete_fields = ['rol']


class MaterialOperacionInline(admin.TabularInline):
    """Materiales que consume la operación, con cantidad y anticipación."""
    model = MaterialOperacion
    extra = 1
    autocomplete_fields = ['material']


@admin.register(ProcesoMaestro)
class ProcesoMaestroAdmin(admin.ModelAdmin):
    """
    Panel de administración para la gestión de recetas maestras (templates de bioprocesos).
    """
    list_display = ('id', 'nombre', 'activo', 'created_at', 'updated_at')
    list_filter = ('activo', 'created_at')
    search_fields = ('nombre', 'descripcion')
    list_editable = ('activo',)
    date_hierarchy = 'created_at'


@admin.register(OperacionProceso)
class OperacionProcesoAdmin(admin.ModelAdmin):
    """
    Panel de administración para las operaciones (fases CPM) que componen un proceso maestro.
    Integra el inline para asignar perfiles de personal basados en competencias (Skills).
    """
    list_display = (
        'id', 
        'proceso', 
        'identificador_paso', 
        'nombre', 
        'tipo_operacion', 
        'duracion_horas', 
        'personal_requerido', 
        'tipo_equipo_requerido'
    )
    list_filter = ('tipo_operacion', 'tipo_dependencia', 'proceso')
    search_fields = ('identificador_paso', 'nombre', 'proceso__nombre')
    autocomplete_fields = ['proceso', 'predecesora']
    inlines = [RequerimientoPersonalFaseInline, MaterialOperacionInline]