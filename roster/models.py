# roster/models.py
from django.db import models

class Cuadrilla(models.Model):
    """
    Representa una cuadrilla de trabajo dentro del área de bioprocesos Upstream 
    (ej. Inóculos, Biorreactores).
    """
    identificador = models.CharField(max_length=50, unique=True, verbose_name="Identificador de Cuadrilla")
    nombre = models.CharField(max_length=100, verbose_name="Nombre Descriptivo")
    activa = models.BooleanField(default=True, verbose_name="Cuadrilla Activa")
    descripcion = models.TextField(blank=True, null=True, verbose_name="Descripción del Área")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")

    def __str__(self):
        return f"{self.identificador} - {self.nombre}"

    class Meta:
        verbose_name = "Cuadrilla"
        verbose_name_plural = "Cuadrillas"


class Operador(models.Model):
    """
    Representa a un colaborador asignado a una cuadrilla específica dentro de la planta.
    """
    cuadrilla = models.ForeignKey(
        Cuadrilla, 
        on_delete=models.CASCADE, 
        related_name='operadores', 
        verbose_name="Cuadrilla Asignada"
    )
    nombre = models.CharField(max_length=150, verbose_name="Nombre del Operador")
    codigo_empleado = models.CharField(max_length=50, unique=True, blank=True, null=True, verbose_name="Código de Empleado")
    activo = models.BooleanField(default=True, verbose_name="Activo en Operación")

    def __str__(self):
        return f"{self.nombre} ({self.cuadrilla.identificador})"

    class Meta:
        verbose_name = "Operador"
        verbose_name_plural = "Operadores"


class TurnoDia(models.Model):
    """
    Matriz de turnos operacional. Asocia a un operador con un código de turno específico en una fecha dada,
    garantizando trazabilidad GxP.
    """
    TURNO_CHOICES = [
        ('M', 'Matutino'),
        ('T', 'Vespertino'),
        ('N', 'Nocturno'),
        ('TR', 'Turno Rotativo / Transición'),
        ('OFF', 'Descanso'),
        ('F', 'Falta'),
        ('INC', 'Incapacidad'),
        ('--', 'Sin Asignación / Inactivo'),
    ]

    operador = models.ForeignKey(
        Operador, 
        on_delete=models.CASCADE, 
        related_name='turnos', 
        verbose_name="Operador"
    )
    fecha = models.DateField(verbose_name="Fecha de Asignación")
    codigo_turno = models.CharField(max_length=10, choices=TURNO_CHOICES, verbose_name="Código de Turno")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Última Actualización (GxP)")

    class Meta:
        unique_together = ('operador', 'fecha')
        verbose_name = "Asignación de Turno"
        verbose_name_plural = "Asignaciones de Turnos"

    def __str__(self):
        return f"{self.operador.nombre} - {self.fecha}: {self.codigo_turno}"