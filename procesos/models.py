# procesos/models.py

from django.db import models
from actividades.models import Equipo, MaterialInsumo

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
    ops_muestreo = models.PositiveIntegerField(default=1, help_text="Número de operadores requeridos para cada muestreo cíclico")
    
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
    personal_requerido = models.PositiveIntegerField(default=1, help_text="Número de operadores requeridos para la actividad")
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