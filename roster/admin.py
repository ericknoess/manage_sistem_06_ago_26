# roster/admin.py
from django.contrib import admin
from .models import TipoTurno, Cuadrilla, Operador, TurnoDia, SecuenciaRol, SecuenciaRolDetalle

@admin.register(TipoTurno)
class TipoTurnoAdmin(admin.ModelAdmin):
    """
    Configuración del panel de administración para el catálogo maestro de Tipos de Turno.
    Permite gestionar códigos, nombres y colores corporativos en formato HEX.
    """
    list_display = ('codigo', 'nombre', 'color_fondo', 'color_texto', 'es_descanso', 'activo', 'creado_en')
    list_filter = ('activo', 'es_descanso')
    search_fields = ('codigo', 'nombre')
    list_editable = ('activo', 'es_descanso')


class SecuenciaRolDetalleInline(admin.TabularInline):
    """
    Permite gestionar los detalles (pasos y días de turnos) de una secuencia de rol
    de manera inline dentro del panel de administración principal de SecuenciaRol.
    """
    model = SecuenciaRolDetalle
    extra = 1
    fields = ('orden', 'tipo_turno', 'dias')


@admin.register(SecuenciaRol)
class SecuenciaRolAdmin(admin.ModelAdmin):
    """
    Configuración del panel de administración para el modelo SecuenciaRol.
    Facilita la gestión de plantillas de rotación reutilizables para la carga masiva.
    """
    list_display = ('id', 'nombre', 'descripcion', 'activa', 'creado_en')
    list_filter = ('activa', 'creado_en')
    search_fields = ('nombre', 'descripcion')
    list_editable = ('activa',)
    inlines = [SecuenciaRolDetalleInline]


@admin.register(Cuadrilla)
class CuadrillaAdmin(admin.ModelAdmin):
    """
    Configuración del panel de administración para el modelo Cuadrilla.
    Permite visualizar el nombre, descripción y fecha de creación en formato tabular.
    """
    list_display = ('id', 'identificador', 'nombre', 'descripcion', 'activa', 'creado_en')
    search_fields = ('identificador', 'nombre')
    list_filter = ('activa', 'creado_en')
    list_editable = ('activa',)


@admin.register(Operador)
class OperadorAdmin(admin.ModelAdmin):
    """
    Configuración del panel de administración para el modelo Operador.
    Incluye filtros por cuadrilla y estado activo para auditoría GxP.
    """
    list_display = ('id', 'codigo_empleado', 'nombre', 'cuadrilla', 'nivel_expertiz', 'activo')
    list_filter = ('cuadrilla', 'activo', 'nivel_expertiz')
    search_fields = ('nombre', 'codigo_empleado')
    list_editable = ('activo',)


@admin.register(TurnoDia)
class TurnoDiaAdmin(admin.ModelAdmin):
    """
    Configuración del panel de administración para la matriz de turnos (TurnoDia).
    Permite filtrar por tipo de turno, fecha y cuadrilla del operador.
    """
    list_display = ('id', 'operador', 'fecha', 'tipo_turno', 'actualizado_en')
    list_filter = ('tipo_turno', 'fecha', 'operador__cuadrilla')
    search_fields = ('operador__nombre', 'tipo_turno__codigo')
    date_hierarchy = 'fecha'