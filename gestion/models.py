# gestion/models.py — Proyectos, tareas de oficina y tableros Kanban. NO es GMP: sin firma ni bitácora de auditoría;
# cada proyecto lleva un historial simple de cambios y todo se puede editar o borrar.

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models

USUARIO = settings.AUTH_USER_MODEL


class Proyecto(models.Model):
    """Proyecto o tablero de un equipo. Sus tareas son a la vez barras del Gantt y tarjetas del tablero Kanban."""
    ESTADO_CHOICES = [('ACTIVO', 'Activo'), ('PAUSADO', 'En pausa'), ('TERMINADO', 'Terminado'), ('ARCHIVADO', 'Archivado')]

    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    color = models.CharField(max_length=7, default='#2a78d6')
    responsable = models.ForeignKey(USUARIO, on_delete=models.PROTECT, related_name='proyectos_a_cargo')
    miembros = models.ManyToManyField(USUARIO, blank=True, related_name='proyectos')
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='ACTIVO')
    base_guardada_en = models.DateTimeField(null=True, blank=True, help_text="Cuándo se guardó la línea base del Gantt")
    # Papelera: borrar un proyecto lo manda aquí (se puede recuperar); solo desde la papelera se elimina de verdad
    en_papelera_desde = models.DateTimeField(null=True, blank=True)
    en_papelera_por = models.CharField(max_length=150, blank=True)
    creado_por = models.ForeignKey(USUARIO, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-actualizado_en']

    def __str__(self):
        return self.nombre


class Columna(models.Model):
    """Columna del tablero Kanban. Las tarjetas en una columna final cuentan como terminadas (100 %)."""
    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE, related_name='columnas')
    nombre = models.CharField(max_length=60)
    orden = models.PositiveIntegerField(default=0)
    es_final = models.BooleanField(default=False)
    limite = models.PositiveIntegerField(null=True, blank=True, help_text="Máximo de tarjetas (límite WIP); vacío = sin límite")

    class Meta:
        ordering = ['orden', 'id']

    def __str__(self):
        return f"{self.proyecto} · {self.nombre}"


class Etiqueta(models.Model):
    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE, related_name='etiquetas')
    nombre = models.CharField(max_length=40)
    color = models.CharField(max_length=7, default='#64748b')

    class Meta:
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Tarea(models.Model):
    """
    Tarea del proyecto. Con subtareas es una tarea resumen: sus fechas y avance salen de sus hijas y no aparece en el
    tablero. Las fechas son días (inicio y fin incluidos) y la duración se cuenta en días hábiles (lunes a viernes).
    """
    PRIORIDAD_CHOICES = [('BAJA', 'Baja'), ('MEDIA', 'Media'), ('ALTA', 'Alta'), ('URGENTE', 'Urgente')]

    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE, related_name='tareas')
    padre = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='subtareas')
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    responsable = models.ForeignKey(USUARIO, on_delete=models.SET_NULL, null=True, blank=True, related_name='tareas_oficina')
    columna = models.ForeignKey(Columna, on_delete=models.SET_NULL, null=True, blank=True, related_name='tareas')
    orden_columna = models.PositiveIntegerField(default=0)
    orden = models.PositiveIntegerField(default=0, help_text="Orden en la lista y el Gantt (entre hermanas)")
    inicio = models.DateField(null=True, blank=True)
    fin = models.DateField(null=True, blank=True)
    es_hito = models.BooleanField(default=False)
    avance = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(100)])
    prioridad = models.CharField(max_length=8, choices=PRIORIDAD_CHOICES, default='MEDIA')
    etiquetas = models.ManyToManyField(Etiqueta, blank=True, related_name='tareas')
    base_inicio = models.DateField(null=True, blank=True)
    base_fin = models.DateField(null=True, blank=True)
    completada_en = models.DateTimeField(null=True, blank=True)
    creado_por = models.ForeignKey(USUARIO, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['orden', 'id']
        indexes = [models.Index(fields=['responsable', 'completada_en'], name='tarea_resp_completa_idx')]

    def __str__(self):
        return self.nombre


class Dependencia(models.Model):
    """Fin a inicio: la sucesora empieza el día hábil siguiente al fin de la predecesora, más `desfase_dias` hábiles."""
    predecesora = models.ForeignKey(Tarea, on_delete=models.CASCADE, related_name='dependencias_sucesoras')
    sucesora = models.ForeignKey(Tarea, on_delete=models.CASCADE, related_name='dependencias_predecesoras')
    desfase_dias = models.IntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['predecesora', 'sucesora'], name='dependencia_unica')]


class ElementoChecklist(models.Model):
    tarea = models.ForeignKey(Tarea, on_delete=models.CASCADE, related_name='checklist')
    texto = models.CharField(max_length=300)
    hecho = models.BooleanField(default=False)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['orden', 'id']


class Comentario(models.Model):
    tarea = models.ForeignKey(Tarea, on_delete=models.CASCADE, related_name='comentarios')
    autor = models.ForeignKey(USUARIO, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    autor_nombre = models.CharField(max_length=150)
    texto = models.TextField()
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['creado_en', 'id']


class Historial(models.Model):
    """
    Historial de cambios del proyecto: quién, cuándo, qué y {campo: [antes, después]}. No es la bitácora GxP.
    `estado_previo` es la foto del proyecto justo antes del cambio (se conserva en los últimos cambios): con ella se
    deshace el cambio o se regresa el proyecto a ese punto. Deshacer y regresar también quedan aquí.
    """
    TIPO_CHOICES = [('CAMBIO', 'Cambio'), ('DESHACER', 'Deshacer'), ('RESTAURAR', 'Restaurar')]
    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE, related_name='historial')
    tarea = models.ForeignKey(Tarea, on_delete=models.SET_NULL, null=True, blank=True, related_name='historial')
    tarea_nombre = models.CharField(max_length=200, blank=True)
    usuario = models.ForeignKey(USUARIO, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    usuario_nombre = models.CharField(max_length=150)
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    descripcion = models.CharField(max_length=300)
    cambios = models.JSONField(default=dict, blank=True)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='CAMBIO')
    estado_previo = models.JSONField(null=True, blank=True)
    deshecho = models.BooleanField(default=False, help_text="Se deshizo (o se regresó el proyecto a antes de este cambio)")
    deshace = models.JSONField(default=list, blank=True, help_text="Ids de los cambios que esta acción marcó como deshechos")

    class Meta:
        ordering = ['-fecha', '-id']


class VersionProyecto(models.Model):
    """Foto completa del proyecto (tareas, columnas, etiquetas, dependencias, checklist y comentarios) para restaurarlo."""
    proyecto = models.ForeignKey(Proyecto, on_delete=models.CASCADE, related_name='versiones')
    numero = models.PositiveIntegerField()
    nombre = models.CharField(max_length=200)
    automatica = models.BooleanField(default=False)
    datos = models.JSONField()
    resumen = models.JSONField(default=dict, blank=True)
    creado_por = models.ForeignKey(USUARIO, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    creado_por_nombre = models.CharField(max_length=150)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-numero']
        constraints = [models.UniqueConstraint(fields=['proyecto', 'numero'], name='version_proyecto_unica')]
