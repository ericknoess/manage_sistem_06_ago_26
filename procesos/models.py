# procesos/models.py

from django.db import models
from actividades.models import Equipo, MaterialInsumo
from roster.models import RolOperador, Operador

# ==============================================================================
# 1. MODELOS MAESTROS (PLANTILLAS Y DISEÑO DEL BIOPROCESO)
# ==============================================================================

class ProcesoMaestro(models.Model):
    """
    Plantilla o receta maestra que define una ruta de proceso biotecnológico completa.
    """
    nombre = models.CharField(max_length=200, unique=True, help_text="Nombre del bioproceso / Protocolo (Ej: Fermentación Fed-Batch)")
    descripcion = models.TextField(blank=True, null=True, help_text="Descripción técnica de la receta")
    activo = models.BooleanField(default=True, help_text="Disponible para instanciación en lotes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[Proceso] {self.nombre}"


class EtapaProceso(models.Model):
    """
    Agrupador lógico (Nivel 2 - ISA-88) que permite organizar las 
    Operaciones/Actividades en bloques visuales y funcionales.
    """
    proceso = models.ForeignKey(
        ProcesoMaestro, 
        on_delete=models.CASCADE, 
        related_name='etapas',
        help_text="Proceso maestro al que pertenece esta etapa"
    )
    nombre = models.CharField(max_length=200, help_text="Nombre de la Etapa")
    orden = models.PositiveIntegerField(default=0, help_text="Orden de secuencia lógica para visualización")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Etapa de Proceso"
        verbose_name_plural = "Etapas de Procesos"
        ordering = ['proceso', 'orden']

    def __str__(self):
        return f"{self.proceso.nombre} | Etapa: {self.nombre}"


class OperacionProceso(models.Model):
    """
    Define cada operación o actividad granular (CPM) que compone una ruta de proceso maestro.
    """
    TIPO_OPERACION_CHOICES = [
        ('ACTIVA', '⚙️ Activa (Operador en planta)'),
        ('INCUBACION', '🧫 Incubación / Biomasa (Pasiva)'),
    ]

    TIPO_DEPENDENCIA_CHOICES = [
        ('FS', 'Fin a Inicio (Finish-to-Start)'),
        ('SS', 'Inicio a Inicio (Start-to-Start)'),
        ('OFFSET', 'Desfase Temporal Fijo (Offset de Calendario)'),
    ]

    proceso = models.ForeignKey(
        ProcesoMaestro, 
        on_delete=models.CASCADE, 
        related_name='operaciones',
        help_text="Proceso maestro al que pertenece esta operación"
    )
    
    etapa = models.ForeignKey(
        EtapaProceso,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='operaciones',
        help_text="Etapa lógica a la que pertenece esta actividad (Opcional)"
    )

    identificador_paso = models.CharField(max_length=20, help_text="Identificador único del paso (Ej: T1, T2)")
    nombre = models.CharField(max_length=200, help_text="Nombre de la operación o fase")
    
    orden = models.PositiveIntegerField(default=0, help_text="Orden de secuencia visual y lógica de la actividad")

    tipo_operacion = models.CharField(max_length=20, choices=TIPO_OPERACION_CHOICES, default='ACTIVA')
    duracion_horas = models.FloatField(help_text="Duración estimada en horas")
    
    frecuencia_muestreo_horas = models.PositiveIntegerField(default=0, help_text="Frecuencia de muestreo cíclico en horas")
    duracion_muestreo_horas = models.FloatField(default=0.0, help_text="Duración en horas de cada evento de muestreo")
    ops_muestreo = models.PositiveIntegerField(default=1, help_text="Número total de operadores requeridos para cada muestreo")
    
    predecesora = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='sucesoras',
        help_text="Operación predecesora inmediata en la ruta crítica"
    )
    tipo_dependencia = models.CharField(max_length=10, choices=TIPO_DEPENDENCIA_CHOICES, default='FS', help_text="Regla lógica de dependencia")
    desfase_horas = models.FloatField(default=0, help_text="Holgura o anticipación en horas respecto a la predecesora")

    personal_requerido = models.PositiveIntegerField(default=1, help_text="Número total de operadores requeridos")
    tipo_equipo_requerido = models.CharField(
        max_length=100, 
        default='N/A', 
        help_text="Categoría o tipo de equipo requerido"
    )
    materiales_requeridos = models.ManyToManyField(
        MaterialInsumo, 
        blank=True, 
        related_name='operaciones_proceso',
        help_text="Insumos o materiales consumibles necesarios"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Operación de Proceso"
        verbose_name_plural = "Operaciones de Procesos"
        ordering = ['proceso', 'orden', 'id']
        # --- [NUEVO] RESTRICCIÓN DE UNICIDAD COMPUESTA ---
        constraints = [
            models.UniqueConstraint(
                fields=['proceso', 'identificador_paso'], 
                name='unique_paso_per_proceso'
            )
        ]

    def __str__(self):
        return f"{self.proceso.nombre} | {self.identificador_paso}: {self.nombre} ({self.duracion_horas}h)"


class RequerimientoPersonalFase(models.Model):
    operacion = models.ForeignKey(
        OperacionProceso,
        on_delete=models.CASCADE,
        related_name='requerimientos_rol',
        verbose_name="Operación / Fase CPM"
    )
    rol = models.ForeignKey(
        RolOperador,
        on_delete=models.RESTRICT,
        related_name='requerido_en_operaciones',
        verbose_name="Rol / Competencia Requerida"
    )
    cantidad = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "Requerimiento de Personal"
        verbose_name_plural = "Requerimientos de Personal"
        unique_together = ('operacion', 'rol') 

    def __str__(self):
        return f"{self.cantidad}x {self.rol.nombre} para [{self.operacion.identificador_paso}]"


class LoteProduccion(models.Model):
    ESTADO_LOTE_CHOICES = [
        ('PLANEADO', 'Planeado'),
        ('EN_PROGRESO', 'En Progreso'),
        ('COMPLETADO', 'Completado'),
        ('DESVIACION', 'Desviación / Detenido'),
        ('ABORTADO', 'Abortado / Cancelado'),
    ]

    identificador_lote = models.CharField(max_length=100, unique=True)
    proceso_maestro = models.ForeignKey(
        ProcesoMaestro, 
        on_delete=models.RESTRICT,
        related_name='lotes_instanciados'
    )
    estado = models.CharField(max_length=20, choices=ESTADO_LOTE_CHOICES, default='PLANEADO')
    fecha_inicio_planeada = models.DateTimeField()
    archivado = models.BooleanField(default=False)
    motivo_aborto = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lote de Producción"
        verbose_name_plural = "Lotes de Producción"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.identificador_lote} [{self.estado}] - {self.proceso_maestro.nombre}"


