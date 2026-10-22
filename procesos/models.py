# procesos/models.py

from datetime import timedelta

from django.db import models
from actividades.models import Equipo, MaterialInsumo, TipoEquipo
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

    # Ventana de inicio en planta: cuánto antes (−) o después (+) de su hora programada puede iniciar la actividad
    # sin tratarse como desviación de horario. Aplica también a cada muestreo de la actividad.
    tolerancia_antes_horas = models.FloatField(default=2, help_text="Horas antes de la hora programada en que ya se puede iniciar")
    tolerancia_despues_horas = models.FloatField(default=2, help_text="Horas después de la hora programada en que aún se inicia sin desviación")

    personal_requerido = models.PositiveIntegerField(default=1, help_text="Número total de operadores requeridos")

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


class MaterialOperacion(models.Model):
    """
    Material que consume una operación de la receta, con su cantidad y con cuántas horas antes
    del inicio de la actividad debe estar disponible (descongelar, atemperar, preparar).
    """
    APLICA_A_CHOICES = [
        ('ACTIVIDAD', 'Actividad principal'),
        ('MUESTREO', 'Cada evento de muestreo'),
    ]

    operacion = models.ForeignKey(OperacionProceso, on_delete=models.CASCADE, related_name='materiales')
    material = models.ForeignKey(MaterialInsumo, on_delete=models.PROTECT, related_name='usos_en_operaciones')
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, help_text="Cantidad en la unidad de medida del material")
    anticipacion_horas = models.FloatField(default=0, help_text="Horas antes del inicio de la actividad en que se requiere")
    aplica_a = models.CharField(max_length=10, choices=APLICA_A_CHOICES, default='ACTIVIDAD')

    class Meta:
        verbose_name = "Material de Operación"
        verbose_name_plural = "Materiales de Operación"
        constraints = [
            models.UniqueConstraint(fields=['operacion', 'material', 'aplica_a'], name='unique_material_por_operacion'),
        ]

    def __str__(self):
        return f"{self.cantidad} {self.material.unidad_medida} {self.material.nombre} para [{self.operacion.identificador_paso}]"


class EquipoOperacion(models.Model):
    """
    Equipo que necesita una operación de la receta, por tipo y cantidad. El equipo queda ocupado
    desde `horas_preparacion` antes del inicio (montaje, SIP) hasta `horas_limpieza` después del fin (CIP).
    """
    APLICA_A_CHOICES = MaterialOperacion.APLICA_A_CHOICES

    operacion = models.ForeignKey(OperacionProceso, on_delete=models.CASCADE, related_name='equipos')
    tipo = models.ForeignKey(TipoEquipo, on_delete=models.PROTECT, related_name='usos_en_operaciones')
    cantidad = models.PositiveIntegerField(default=1, help_text="Cuántos equipos de este tipo se ocupan")
    horas_preparacion = models.FloatField(default=0, help_text="Horas que el equipo se ocupa antes del inicio (montaje, esterilización)")
    horas_limpieza = models.FloatField(default=0, help_text="Horas que el equipo se ocupa después del fin (limpieza, CIP)")
    aplica_a = models.CharField(max_length=10, choices=APLICA_A_CHOICES, default='ACTIVIDAD')

    class Meta:
        verbose_name = "Equipo de Operación"
        verbose_name_plural = "Equipos de Operación"
        constraints = [
            models.UniqueConstraint(fields=['operacion', 'tipo', 'aplica_a'], name='unique_tipo_equipo_por_operacion'),
        ]

    def __str__(self):
        return f"{self.cantidad}x {self.tipo.nombre} para [{self.operacion.identificador_paso}]"


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
    
    # Fecha-hora completas: una fase puede durar varios días (ej. incubaciones de 72 h)
    inicio_base_cpm = models.DateTimeField(null=True, blank=True, help_text="Inicio según la línea base CPM al instanciar el lote")
    fin_base_cpm = models.DateTimeField(null=True, blank=True, help_text="Fin según la línea base CPM al instanciar el lote")

    inicio_programado = models.DateTimeField(null=True, blank=True, help_text="Inicio vigente (forecast) tras reprogramaciones")
    fin_programado = models.DateTimeField(null=True, blank=True, help_text="Fin vigente (forecast) tras reprogramaciones")
    
    motivo_reprogramacion = models.CharField(max_length=50, choices=MOTIVO_REPROGRAMACION_CHOICES, null=True, blank=True)
    notas_reprogramacion = models.TextField(null=True, blank=True)

    fecha_inicio_real = models.DateTimeField(null=True, blank=True)
    fecha_fin_real = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Fase de Lote"
        verbose_name_plural = "Fases de Lote"
        ordering = ['operacion_maestra__identificador_paso', 'indice_muestreo']

    def __str__(self):
        nombre_mostrar = self.nombre_tarea_dinamica if self.es_subtarea_muestreo else self.operacion_maestra.nombre
        return f"Lote: {self.lote.identificador_lote} | Fase: {nombre_mostrar} ({self.estado})"

    @property
    def duracion_planeada(self):
        """Duración estimada: la del evento de muestreo para subtareas, la de la operación en otro caso."""
        op = self.operacion_maestra
        horas = op.duracion_muestreo_horas if self.es_subtarea_muestreo else op.duracion_horas
        return timedelta(hours=horas or 0)


