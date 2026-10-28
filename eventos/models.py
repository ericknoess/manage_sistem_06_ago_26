# eventos/models.py — Eventos GMP de un lote (fallas, fuera de especificación, desviaciones de procedimiento…).
#
# Se reportan en planta (web o tablet con PIN) o los crea el sistema (dato fuera de especificación, inicio fuera de
# ventana). Calidad, Supervisión o Jefatura los evalúa y cierra con firma electrónica: clasificación, evaluación y,
# si es desviación, su número en el sistema de calidad. No se borran: un evento registrado por error se anula con motivo
# y firma. Todo cambio pasa por eventos/services.py y queda en la bitácora; aparecen en el informe del lote.

from django.conf import settings
from django.db import models


class EventoGMP(models.Model):
    TIPO_CHOICES = [
        ('FUERA_ESPECIFICACION', 'Resultado fuera de especificación'),
        ('INICIO_FUERA_VENTANA', 'Inicio fuera de ventana'),
        ('FALLA_EQUIPO', 'Falla de equipo'),
        ('MATERIAL', 'Material (faltante, dañado o equivocado)'),
        ('PROCEDIMIENTO', 'Desviación de procedimiento'),
        ('AMBIENTAL', 'Instalaciones o condición ambiental'),
        ('CONTAMINACION', 'Sospecha de contaminación'),
        ('OTRO', 'Otro'),
    ]
    ORIGEN_CHOICES = [('MANUAL', 'Reportado'), ('AUTOMATICO', 'Automático')]
    ESTADO_CHOICES = [('ABIERTO', 'Abierto'), ('CERRADO', 'Cerrado'), ('ANULADO', 'Anulado')]
    CLASIFICACION_CHOICES = [
        ('SIN_IMPACTO', 'Sin impacto en la calidad'),
        ('MENOR', 'Desviación menor'),
        ('MAYOR', 'Desviación mayor'),
        ('CRITICA', 'Desviación crítica'),
    ]

    folio = models.CharField(max_length=20, unique=True, help_text="EV-AAAA-NNNN")
    lote = models.ForeignKey('procesos.LoteProduccion', on_delete=models.PROTECT, related_name='eventos_gmp')
    fase = models.ForeignKey('procesos.FaseLote', on_delete=models.PROTECT, null=True, blank=True, related_name='eventos_gmp')
    tipo = models.CharField(max_length=25, choices=TIPO_CHOICES)
    origen = models.CharField(max_length=10, choices=ORIGEN_CHOICES, default='MANUAL')
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField()
    accion_inmediata = models.TextField(blank=True, default='')
    ocurrio_en = models.DateTimeField(db_index=True)
    # Lo que está ligado al evento (opcional)
    equipo = models.ForeignKey('actividades.Equipo', on_delete=models.PROTECT, null=True, blank=True, related_name='eventos_gmp')
    valor = models.ForeignKey('datos_proceso.ValorParametro', on_delete=models.PROTECT, null=True, blank=True, related_name='eventos_gmp')

    # Quién lo reportó (usuario web u operador con PIN; "Sistema" si no hay ninguno)
    reportado_por_usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                              related_name='eventos_reportados')
    reportado_por_operador = models.ForeignKey('roster.Operador', on_delete=models.PROTECT, null=True, blank=True,
                                               related_name='eventos_reportados')
    reportado_por_nombre = models.CharField(max_length=150)
    reportado_en = models.DateTimeField(auto_now_add=True)

    # Evaluación y cierre (o anulación), con su registro firmado en la bitácora
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='ABIERTO', db_index=True)
    clasificacion = models.CharField(max_length=12, choices=CLASIFICACION_CHOICES, blank=True, default='')
    numero_desviacion = models.CharField(max_length=50, blank=True, default='',
                                         help_text="Número de la desviación en el sistema de calidad")
    evaluacion = models.TextField(blank=True, default='')
    motivo_anulacion = models.TextField(blank=True, default='')
    cerrado_por_usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                            related_name='eventos_cerrados')
    cerrado_por_nombre = models.CharField(max_length=150, blank=True, default='')
    cerrado_en = models.DateTimeField(null=True, blank=True)
    registro_cierre = models.ForeignKey('auditoria.RegistroAuditoria', on_delete=models.PROTECT, null=True, blank=True,
                                        related_name='+', help_text="Registro firmado del cierre o la anulación")

    class Meta:
        verbose_name = "Evento GMP"
        verbose_name_plural = "Eventos GMP"
        ordering = ['-ocurrio_en', '-id']
        indexes = [models.Index(fields=['lote', 'estado'])]

    def __str__(self):
        return f"{self.folio} · {self.lote.identificador_lote} · {self.titulo}"
