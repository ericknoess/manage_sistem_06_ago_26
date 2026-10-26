# datos_proceso/models.py
#
# Datos de proceso (antes en la app "Cultivo"): qué se mide en cada actividad de la receta y lo que se capturó en cada lote.
#   Catálogo:  ParametroProceso (uno para toda la planta; puede ser calculado con fórmula)
#   Receta:    SeccionCaptura (por actividad: cuándo se captura) → ParametroSeccion (qué parámetros y sus límites)
#   Lote:      TomaDatos (un evento de captura en una fase) → ValorParametro (un valor; las correcciones lo reemplazan)
#   Análisis:  IndicadorProceso (por receta: área bajo la curva, apego a la curva esperada, último, máximo o fórmula)
# Lo capturado no se borra ni se edita: corregir crea un valor nuevo que reemplaza al anterior (con motivo y firma).

from django.conf import settings
from django.db import models
from django.db.models import Q


class ParametroProceso(models.Model):
    TIPO_CHOICES = [
        ('NUMERO', 'Número'),
        ('TEXTO', 'Texto'),
        ('OPCION', 'Lista de opciones'),
        ('BOOLEANO', 'Sí / No'),
    ]

    codigo = models.CharField(max_length=40, unique=True,
                              help_text="Código corto que usan las fórmulas (ej. ph, glucosa). No cambia después de crearlo")
    nombre = models.CharField(max_length=120)
    unidad = models.CharField(max_length=30, blank=True, default='', help_text="Unidad de medida (ej. g/L, °C, MCel/mL)")
    tipo_dato = models.CharField(max_length=10, choices=TIPO_CHOICES, default='NUMERO')
    decimales = models.PositiveSmallIntegerField(default=2, help_text="Decimales con que se captura y se muestra")
    opciones = models.JSONField(default=list, blank=True, help_text="Valores permitidos si el tipo es lista de opciones")
    formula = models.TextField(blank=True, default='',
                               help_text="Si tiene fórmula, el valor no se captura: se calcula con otros parámetros")
    descripcion = models.TextField(blank=True, default='')
    activo = models.BooleanField(default=True, help_text="Disponible para recetas nuevas (baja lógica)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = "Parámetro de proceso"
        verbose_name_plural = "Parámetros de proceso"

    def __str__(self):
        return f"{self.nombre} ({self.unidad})" if self.unidad else self.nombre

    @property
    def es_calculado(self):
        return bool((self.formula or '').strip())


class SeccionCaptura(models.Model):
    """
    Grupo de parámetros que se capturan juntos en una actividad de la receta (ej. "Reactor", "Metabolitos").
    En una incubación con muestreo, `frecuencia` dice en qué muestreos aplica; en otras actividades
    se captura una vez, al completarla.
    """
    FRECUENCIA_CHOICES = [
        ('TODOS', 'En todos los muestreos'),
        ('CADA_N', 'Cada N horas'),
        ('HORAS', 'En horas específicas'),
    ]

    operacion = models.ForeignKey('procesos.OperacionProceso', on_delete=models.CASCADE, related_name='secciones_captura')
    nombre = models.CharField(max_length=100)
    orden = models.PositiveIntegerField(default=0)
    frecuencia = models.CharField(max_length=10, choices=FRECUENCIA_CHOICES, default='TODOS')
    cada_horas = models.PositiveIntegerField(default=0, help_text="Si la frecuencia es cada N horas")
    horas = models.JSONField(default=list, blank=True, help_text="Horas del muestreo en que aplica, si son específicas")
    muestra_fisica = models.BooleanField(default=False, help_text="Se toma una muestra que se identifica con un código")
    patron_codigo_muestra = models.CharField(max_length=60, blank=True, default='',
                                             help_text="Código de la muestra; {n} = consecutivo, {h} = hora (ej. PO41-M{n})")

    class Meta:
        ordering = ['operacion', 'orden', 'id']
        verbose_name = "Sección de captura"
        verbose_name_plural = "Secciones de captura"

    def __str__(self):
        return f"{self.nombre} [{self.operacion.identificador_paso}]"

    def aplica_en(self, hora):
        """¿Se captura en el muestreo de la hora `hora`? (None = actividad sin muestreos: siempre)."""
        if hora is None or self.frecuencia == 'TODOS':
            return True
        if self.frecuencia == 'CADA_N':
            return bool(self.cada_horas) and hora % self.cada_horas == 0
        return hora in (self.horas or [])


class ParametroSeccion(models.Model):
    """Parámetro de una sección, con sus límites de especificación y de alerta (vacíos = sin límite)."""
    seccion = models.ForeignKey(SeccionCaptura, on_delete=models.CASCADE, related_name='parametros')
    parametro = models.ForeignKey(ParametroProceso, on_delete=models.PROTECT, related_name='usos_en_secciones')
    orden = models.PositiveIntegerField(default=0)
    obligatorio = models.BooleanField(default=True)
    especificacion_min = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    especificacion_max = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    alerta_min = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    alerta_max = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    # Referencia para la gráfica de tendencia al capturar (no es criterio de aceptación)
    objetivo = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True,
                                   help_text="Valor esperado constante (línea horizontal)")
    curva_referencia = models.JSONField(default=list, blank=True,
                                        help_text="Valor esperado por edad: [[edad_h, valor], …] ordenado por edad")
    EJES_EDAD = [('LOTE', 'Edad del lote'), ('ETAPA', 'Edad de la etapa')]
    eje_edad = models.CharField(max_length=5, choices=EJES_EDAD, default='LOTE',
                                help_text="Contra qué edad se grafica la tendencia y se lee la curva")

    class Meta:
        ordering = ['seccion', 'orden', 'id']
        verbose_name = "Parámetro de sección"
        verbose_name_plural = "Parámetros de sección"
        constraints = [
            models.UniqueConstraint(fields=['seccion', 'parametro'], name='unique_parametro_por_seccion'),
        ]

    def __str__(self):
        return f"{self.parametro.codigo} en {self.seccion}"