class MaterialFase(models.Model):
    """
    Requerimiento de material de una fase de lote. Se copia de la receta al instanciar el lote
    para que editar la receta después no altere el registro; los ajustes por lote guardan motivo
    y los retiros son bajas lógicas (`activo=False`).
    """
    fase = models.ForeignKey(FaseLote, on_delete=models.CASCADE, related_name='materiales')
    material = models.ForeignKey(MaterialInsumo, on_delete=models.PROTECT, related_name='requerimientos_lote')
    cantidad = models.DecimalField(max_digits=12, decimal_places=3)
    # Copia de la unidad del catálogo al crear el registro: cambiarla después en el catálogo no altera el lote
    unidad_medida = models.CharField(max_length=10)
    cantidad_receta = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True, help_text="Cantidad original de la receta; vacía si se agregó en el lote")
    anticipacion_horas = models.FloatField(default=0)
    activo = models.BooleanField(default=True)
    motivo_ajuste = models.TextField(blank=True, default='')
    ajustado_en = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Material de Fase"
        verbose_name_plural = "Materiales de Fase"
        constraints = [
            models.UniqueConstraint(fields=['fase', 'material'], name='unique_material_por_fase'),
        ]

    def __str__(self):
        return f"{self.cantidad} {self.material.unidad_medida} {self.material.nombre} | {self.fase}"

    @property
    def momento_requerido(self):
        """Fecha-hora en que el material debe estar disponible; sigue al forecast de la fase."""
        if not self.fase.inicio_programado:
            return None
        return self.fase.inicio_programado - timedelta(hours=self.anticipacion_horas or 0)


class EntregaMaterial(models.Model):
    """
    Surtido de un material de fase con doble firma: quien entrega y quien recibe (nunca la misma persona).
      - ENTREGA: almacén o planeación → personal de la fase.
      - DEVOLUCION: personal de la fase → almacén (sobrante de una entrega recibida; hereda su lote y caducidad).
    Los registros no se borran: el estado avanza de EN_TRANSITO a RECIBIDA o RECHAZADA (con motivo).
    """
    TIPO_CHOICES = [('ENTREGA', 'Entrega'), ('DEVOLUCION', 'Devolución')]
    ESTADO_CHOICES = [('EN_TRANSITO', 'Por recibir'), ('RECIBIDA', 'Recibida'), ('RECHAZADA', 'Rechazada')]

    material_fase = models.ForeignKey(MaterialFase, on_delete=models.PROTECT, related_name='entregas')
    tipo = models.CharField(max_length=12, choices=TIPO_CHOICES, default='ENTREGA')
    devolucion_de = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='devoluciones',
                                      help_text="Entrega de la que se devuelve el sobrante")
    cantidad = models.DecimalField(max_digits=12, decimal_places=3)
    unidad_medida = models.CharField(max_length=10)
    lote_material = models.CharField(max_length=80, help_text="Lote del insumo (proveedor o almacén)")
    caducidad = models.DateField(help_text="Caducidad del lote del insumo")
    observaciones = models.TextField(blank=True, default='')
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='EN_TRANSITO')

    # Quién entrega: usuario web o persona con PIN en la terminal (el nombre se guarda tal como era)
    entregado_por_usuario = models.ForeignKey('auth.User', on_delete=models.PROTECT, null=True, blank=True, related_name='entregas_material')
    entregado_por_operador = models.ForeignKey(Operador, on_delete=models.PROTECT, null=True, blank=True, related_name='entregas_material')
    entregado_por_nombre = models.CharField(max_length=150)
    entregado_en = models.DateTimeField()

    # Quién recibe o rechaza
    recibido_por_usuario = models.ForeignKey('auth.User', on_delete=models.PROTECT, null=True, blank=True, related_name='recepciones_material')
    recibido_por_operador = models.ForeignKey(Operador, on_delete=models.PROTECT, null=True, blank=True, related_name='recepciones_material')
    recibido_por_nombre = models.CharField(max_length=150, blank=True, default='')
    recibido_en = models.DateTimeField(null=True, blank=True)
    motivo_rechazo = models.TextField(blank=True, default='')

    class Meta:
        verbose_name = "Entrega de material"
        verbose_name_plural = "Entregas de material"
        ordering = ['entregado_en', 'id']

    def __str__(self):
        return f"{self.get_tipo_display()} {self.cantidad} {self.unidad_medida} {self.material_fase.material_id} ({self.get_estado_display()})"


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

