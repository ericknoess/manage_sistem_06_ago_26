from django.contrib import admin

from .models import IndicadorProceso, ParametroProceso, SeccionCaptura, ParametroSeccion, TomaDatos, ValorParametro


@admin.register(ParametroProceso)
class ParametroProcesoAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'nombre', 'unidad', 'tipo_dato', 'formula', 'activo']
    list_filter = ['tipo_dato', 'activo']
    search_fields = ['codigo', 'nombre']


class ParametroSeccionInline(admin.TabularInline):
    model = ParametroSeccion
    extra = 0


@admin.register(SeccionCaptura)
class SeccionCapturaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'operacion', 'frecuencia', 'cada_horas', 'muestra_fisica']
    inlines = [ParametroSeccionInline]


class SoloLecturaAdmin(admin.ModelAdmin):
    """Los datos capturados se consultan aquí pero se registran y corrigen solo desde la aplicación (con bitácora)."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TomaDatos)
class TomaDatosAdmin(SoloLecturaAdmin):
    list_display = ['id', 'fase', 'momento', 'adicional', 'registrado_por_nombre']
    list_filter = ['adicional']


@admin.register(ValorParametro)
class ValorParametroAdmin(SoloLecturaAdmin):
    list_display = ['id', 'toma', 'parametro', 'valor_numero', 'valor_texto', 'calculado', 'vigente', 'fuera_especificacion']
    list_filter = ['vigente', 'calculado', 'fuera_especificacion']


@admin.register(IndicadorProceso)
class IndicadorProcesoAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'nombre', 'proceso', 'tipo', 'parametro', 'etapa', 'activo']
    list_filter = ['tipo', 'activo', 'proceso']
