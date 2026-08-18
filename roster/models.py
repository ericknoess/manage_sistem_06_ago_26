# roster/models.py
from django.db import models

class TipoTurno(models.Model):
    """
    Catálogo maestro configurable de tipos de turnos y roles operativos.
    Permite definir códigos personalizados y sus propiedades visuales (colores HEX).
    """
    codigo = models.CharField(
        max_length=10, 
        unique=True, 
        primary_key=True,
        verbose_name="Código de Turno",
        help_text="Identificador corto único (ej. M, T, N, PERF)"
    )
    nombre = models.CharField(
        max_length=100, 
        verbose_name="Nombre Descriptivo",
        help_text="Descripción larga del turno (ej. Mañana, Perfusión Especial)"
    )
    color_fondo = models.CharField(
        max_length=7, 
        default="#3b82f6", 
        verbose_name="Color de Fondo (HEX)",
        help_text="Código HEX para el fondo de la celda (ej. #3b82f6)"
    )
    color_texto = models.CharField(
        max_length=7, 
        default="#ffffff", 
        verbose_name="Color de Texto (HEX)",
        help_text="Código HEX para el texto de la celda (ej. #ffffff)"
    )
    es_descanso = models.BooleanField(
        default=False, 
        verbose_name="¿Es Descanso?",
        help_text="Marca si el turno representa tiempo libre o ausencia no operativa"
    )
    activo = models.BooleanField(
        default=True, 
        verbose_name="Turno Activo",
        help_text="Baja lógica para preservar la trazabilidad histórica GxP"
    )
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name="Última Actualización")

    def __str__(self):
        return f"[{self.codigo}] {self.nombre}"

    class Meta:
        verbose_name = "Tipo de Turno"
        verbose_name_plural = "Tipos de Turnos"
        ordering = ['codigo']


class Cuadrilla(models.Model):
    """
    Representa una cuadrilla de trabajo dentro del área de bioprocesos Upstream 
    (ej. Inóculos, Biorreactores).
    """
    identificador = models.CharField(max_length=50, unique=True, verbose_name="Identificador de Cuadrilla")
    nombre = models.CharField(max_length=100, verbose_name="Nombre Descriptivo")
    activa = models.BooleanField(default=True, verbose_name="Cuadrilla Activa")
    descripcion = models.TextField(blank=True, null=True, verbose_name="Descripción del Área")
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name="Última Actualización")

    def __str__(self):
        return f"{self.identificador} - {self.nombre}"

    class Meta:
        verbose_name = "Cuadrilla"
        verbose_name_plural = "Cuadrillas"
        ordering = ['identificador']


class Operador(models.Model):
    """
    Representa a un colaborador asignado a una cuadrilla específica dentro de la planta.
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
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name="Última Actualización")

    def __str__(self):
        return f"{self.codigo_empleado or 'S/C'} | {self.nombre} ({self.cuadrilla.identificador if self.cuadrilla else 'Sin Cuadrilla'})"

    class Meta:
        verbose_name = "Operador"
        verbose_name_plural = "Operadores"
        ordering = ['codigo_empleado']


class TurnoDia(models.Model):
    """
    Matriz de turnos operacional. Asocia a un operador con un tipo de turno específico en una fecha dada.
    """
    operador = models.ForeignKey(
        Operador, 
        on_delete=models.CASCADE, 
        related_name='turnos', 
        verbose_name="Operador"
    )
    fecha = models.DateField(verbose_name="Fecha de Asignación")
    tipo_turno = models.ForeignKey(
        TipoTurno,
        on_delete=models.PROTECT,
        to_field='codigo',
        db_column='codigo_turno',
        related_name='asignaciones',
        verbose_name="Tipo de Turno",
        default='M'
    )
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name="Última Actualización")

    class Meta:
        unique_together = ('operador', 'fecha')
        verbose_name = "Asignación de Turno"
        verbose_name_plural = "Asignaciones de Turnos"
        ordering = ['-fecha', 'operador']

    def __str__(self):
        return f"{self.operador.nombre} - {self.fecha}: {self.tipo_turno_id or 'Libre'}"


class SecuenciaRol(models.Model):
    """
    Define un patrón de rotación reutilizable (plantilla).
    """
    nombre = models.CharField(max_length=100, unique=True, verbose_name="Nombre de la Secuencia")
    descripcion = models.TextField(blank=True, null=True, verbose_name="Descripción")
    activa = models.BooleanField(default=True, verbose_name="¿Está Activa?")
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name="Última Actualización")

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
    tipo_turno = models.ForeignKey(
        TipoTurno,
        on_delete=models.PROTECT,
        to_field='codigo',
        db_column='codigo_turno',
        related_name='detalles_secuencia',
        verbose_name="Tipo de Turno",
        default='M'
    )
    dias = models.PositiveIntegerField(default=1, verbose_name="Cantidad de Días")
    creado_en = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name="Última Actualización")

    class Meta:
        ordering = ['secuencia', 'orden']
        verbose_name = "Detalle de Secuencia"
        verbose_name_plural = "Detalles de Secuencia"

    def __str__(self):
        return f"{self.secuencia.nombre} - Paso {self.orden}: {self.tipo_turno_id} x {self.dias} días"