class FaseLote(models.Model):
    ESTADO_FASE_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('EN_PROGRESO', 'En Progreso'),
        ('COMPLETADA', 'Completada'),
        ('OMITIDA', 'Omitida / Cancelada'),
    ]

    MOTIVO_REPROGRAMACION_CHOICES = [
        ('MANTENIMIENTO', '⚙️ Mantenimiento de Equipo'),
        ('INSUMOS', '📦 Falta / Retraso de Insumos'),
        ('PERSONAL', '👥 Ausentismo / Falta de Personal'),
        ('CALIDAD', '🔬 Desviación de Calidad previa'),
        ('PRODUCCION', '⏳ Retraso acumulado en producción'),
        ('OTRO', '📝 Otro (Especificar en notas)'),
    ]

    lote = models.ForeignKey(LoteProduccion, on_delete=models.CASCADE, related_name='fases')
    operacion_maestra = models.ForeignKey(OperacionProceso, on_delete=models.RESTRICT, related_name='fases_ejecutadas')
    estado = models.CharField(max_length=20, choices=ESTADO_FASE_CHOICES, default='PENDIENTE')
    
    es_subtarea_muestreo = models.BooleanField(default=False)
    indice_muestreo = models.PositiveIntegerField(default=0)
    nombre_tarea_dinamica = models.CharField(max_length=200, null=True, blank=True)
    
    fecha_base_cpm = models.DateField(null=True, blank=True)
    hora_inicio_base_cpm = models.TimeField(null=True, blank=True)
    hora_fin_base_cpm = models.TimeField(null=True, blank=True)

    fecha_programada = models.DateField(null=True, blank=True)
    hora_inicio_programada = models.TimeField(null=True, blank=True)
    hora_fin_programada = models.TimeField(null=True, blank=True)
    
    motivo_reprogramacion = models.CharField(max_length=50, choices=MOTIVO_REPROGRAMACION_CHOICES, null=True, blank=True)
    notas_reprogramacion = models.TextField(null=True, blank=True)

    equipos_asignados = models.ManyToManyField(Equipo, blank=True, related_name='fases_asignadas')
    materiales_asignados = models.ManyToManyField(MaterialInsumo, blank=True, related_name='fases_asignadas')

    fecha_inicio_real = models.DateTimeField(null=True, blank=True)
    fecha_fin_real = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Fase de Lote"
        verbose_name_plural = "Fases de Lote"
        ordering = ['operacion_maestra__identificador_paso', 'indice_muestreo']

    def __str__(self):
        nombre_mostrar = self.nombre_tarea_dinamica if self.es_subtarea_muestreo else self.operacion_maestra.nombre
        return f"Lote: {self.lote.identificador_lote} | Fase: {nombre_mostrar} ({self.estado})"


class AsignacionFaseOperador(models.Model):
    fase_lote = models.ForeignKey(FaseLote, on_delete=models.CASCADE, related_name='operadores_asignados')
    operador = models.ForeignKey(Operador, on_delete=models.RESTRICT, related_name='fases_lote_ejecutadas')
    rol_ejercido = models.ForeignKey(RolOperador, on_delete=models.RESTRICT)
    horas_invertidas = models.FloatField(default=0.0)
    asignado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Asignación de Operador a Fase"
        verbose_name_plural = "Asignaciones de Operadores a Fases"
        unique_together = ('fase_lote', 'operador')

    def __str__(self):
        return f"{self.operador.nombre} -> {self.fase_lote.operacion_maestra.nombre} [{self.rol_ejercido.nombre}]"