# actividades/models.py

from django.db import models
from roster.models import Operador

class TipoEquipo(models.Model):
    """
    Categoría de equipo (Biorreactor, Autoclave, Centrífuga…). Las recetas piden equipos por tipo y,
    al planear el lote, se reserva un equipo concreto de ese tipo.
    """
    codigo = models.CharField(max_length=50, primary_key=True, help_text="Código del tipo (Ej: BIORREACTOR)")
    nombre = models.CharField(max_length=100, help_text="Nombre visible del tipo")
    activo = models.BooleanField(default=True, help_text="Disponible para nuevas recetas y equipos (baja lógica)")

    class Meta:
        ordering = ['nombre']
        verbose_name = "Tipo de equipo"
        verbose_name_plural = "Tipos de equipo"

    def __str__(self):
        return self.nombre


class Equipo(models.Model):
    """
    Catálogo maestro de equipos críticos de bioproceso (Biorreactores, tanques, centrífugas).
    """
    ESTADO_CHOICES = [
        ('DISPONIBLE', 'Disponible'),
        ('MANTENIMIENTO', 'En mantenimiento'),
        ('FUERA_SERVICIO', 'Fuera de servicio'),
    ]

    id = models.CharField(max_length=50, primary_key=True, help_text="Código único del equipo (Ej: EQ-01)")
    nombre = models.CharField(max_length=150, help_text="Nombre descriptivo del equipo")
    tipo = models.ForeignKey(TipoEquipo, on_delete=models.PROTECT, to_field='codigo', db_column='tipo',
                             related_name='equipos', help_text="Tipo o categoría del equipo")
    area = models.CharField(max_length=100, blank=True, default='', help_text="Área o sala donde está el equipo")
    capacidad = models.CharField(max_length=50, blank=True, default='', help_text="Capacidad o tamaño (Ej: 500 L)")
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='DISPONIBLE',
                              help_text="Solo un equipo disponible se puede reservar")
    calificacion_vence = models.DateField(null=True, blank=True,
                                         help_text="Vencimiento de la calificación; después de esa fecha no se reserva")
    activo = models.BooleanField(default=True, help_text="Disponibilidad operativa en planta (baja lógica)")

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"[{self.id}] {self.nombre}"

    def motivo_no_reservable(self, hasta=None):
        """Por qué el equipo no se puede reservar hasta la fecha-hora `hasta`, o None si sí se puede."""
        if not self.activo:
            return f"El equipo [{self.id}] está dado de baja."
        if self.estado != 'DISPONIBLE':
            return f"El equipo [{self.id}] está {self.get_estado_display().lower()}."
        if self.calificacion_vence and hasta and self.calificacion_vence < hasta.date():
            return f"La calificación de [{self.id}] vence el {self.calificacion_vence:%d/%m/%Y}, antes de terminar la reserva."
        return None


class MaterialInsumo(models.Model):
    """
    Catálogo maestro de materias primas, medios de cultivo y consumibles.
    """
    CATEGORIA_CHOICES = [
        ('MEDIO', 'Medio de cultivo'),
        ('SOLUCION', 'Solución / buffer'),
        ('REACTIVO', 'Reactivo / suplemento'),
        ('SINGLE_USE', 'Single-use (bolsas, filtros, tubería)'),
        ('CONSUMIBLE', 'Consumible de laboratorio'),
        ('LIMPIEZA', 'Limpieza / sanitización'),
        ('OTRO', 'Otro'),
    ]
    UNIDAD_CHOICES = [
        ('L', 'L'),
        ('mL', 'mL'),
        ('kg', 'kg'),
        ('g', 'g'),
        ('mg', 'mg'),
        ('pza', 'pza'),
        ('kit', 'kit'),
        ('caja', 'caja'),
    ]
    ALMACENAMIENTO_CHOICES = [
        ('AMBIENTE', 'Ambiente (15–25 °C)'),
        ('REFRIGERADO', 'Refrigerado (2–8 °C)'),
        ('CONGELADO', 'Congelado (-20 °C)'),
        ('ULTRACONGELADO', 'Ultracongelado (-80 °C)'),
    ]

    id = models.CharField(max_length=50, primary_key=True, help_text="Código único del material (Ej: MAT-01)")
    nombre = models.CharField(max_length=150, help_text="Nombre del material o insumo")
    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES, default='OTRO')
    unidad_medida = models.CharField(max_length=10, choices=UNIDAD_CHOICES, default='pza', help_text="Unidad en la que se expresan las cantidades requeridas")
    codigo_erp = models.CharField(max_length=50, blank=True, default='', help_text="Código del material en ERP/SAP")
    proveedor = models.CharField(max_length=150, blank=True, default='')
    condicion_almacenamiento = models.CharField(max_length=20, choices=ALMACENAMIENTO_CHOICES, default='AMBIENTE')
    stock_controlado = models.BooleanField(default=True, help_text="Indica si requiere control estricto de lote")
    activo = models.BooleanField(default=True, help_text="Disponible para uso en recetas")

    class Meta:
        ordering = ['nombre']

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