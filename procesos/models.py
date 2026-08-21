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


class OperacionProceso(models.Model):
    """
    Define cada operación o fase (CPM) que compone una ruta de proceso maestro,
    incluyendo su duración, tipo, dependencias avanzadas con desfase y requerimientos GxP.
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
    identificador_paso = models.CharField(max_length=20, help_text="Identificador único del paso (Ej: T1, T2)")
    nombre = models.CharField(max_length=200, help_text="Nombre de la operación o fase")
    tipo_operacion = models.CharField(max_length=20, choices=TIPO_OPERACION_CHOICES, default='ACTIVA')
    duracion_horas = models.FloatField(help_text="Duración estimada en horas")
    
    # Parámetros para operaciones de incubación / pasivas (Generador de Muestreos)
    frecuencia_muestreo_horas = models.PositiveIntegerField(default=0, help_text="Frecuencia de muestreo cíclico en horas (0 si no aplica)")
    duracion_muestreo_horas = models.FloatField(default=0.0, help_text="Duración en horas de cada evento de muestreo")
    ops_muestreo = models.PositiveIntegerField(default=1, help_text="Número total de operadores requeridos para cada muestreo")
    
    # Dependencia CPM Avanzada con Desfase
    predecesora = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='sucesoras',
        help_text="Operación predecesora inmediata en la ruta crítica"
    )
    tipo_dependencia = models.CharField(max_length=10, choices=TIPO_DEPENDENCIA_CHOICES, default='FS', help_text="Regla lógica de dependencia")
    desfase_horas = models.FloatField(default=0, help_text="Holgura o anticipación en horas respecto a la predecesora (Ej: -24 para 1 día antes)")

    # Requerimientos Técnicos y de Recursos (GxP)
    personal_requerido = models.PositiveIntegerField(default=1, help_text="Número total de operadores requeridos (Se migrará a requerimientos específicos por rol)")
    tipo_equipo_requerido = models.CharField(
        max_length=100, 
        default='N/A', 
        help_text="Categoría o tipo de equipo requerido (Ej: Biorreactor, Autoclave, Centrífuga)"
    )
    materiales_requeridos = models.ManyToManyField(
        MaterialInsumo, 
        blank=True, 
        related_name='operaciones_proceso',
        help_text="Insumos o materiales consumibles necesarios para la fase"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.proceso.nombre} | {self.identificador_paso}: {self.nombre} ({self.duracion_horas}h)"


class RequerimientoPersonalFase(models.Model):
    """
    Permite definir qué cantidad de operadores de un nivel específico (Rol) 
    se necesitan para una operación concreta.
    """
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
    cantidad = models.PositiveIntegerField(
        default=1,
        help_text="Cantidad de operadores con este rol que deben ser asignados"
    )

    class Meta:
        verbose_name = "Requerimiento de Personal"
        verbose_name_plural = "Requerimientos de Personal"
        unique_together = ('operacion', 'rol') 

    def __str__(self):
        return f"{self.cantidad}x {self.rol.nombre} para [{self.operacion.identificador_paso}]"


# ==============================================================================
# 2. MODELOS TRANSACCIONALES (EJECUCIÓN DE LOTE Y EBR - ELECTRONIC BATCH RECORD)
# ==============================================================================

class LoteProduccion(models.Model):
    """
    Instancia física a manufacturar basada en una receta maestra.
    """
    ESTADO_LOTE_CHOICES = [
        ('PLANEADO', 'Planeado'),
        ('EN_PROGRESO', 'En Progreso'),
        ('COMPLETADO', 'Completado'),
        ('DESVIACION', 'Desviación / Detenido'),
    ]

    identificador_lote = models.CharField(max_length=100, unique=True, help_text="ID oficial del Lote (Ej: LOTE-EPO-2026X)")
    proceso_maestro = models.ForeignKey(
        ProcesoMaestro, 
        on_delete=models.RESTRICT,
        related_name='lotes_instanciados'
    )
    estado = models.CharField(max_length=20, choices=ESTADO_LOTE_CHOICES, default='PLANEADO')
    
    # MODIFICACIÓN: Cambiado de DateField a DateTimeField para incluir hora exacta
    fecha_inicio_planeada = models.DateTimeField(help_text="Fecha y hora estimada o programada de inicio")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lote de Producción"
        verbose_name_plural = "Lotes de Producción"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.identificador_lote} [{self.estado}] - {self.proceso_maestro.nombre}"


class FaseLote(models.Model):
    """
    Instancia individual de una OperacionProceso correspondiente a un Lote específico.
    Registra los tiempos reales de ejecución.
    """
    ESTADO_FASE_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('EN_PROGRESO', 'En Progreso'),
        ('COMPLETADA', 'Completada'),
        ('OMITIDA', 'Omitida / Cancelada'),
    ]

    lote = models.ForeignKey(LoteProduccion, on_delete=models.CASCADE, related_name='fases')
    operacion_maestra = models.ForeignKey(OperacionProceso, on_delete=models.RESTRICT, related_name='fases_ejecutadas')
    estado = models.CharField(max_length=20, choices=ESTADO_FASE_CHOICES, default='PENDIENTE')
    
    fecha_inicio_real = models.DateTimeField(null=True, blank=True, help_text="Timestamp real de inicio de la tarea")
    fecha_fin_real = models.DateTimeField(null=True, blank=True, help_text="Timestamp real de fin de la tarea")

    class Meta:
        verbose_name = "Fase de Lote"
        verbose_name_plural = "Fases de Lote"
        unique_together = ('lote', 'operacion_maestra')
        ordering = ['operacion_maestra__identificador_paso']

    def __str__(self):
        return f"Lote: {self.lote.identificador_lote} | Fase: {self.operacion_maestra.nombre} ({self.estado})"


class AsignacionFaseOperador(models.Model):
    """
    Registro GxP inmutable que vincula a un operador real del Roster con una fase de un lote,
    especificando qué competencia/rol ejerció durante dicha tarea.
    """
    fase_lote = models.ForeignKey(FaseLote, on_delete=models.CASCADE, related_name='operadores_asignados')
    operador = models.ForeignKey(Operador, on_delete=models.RESTRICT, related_name='fases_lote_ejecutadas')
    rol_ejercido = models.ForeignKey(
        RolOperador, 
        on_delete=models.RESTRICT, 
        help_text="La competencia bajo la cual se asignó al operador a esta tarea"
    )
    horas_invertidas = models.FloatField(default=0.0, help_text="Horas reales registradas por el operador en esta fase")
    asignado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Asignación de Operador a Fase"
        verbose_name_plural = "Asignaciones de Operadores a Fases"
        unique_together = ('fase_lote', 'operador')

    def __str__(self):
        return f"{self.operador.nombre} -> {self.fase_lote.operacion_maestra.nombre} [{self.rol_ejercido.nombre}]"