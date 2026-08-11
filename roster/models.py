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
        ordering = ['identificador']


class Operador(models.Model):
    """
    Representa a un colaborador asignado a una cuadrilla específica dentro de la planta,
    incorporando metadatos de expertiz y soporte fotográfico para trazabilidad GxP.
    """
    EXPERTISE_CHOICES = [
        ('JUNIOR', 'Operador Junior'),
        ('SENIOR', 'Operador Senior'),
        ('ESPECIALISTA', 'Especialista Upstream'),
    ]

    cuadrilla = models.ForeignKey(
        Cuadrilla, 
        on_delete=models.CASCADE, 
        related_name='operadores', 
        verbose_name="Cuadrilla Asignada"
    )
    nombre = models.CharField(max_length=150, verbose_name="Nombre del Operador")
    codigo_empleado = models.CharField(max_length=50, unique=True, blank=True, null=True, verbose_name="Código de Empleado")
    foto = models.ImageField(upload_to='operadores/fotos/', blank=True, null=True, verbose_name="Fotografía del Colaborador")
    nivel_expertiz = models.CharField(max_length=30, choices=EXPERTISE_CHOICES, default='JUNIOR', verbose_name="Nivel de Expertiz")
    activo = models.BooleanField(default=True, verbose_name="Activo en Operación")

    def __str__(self):
        return f"{self.codigo_empleado or 'S/C'} | {self.nombre} ({self.cuadrilla.identificador if self.cuadrilla else 'Sin Cuadrilla'})"

    class Meta:
        verbose_name = "Operador"
        verbose_name_plural = "Operadores"
        ordering = ['codigo_empleado']


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
        ('', 'Sin Asignación / Inactivo'),
    ]

    operador = models.ForeignKey(
        Operador, 
        on_delete=models.CASCADE, 
        related_name='turnos', 
        verbose_name="Operador"
    )
    fecha = models.DateField(verbose_name="Fecha de Asignación")
    codigo_turno = models.CharField(max_length=10, choices=TURNO_CHOICES, default='', verbose_name="Código de Turno")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Última Actualización (GxP)")

    class Meta:
        unique_together = ('operador', 'fecha')
        verbose_name = "Asignación de Turno"
        verbose_name_plural = "Asignaciones de Turnos"
        ordering = ['-fecha', 'operador']

    def __str__(self):
        return f"{self.operador.nombre} - {self.fecha}: {self.codigo_turno or 'Libre'}"


class SecuenciaRol(models.Model):
    """
    Define un patrón de rotación reutilizable (plantilla).
    Ejemplo: "Rotación A 5x2"
    """
    nombre = models.CharField(max_length=100, unique=True, verbose_name="Nombre de la Secuencia")
    descripcion = models.TextField(blank=True, null=True, verbose_name="Descripción")
    activa = models.BooleanField(default=True, verbose_name="¿Está Activa?")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")

    def __str__(self):
        return f"{self.nombre} {'(Activa)' if self.activa else '(Inactiva)'}"

    class Meta:
        verbose_name = "Secuencia de Rol"
        verbose_name_plural = "Secuencias de Rol"
        ordering = ['nombre']


class SecuenciaRolDetalle(models.Model):
    """
    Define los pasos individuales de una secuencia de rol.
    """
    secuencia = models.ForeignKey(
        SecuenciaRol, 
        on_delete=models.CASCADE, 
        related_name='detalles', 
        verbose_name="Secuencia Padre"
    )
    orden = models.PositiveIntegerField(verbose_name="Orden de Ejecución")
    codigo_turno = models.CharField(
        max_length=10, 
        choices=TurnoDia.TURNO_CHOICES, 
        verbose_name="Código de Turno"
    )
    dias = models.PositiveIntegerField(default=1, verbose_name="Cantidad de Días")

    class Meta:
        ordering = ['secuencia', 'orden']
        verbose_name = "Detalle de Secuencia"
        verbose_name_plural = "Detalles de Secuencia"

    def __str__(self):
        return f"{self.secuencia.nombre} - Paso {self.orden}: {self.codigo_turno} x {self.dias} días"