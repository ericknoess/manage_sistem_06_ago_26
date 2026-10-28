# eventos/admin.py — Consulta de eventos GMP (solo lectura: se reportan, cierran y anulan desde /eventos/).

from django.contrib import admin

from .models import EventoGMP


@admin.register(EventoGMP)
class EventoGMPAdmin(admin.ModelAdmin):
    list_display = ('folio', 'lote', 'tipo', 'titulo', 'estado', 'clasificacion', 'ocurrio_en')
    list_filter = ('estado', 'tipo', 'clasificacion', 'origen')
    search_fields = ('folio', 'titulo', 'lote__identificador_lote', 'numero_desviacion')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
