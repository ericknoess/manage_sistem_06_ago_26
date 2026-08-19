# actividades/models.py

from django.db import models
from roster.models import Operador

class Equipo(models.Model):
    """
    Catálogo maestro de equipos críticos de bioproceso (Biorreactores, tanques, centrífugas).
    """
    id = models.CharField(max_length=50, primary_key=True, help_text="Código único del equipo (Ej: EQ-01)")
    nombre = models.CharField(max_length=150, help_text="Nombre descriptivo del equipo")
    tipo = models.CharField(max_length=50, default="EQUIPO", help_text="Tipo o categoría del equipo")
    activo = models.BooleanField(default=True, help_text="Disponibilidad operativa en planta")

    def __str__(self):
        return f"[{self.id}] {self.nombre}"


class MaterialInsumo(models.Model):
    """
    Catálogo maestro de materias primas, medios de cultivo y consumibles.
    """
    id = models.CharField(max_length=50, primary_key=True, help_text="Código único del material (Ej: MAT-01)")
    nombre = models.CharField(max_length=150, help_text="Nombre del material o insumo")
    stock_controlado = models.BooleanField(default=True, help_text="Indica si requiere control estricto de lote")
    activo = models.BooleanField(default=True, help_text="Disponible para uso en recetas")

    def __str__(self):
        return f"[{self.id}] {self.nombre}"


class ActividadSemanal(models.Model):
    """
    Representa una tarea programada dentro de la vista semanal de operaciones,
    vinculada a múltiples operadores del Roster y a recursos críticos.
    """
    TURNO_CHOICES = [
        ('M', 'Matutino'),
        ('T', 'Vespertino'),
        ('N', 'Nocturno'),
        ('OFF', 'Descanso'),
    ]

    lote_codigo = models.CharField(max_length=100, help_text="Código del lote de producción asociado (Ej: LOTE-CHO-01)")
    titulo = models.CharField(max_length=200, help_text="Nombre de la actividad operativa")
    fecha = models.DateField(help_text="Fecha programada para la ejecución (YYYY-MM-DD)")
    hora_inicio = models.TimeField(help_text="Hora estimada de inicio")
    hora_fin = models.TimeField(help_text="Hora estimada de finalización")
    turno_req = models.CharField(max_length=5, choices=TURNO_CHOICES, default='M', help_text="Turno requerido para la tarea")
    
    # Nuevo campo para definir cuántas personas requiere la tarea
    personal_requerido = models.PositiveIntegerField(default=1, help_text="Número mínimo de operadores necesarios")

    # Relación Many-to-Many con los operadores del Roster
    operadores_asignados = models.ManyToManyField(
        Operador, 
        blank=True, 
        related_name='actividades_semanales',
        help_text="Operadores responsables asignados desde el Roster"
    )

    # Relaciones Many-to-Many para equipos y materiales requeridos
    equipos = models.ManyToManyField(Equipo, blank=True, related_name='actividades')
    materiales = models.ManyToManyField(MaterialInsumo, blank=True, related_name='actividades')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.fecha} | {self.titulo} ({self.hora_inicio} - {self.hora_fin})"