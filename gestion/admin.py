from django.contrib import admin

from .models import Proyecto, Tarea


@admin.register(Proyecto)
class ProyectoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'responsable', 'estado', 'actualizado_en')
    list_filter = ('estado',)
    search_fields = ('nombre',)


@admin.register(Tarea)
class TareaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'proyecto', 'responsable', 'inicio', 'fin', 'avance')
    list_filter = ('proyecto',)
    search_fields = ('nombre',)