class _SoloAgregar(models.Model):
    """Registros GxP: no se borran (corregir crea un registro nuevo)."""

    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        raise PermissionError("Los datos de proceso capturados no se pueden eliminar (integridad de datos GxP).")


class TomaDatos(_SoloAgregar):
    """
    Un evento de captura en una fase del lote: el muestreo M-12h, el cierre de una actividad o una muestra adicional.
    `momento` es la hora real de la toma; de ahí se calcula la edad contra la edad 0 de la etapa y del lote.
    """
    fase = models.ForeignKey('procesos.FaseLote', on_delete=models.PROTECT, related_name='tomas_datos')
    momento = models.DateTimeField(help_text="Hora real de la toma")
    adicional = models.BooleanField(default=False, help_text="Muestra fuera del calendario de muestreos")
    motivo = models.TextField(blank=True, default='', help_text="Por qué se tomó la muestra adicional")
    codigos_muestra = models.JSONField(default=dict, blank=True, help_text="{sección: código de la muestra física}")
    plan = models.JSONField(default=dict, blank=True, help_text="Secciones y parámetros que se pidieron (con límites), tal como eran")
    registrado_por_usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                               related_name='tomas_datos')
    registrado_por_operador = models.ForeignKey('roster.Operador', on_delete=models.PROTECT, null=True, blank=True,
                                                related_name='tomas_datos')
    registrado_por_nombre = models.CharField(max_length=150)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['momento', 'id']
        verbose_name = "Toma de datos"
        verbose_name_plural = "Tomas de datos"
        constraints = [
            # Del calendario hay una sola toma por fase; las adicionales pueden ser varias
            models.UniqueConstraint(fields=['fase'], condition=Q(adicional=False), name='unique_toma_por_fase'),
        ]

    def __str__(self):
        return f"Toma {'adicional ' if self.adicional else ''}{self.fase_id} @ {self.momento:%Y-%m-%d %H:%M}"


