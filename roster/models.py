from django.db import models

class Cuadrilla(models.Model):
    """
    Agrupación lógica de operadores en la planta biotecnológica.
    Ejemplo: Cuadrilla A - Inóculos.
    """
    identificador = models.CharField(max_length=5, unique=True, help_text="Ej: A, B, C")
    nombre = models.CharField(max_length=100, help_text="Nombre descriptivo de la cuadrilla")
    activa = models.BooleanField(default=True, help_text="Define si la cuadrilla está operando actualmente")
    
    # Campos de auditoría básicos
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Cuadrilla'
        verbose_name_plural = 'Cuadrillas'
        ordering = ['identificador']

    def __str__(self):
        return f"Cuadrilla {self.identificador} - {self.nombre}"


class Operador(models.Model):
    """
    Colaborador asignado a la planta.
    """
    nombre = models.CharField(max_length=150)
    # Relación 1 a N: Una cuadrilla tiene muchos operadores. 
    # on_delete=models.PROTECT evita borrar una cuadrilla si tiene operadores asignados.
    cuadrilla = models.ForeignKey(Cuadrilla, on_delete=models.PROTECT, related_name='operadores')
    activo = models.BooleanField(default=True)
    
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Operador'
        verbose_name_plural = 'Operadores'
        ordering = ['cuadrilla__identificador', 'nombre']

    def __str__(self):
        return self.nombre


class TurnoDia(models.Model):
    """
    Registro atómico del estado de un operador en una fecha específica.
    """
    # Opciones de turno extraídas de la lógica operativa de la maqueta
    TIPO_TURNO_CHOICES = [
        ('M', 'Mañana'),
        ('T', 'Tarde'),
        ('N', 'Noche'),
        ('TR', 'Turno Rotativo'),
        ('OFF', 'Descanso'),
        ('F', 'Falta'),
        ('INC', 'Incapacidad'),
        ('--', 'Sin Rol'),
    ]

    operador = models.ForeignKey(Operador, on_delete=models.CASCADE, related_name='turnos')
    fecha = models.DateField()
    codigo_turno = models.CharField(max_length=5, choices=TIPO_TURNO_CHOICES, default='--')
    
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Turno Diario'
        verbose_name_plural = 'Turnos Diarios'
        # Un operador no puede tener dos turnos distintos registrados en el mismo día exacto
        constraints = [
            models.UniqueConstraint(fields=['operador', 'fecha'], name='unique_turno_operador_fecha')
        ]
        ordering = ['fecha']

    def __str__(self):
        return f"{self.operador.nombre} - {self.fecha} [{self.codigo_turno}]"