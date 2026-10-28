# auditoria/models.py

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models


class RegistroAuditoria(models.Model):
    """
    Bitácora GxP (audit trail): quién hizo qué, cuándo, por qué y qué valores cambiaron.
    Solo se agregan registros; no se editan ni se borran (ver save/delete).
    Los nombres se guardan también como texto para que el registro no cambie si después
    se renombra o se desactiva al usuario, al operador o al lote.
    """
    CATEGORIA_CHOICES = [
        ('LOTE', 'Lote'),
        ('FASE', 'Fase de lote'),
        ('ASIGNACION', 'Asignación de personal'),
        ('MATERIAL_LOTE', 'Material de lote'),
        ('EQUIPO_LOTE', 'Equipo de lote'),
        ('DATOS_PROCESO', 'Datos de proceso'),
        ('EVENTO', 'Evento GMP'),
        ('RECETA', 'Receta maestra'),
        ('CATALOGO', 'Catálogo'),
        ('ROSTER', 'Roster'),
        ('SESION', 'Sesión'),
    ]

    fecha = models.DateTimeField(auto_now_add=True, db_index=True)

    # Quién: un usuario del sistema o un operador que firmó con su PIN en /mobile/
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='registros_auditoria')
    operador = models.ForeignKey('roster.Operador', on_delete=models.PROTECT, null=True, blank=True, related_name='registros_auditoria')
    actor = models.CharField(max_length=150, help_text="Nombre de quien hizo la acción, tal como era en ese momento")
    roles = models.CharField(max_length=255, blank=True, help_text="Roles del usuario al momento de la acción")
    ip = models.GenericIPAddressField(null=True, blank=True)

    # Qué
    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES, db_index=True)
    accion = models.CharField(max_length=40, db_index=True, help_text="Código de la acción, ej. CREAR, ABORTAR, REPROGRAMAR")
    descripcion = models.CharField(max_length=500)
    objeto_tipo = models.CharField(max_length=60, blank=True)
    objeto_id = models.CharField(max_length=60, blank=True, db_index=True)

    # Contexto de lote para consultar el historial de un lote o una fase
    lote = models.ForeignKey('procesos.LoteProduccion', on_delete=models.SET_NULL, null=True, blank=True, related_name='registros_auditoria')
    lote_codigo = models.CharField(max_length=100, blank=True, db_index=True)
    fase = models.ForeignKey('procesos.FaseLote', on_delete=models.SET_NULL, null=True, blank=True, related_name='registros_auditoria')

    # Por qué y qué cambió: {"campo": [antes, después]}
    motivo = models.TextField(blank=True)
    cambios = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Registro de auditoría"
        verbose_name_plural = "Bitácora de auditoría"
        ordering = ['-fecha', '-id']
        indexes = [models.Index(fields=['categoria', 'fecha'])]

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionDenied("La bitácora de auditoría no se puede modificar.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("La bitácora de auditoría no se puede borrar.")

    def __str__(self):
        return f"{self.fecha:%Y-%m-%d %H:%M} · {self.actor} · {self.descripcion}"


class FirmaElectronica(models.Model):
    """
    Firma electrónica (21 CFR Part 11) ligada a un registro de la bitácora: nombre de quien firma,
    fecha y hora, y significado de la firma. Se captura volviendo a pedir la contraseña (o el PIN
    en la terminal). Como la bitácora, no se edita ni se borra.
    """
    METODO_CHOICES = [('CONTRASENA', 'Contraseña'), ('PIN', 'PIN de operador')]

    registro = models.OneToOneField(RegistroAuditoria, on_delete=models.PROTECT, related_name='firma')
    fecha = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='firmas')
    operador = models.ForeignKey('roster.Operador', on_delete=models.PROTECT, null=True, blank=True, related_name='firmas')
    nombre_firmante = models.CharField(max_length=150)
    significado = models.CharField(max_length=200, help_text="Qué se afirma al firmar, ej. 'Ejecución completada y verificada'")
    metodo = models.CharField(max_length=12, choices=METODO_CHOICES)
    comentario = models.TextField(blank=True)

    class Meta:
        verbose_name = "Firma electrónica"
        verbose_name_plural = "Firmas electrónicas"
        ordering = ['-fecha']

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionDenied("Una firma electrónica no se puede modificar.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Una firma electrónica no se puede borrar.")

    def __str__(self):
        return f"{self.nombre_firmante} · {self.significado} · {self.fecha:%Y-%m-%d %H:%M}"