class ValorParametro(_SoloAgregar):
    """
    Valor de un parámetro en una toma. Los límites y la sección se guardan como eran al capturar.
    Una corrección crea otro valor con `reemplaza` = este y deja este con `vigente=False`.
    """
    toma = models.ForeignKey(TomaDatos, on_delete=models.PROTECT, related_name='valores')
    parametro = models.ForeignKey(ParametroProceso, on_delete=models.PROTECT, related_name='valores')
    seccion_nombre = models.CharField(max_length=100, blank=True, default='')
    valor_numero = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    valor_texto = models.CharField(max_length=500, blank=True, default='')
    calculado = models.BooleanField(default=False)
    limites = models.JSONField(default=dict, blank=True, help_text="Límites vigentes al capturar")
    fuera_especificacion = models.BooleanField(default=False)
    fuera_alerta = models.BooleanField(default=False)
    vigente = models.BooleanField(default=True)
    reemplaza = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='correcciones')
    motivo_correccion = models.TextField(blank=True, default='')
    registrado_por_usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                               related_name='valores_parametro')
    registrado_por_operador = models.ForeignKey('roster.Operador', on_delete=models.PROTECT, null=True, blank=True,
                                                related_name='valores_parametro')
    registrado_por_nombre = models.CharField(max_length=150)
    registrado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['toma', 'id']
        verbose_name = "Valor de parámetro"
        verbose_name_plural = "Valores de parámetro"

    def __str__(self):
        return f"{self.parametro.codigo} = {self.valor_mostrado}"

    @property
    def valor_mostrado(self):
        if self.valor_numero is not None:
            return format(self.valor_numero.normalize(), 'f')
        return self.valor_texto


class IndicadorProceso(models.Model):
    """
    Indicador que se calcula para cada lote de una receta a partir de sus datos vigentes (no se guarda: se calcula al consultar).
    Ej. ABC de células (AREA), % de apego a la curva esperada (APEGO), gramos estimados = abc_cel / 1000 - 5.5 (FORMULA).
    """
    TIPO_CHOICES = [
        ('AREA', 'Área bajo la curva'),
        ('APEGO', 'Apego a la curva esperada (%)'),
        ('ULTIMO', 'Último valor'),
        ('MAXIMO', 'Valor máximo'),
        ('FORMULA', 'Fórmula con otros indicadores'),
    ]
    proceso = models.ForeignKey('procesos.ProcesoMaestro', on_delete=models.CASCADE, related_name='indicadores')
    codigo = models.CharField(max_length=40, help_text="Código corto para usarlo en fórmulas (ej. abc_cel)")
    nombre = models.CharField(max_length=120)
    unidad = models.CharField(max_length=30, blank=True, default='')
    decimales = models.PositiveSmallIntegerField(default=1)
    orden = models.PositiveIntegerField(default=0)
    tipo = models.CharField(max_length=8, choices=TIPO_CHOICES)
    parametro = models.ForeignKey(ParametroProceso, on_delete=models.PROTECT, null=True, blank=True, related_name='indicadores',
                                  help_text="Parámetro numérico que se analiza (todos los tipos salvo fórmula)")
    etapa = models.ForeignKey('procesos.EtapaProceso', on_delete=models.CASCADE, null=True, blank=True, related_name='indicadores',
                              help_text="Solo datos de esta etapa (vacío = todo el lote)")
    eje_edad = models.CharField(max_length=5, choices=ParametroSeccion.EJES_EDAD, default='LOTE',
                                help_text="Edad contra la que se integra el área (el apego usa la de la curva esperada)")
    formula = models.TextField(blank=True, default='', help_text="Solo tipo fórmula: usa los códigos de otros indicadores")
    meta_min = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    meta_max = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['proceso', 'orden', 'id']
        verbose_name = "Indicador de proceso"
        verbose_name_plural = "Indicadores de proceso"
        constraints = [
            models.UniqueConstraint(fields=['proceso', 'codigo'], name='unique_codigo_indicador_por_receta'),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.proceso})"
