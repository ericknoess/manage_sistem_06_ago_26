# roster/admin.py
from django.contrib import admin
from .models import Cuadrilla, Operador, TurnoDia

@admin.register(Cuadrilla)
class CuadrillaAdmin(admin.ModelAdmin):
    """
    Configuración del panel de administración para el modelo Cuadrilla.
    Permite visualizar el nombre, descripción y fecha de creación en formato tabular.
    """
    list_display = ('id', 'nombre', 'descripcion', 'created_at')
    search_fields = ('nombre',)
    list_filter = ('created_at',)


@admin.register(Operador)
class OperadorAdmin(admin.ModelAdmin):
    """
    Configuración del panel de administración para el modelo Operador.
    Incluye filtros por cuadrilla y estado activo para auditoría GxP.
    """
    list_display = ('id', 'nombre', 'codigo_empleado', 'cuadrilla', 'activo')
    list_filter = ('cuadrilla', 'activo')
    search_fields = ('nombre', 'codigo_empleado')
    list_editable = ('activo',)


@admin.register(TurnoDia)
class TurnoDiaAdmin(admin.ModelAdmin):
    """
    Configuración del panel de administración para la matriz de turnos (TurnoDia).
    Permite filtrar por código de turno, fecha y cuadrilla del operador.
    """
    list_display = ('id', 'operador', 'fecha', 'codigo_turno', 'updated_at')
    list_filter = ('codigo_turno', 'fecha', 'operador__cuadrilla')
    search_fields = ('operador__nombre', 'codigo_turno')
    date_hierarchy = 'fecha'