# usuarios/models.py

from django.conf import settings
from django.db import models


class Perfil(models.Model):
    """
    Datos del usuario del sistema que no trae django.contrib.auth.
    Los roles son grupos de Django (ver usuarios/roles.py); los permisos de negocio
    se declaran aquí para tener un solo lugar con todas las acciones controladas.
    """
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='perfil')
    operador = models.OneToOneField(
        'roster.Operador', on_delete=models.SET_NULL, null=True, blank=True, related_name='usuario_sistema',
        help_text="Registro del roster de esta persona, si también aparece ahí (supervisores, jefaturas)."
    )
    puesto = models.CharField(max_length=120, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Perfil de usuario"
        verbose_name_plural = "Perfiles de usuario"
        default_permissions = ()
        permissions = [
            ('instanciar_lote', 'Crear e iniciar lotes'),
            ('abortar_lote', 'Abortar, eliminar y archivar lotes'),
            ('reprogramar_fase', 'Reprogramar fases de lote'),
            ('asignar_personal', 'Asignar operadores y equipos a fases'),
            ('ejecutar_fase', 'Iniciar y completar fases'),
            ('ajustar_material_lote', 'Agregar, ajustar y retirar materiales de un lote'),
            ('editar_receta', 'Crear y editar recetas maestras'),
            ('archivar_receta', 'Archivar y restaurar recetas maestras'),
            ('gestionar_catalogos', 'Gestionar catálogos de materiales y equipos'),
            ('gestionar_roster', 'Gestionar turnos, cuadrillas, operadores e incidencias'),
            ('gestionar_usuarios', 'Gestionar usuarios y roles'),
        ]

    def __str__(self):
        return f"Perfil de {self.usuario.get_username()}"