class EquipoFase(models.Model):
    """
    Requerimiento de equipo de una fase de lote, copiado de la receta al instanciar el lote. Los ajustes
    guardan motivo y los retiros son bajas lógicas, igual que los materiales. Los equipos concretos
    se reservan en `ReservaEquipo`.
    """
    fase = models.ForeignKey(FaseLote, on_delete=models.CASCADE, related_name='equipos')
    tipo = models.ForeignKey(TipoEquipo, on_delete=models.PROTECT, related_name='requerimientos_lote')
    cantidad = models.PositiveIntegerField(default=1)
    cantidad_receta = models.PositiveIntegerField(null=True, blank=True, help_text="Cantidad original de la receta; vacía si se agregó en el lote")
    horas_preparacion = models.FloatField(default=0)
    horas_limpieza = models.FloatField(default=0)
    activo = models.BooleanField(default=True)
    motivo_ajuste = models.TextField(blank=True, default='')
    ajustado_en = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Equipo de Fase"
        verbose_name_plural = "Equipos de Fase"
        constraints = [
            models.UniqueConstraint(fields=['fase', 'tipo'], name='unique_tipo_equipo_por_fase'),
        ]

    def __str__(self):
        return f"{self.cantidad}x {self.tipo.nombre} | {self.fase}"

    def ventana_ocupacion(self):
        """(inicio, fin) en que la fase ocupa el equipo, con preparación y limpieza. Usa las horas reales si ya las hay."""
        fase = self.fase
        inicio = fase.fecha_inicio_real or fase.inicio_programado
        if not inicio:
            return None, None
        if fase.fecha_fin_real:
            fin = fase.fecha_fin_real
        elif fase.fecha_inicio_real:
            fin = fase.fecha_inicio_real + fase.duracion_planeada
        else:
            fin = fase.fin_programado or inicio + fase.duracion_planeada
        return (inicio - timedelta(hours=self.horas_preparacion or 0), fin + timedelta(hours=self.horas_limpieza or 0))


class ReservaEquipo(models.Model):
    """
    Equipo concreto reservado para un requerimiento de fase. Si se cambia durante la ejecución, la reserva
    anterior se cierra en `hasta` y la nueva empieza en `desde`, de modo que el registro muestra qué equipo
    se usó en cada tramo. Liberar una reserva antes de iniciar es baja lógica (`activo=False`).
    """
    equipo_fase = models.ForeignKey(EquipoFase, on_delete=models.CASCADE, related_name='reservas')
    equipo = models.ForeignKey(Equipo, on_delete=models.PROTECT, related_name='reservas')
    desde = models.DateTimeField(null=True, blank=True, help_text="Inicio del tramo si entró por un cambio durante la ejecución")
    hasta = models.DateTimeField(null=True, blank=True, help_text="Fin del tramo si se cambió por otro equipo durante la ejecución")
    activo = models.BooleanField(default=True)
    motivo = models.TextField(blank=True, default='', help_text="Motivo de la liberación o del cambio")
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Reserva de Equipo"
        verbose_name_plural = "Reservas de Equipo"
        ordering = ['equipo_fase', 'creado_en']

    def __str__(self):
        return f"{self.equipo} → {self.equipo_fase.fase}"

    @property
    def vigente(self):
        """Ocupa el equipo ahora o en adelante: activa y sin cerrar por un cambio."""
        return self.activo and self.hasta is None

    def ventana(self):
        """Tramo que ocupa este equipo: la ventana del requerimiento recortada por `desde`/`hasta`."""
        inicio, fin = self.equipo_fase.ventana_ocupacion()
        if inicio is None:
            return None, None
        if self.desde and self.desde > inicio:
            inicio = self.desde
        if self.hasta and self.hasta < fin:
            fin = self.hasta
        return inicio, fin
