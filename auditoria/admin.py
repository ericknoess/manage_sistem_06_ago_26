# auditoria/admin.py — Consulta de la bitácora; el admin no permite agregar, editar ni borrar.

from django.contrib import admin

from .models import RegistroAuditoria


@admin.register(RegistroAuditoria)
class RegistroAuditoriaAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'actor', 'categoria', 'accion', 'descripcion', 'lote_codigo')
    list_filter = ('categoria', 'accion', 'fecha')
    search_fields = ('descripcion', 'actor', 'lote_codigo', 'motivo')
    date_hierarchy = 'fecha'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
