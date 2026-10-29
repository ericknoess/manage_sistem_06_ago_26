# gestion/services.py — Proyectos y tareas de oficina (no GMP): calendario hábil, dependencias fin a inicio con
# reprogramación de sucesoras, tareas resumen, ruta crítica, línea base, tablero Kanban e historial simple.
#
# Quién ve y edita: el responsable del proyecto y sus miembros (y los administradores). Configurar el proyecto
# (miembros, columnas, estado, borrar) solo el responsable o un administrador. Solo usuarios web (no la terminal con PIN).
#
# Para no perder información: cada función que modifica un proyecto lleva @con_respaldo, que toma una foto del proyecto
# antes del cambio; `anotar` la guarda en el Historial (quién, cuándo, qué). Con esas fotos se deshace (`deshacer`) o se
# regresa a un punto (`regresar`); además hay versiones con nombre y un respaldo automático por día (`VersionProyecto`),
# y borrar un proyecto lo manda a la papelera.

import contextvars
from datetime import date, datetime, timedelta
from functools import wraps

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import BooleanField, Count, ExpressionWrapper, Max, Q
from django.utils import timezone

from .models import (Columna, Comentario, Dependencia, ElementoChecklist, Etiqueta, Historial, Proyecto, Tarea,
                     VersionProyecto)

COLUMNAS_INICIALES = [('Por hacer', False), ('En curso', False), ('En revisión', False), ('Hecho', True)]
COLORES = ['#2a78d6', '#1baf7a', '#eb6834', '#8b5cf6', '#e87ba4', '#eda100', '#0891b2', '#64748b']
CAMBIOS_DESHACIBLES = 100   # cuántos cambios recientes conservan su foto previa (los más viejos se recuperan con versiones)


class ErrorGestion(Exception):
    """Regla del módulo de proyectos violada (el mensaje se muestra tal cual)."""


# ==============================================================================
# CALENDARIO: días hábiles de lunes a viernes
# ==============================================================================

_EPOCA = date(2000, 1, 3)   # un lunes


def es_habil(d):
    return d.weekday() < 5


def indice_habil(d):
    """Número de día hábil desde la época. Un sábado o domingo cuenta como el lunes siguiente."""
    dias = (d - _EPOCA).days
    return (dias // 7) * 5 + min(dias % 7, 5)


def fecha_de_indice(i):
    return _EPOCA + timedelta(days=(i // 5) * 7 + i % 5)


def habil_desde(d):
    """El mismo día si es hábil; si no, el lunes siguiente."""
    return fecha_de_indice(indice_habil(d))


def sumar_habiles(d, n):
    """`n` días hábiles después (o antes, si es negativo) de `d`."""
    return fecha_de_indice(indice_habil(d) + n)


def dias_habiles(inicio, fin):
    """Días hábiles de `inicio` a `fin`, ambos incluidos."""
    if not inicio or not fin or fin < inicio:
        return 0
    return indice_habil(fin + timedelta(days=1)) - indice_habil(inicio)


def duracion(tarea):
    if tarea.es_hito:
        return 0
    return max(1, dias_habiles(tarea.inicio, tarea.fin)) if tarea.inicio and tarea.fin else 0


def inicio_minimo(predecesora, desfase_dias=0):
    """Primer día en que puede empezar una sucesora: el hábil siguiente a su fin (un hito: ese mismo día), más el desfase."""
    if not predecesora.fin:
        return None
    base = habil_desde(predecesora.fin) if predecesora.es_hito else habil_desde(predecesora.fin + timedelta(days=1))
    return sumar_habiles(base, desfase_dias or 0)


def fin_por_duracion(inicio, dias, es_hito=False):
    return inicio if es_hito or dias <= 0 else sumar_habiles(inicio, dias - 1)


# ==============================================================================
# ACCESO E HISTORIAL
# ==============================================================================

def nombre_usuario(usuario):
    return (usuario.get_full_name() or usuario.get_username()) if usuario else ''


def es_admin(usuario):
    return bool(usuario and (usuario.is_superuser or usuario.groups.filter(name='Administrador').exists()))


def proyectos_visibles(usuario, papelera=False):
    proyectos = Proyecto.objects.filter(en_papelera_desde__isnull=not papelera)
    if not es_admin(usuario):
        proyectos = proyectos.filter(Q(responsable=usuario) | Q(miembros=usuario)).distinct()
    return proyectos


def puede_ver(usuario, proyecto):
    return es_admin(usuario) or proyecto.responsable_id == usuario.id or proyecto.miembros.filter(pk=usuario.pk).exists()


def puede_administrar(usuario, proyecto):
    return es_admin(usuario) or proyecto.responsable_id == usuario.id


def exigir_acceso(usuario, proyecto, administrar=False):
    if administrar and not puede_administrar(usuario, proyecto):
        raise ErrorGestion("Solo el responsable del proyecto o un administrador puede configurarlo.")
    if not puede_ver(usuario, proyecto):
        raise ErrorGestion("No eres miembro de este proyecto.")
    if proyecto.en_papelera_desde and not administrar:
        raise ErrorGestion("El proyecto está en la papelera: recupéralo para modificarlo.")
    if not administrar and proyecto.estado == 'ARCHIVADO':
        raise ErrorGestion("El proyecto está archivado: reactívalo para modificarlo.")


# --- Respaldo antes de cada cambio ----------------------------------------------------

_foto_previa = contextvars.ContextVar('foto_previa', default=None)


def con_respaldo(proyecto_de):
    """Toma la foto del proyecto antes de ejecutar la función (`proyecto_de(objeto)` dice de qué proyecto es el objeto)."""
    def decorador(funcion):
        @wraps(funcion)
        def envoltura(usuario, objeto, *args, **kwargs):
            if _foto_previa.get() is not None:      # ya dentro de otra acción con respaldo
                return funcion(usuario, objeto, *args, **kwargs)
            proyecto = proyecto_de(objeto)
            token = _foto_previa.set((proyecto.pk, foto_proyecto(proyecto)))
            try:
                return funcion(usuario, objeto, *args, **kwargs)
            finally:
                _foto_previa.reset(token)
        return envoltura
    return decorador


def anotar(usuario, proyecto, descripcion, tarea=None, cambios=None, tipo='CAMBIO', estado_previo=None, deshace=None):
    """Registra el cambio con quién lo hizo y la foto previa (si la acción la tomó). Una vez al día, esa foto queda
    además como versión automática; solo los últimos cambios conservan su foto."""
    if estado_previo is None:
        previa = _foto_previa.get()
        estado_previo = previa[1] if previa and previa[0] == proyecto.pk else None
    registro = Historial.objects.create(
        proyecto=proyecto, tarea=tarea, tarea_nombre=tarea.nombre if tarea else '', usuario=usuario,
        usuario_nombre=nombre_usuario(usuario), descripcion=descripcion[:300], cambios=cambios or {}, tipo=tipo,
        estado_previo=estado_previo, deshace=deshace or [])
    if estado_previo is not None:
        hoy = timezone.localdate()
        if not proyecto.versiones.filter(automatica=True, creado_en__date=hoy).exists():
            _crear_version(usuario, proyecto, f"Respaldo automático del {hoy.strftime('%d/%m/%Y')}", estado_previo, automatica=True)
        viejos = list(proyecto.historial.filter(estado_previo__isnull=False).order_by('-id')
                      .values_list('id', flat=True)[CAMBIOS_DESHACIBLES:])
        if viejos:
            Historial.objects.filter(id__in=viejos).update(estado_previo=None)
    return registro


def _texto(valor):
    if valor is None or valor == '':
        return None
    if isinstance(valor, date):
        return valor.strftime('%d/%m/%Y')
    return str(valor)


# ==============================================================================
# PROYECTOS
# ==============================================================================

def _usuario_activo(usuario_id):
    if usuario_id in (None, ''):
        return None
    usuario = get_user_model().objects.filter(pk=usuario_id, is_active=True).first()
    if not usuario:
        raise ErrorGestion("El usuario elegido no existe o está inactivo.")
    return usuario


def _nombre_valido(nombre, que='El nombre', minimo=2):
    nombre = (nombre or '').strip()
    if len(nombre) < minimo:
        raise ErrorGestion(f"Escribe {que.lower()}." if minimo == 1 else f"{que} debe tener al menos {minimo} caracteres.")
    return nombre[:200]


@transaction.atomic
def crear_proyecto(usuario, datos):
    nombre = _nombre_valido(datos.get('nombre'))
    responsable = _usuario_activo(datos.get('responsable')) or usuario
    color = datos.get('color') or COLORES[Proyecto.objects.count() % len(COLORES)]
    proyecto = Proyecto.objects.create(nombre=nombre, descripcion=(datos.get('descripcion') or '').strip(), color=color[:7],
                                       responsable=responsable, creado_por=usuario)
    miembros = {usuario.pk, responsable.pk} | {int(m) for m in datos.get('miembros') or []}
    proyecto.miembros.set(get_user_model().objects.filter(pk__in=miembros, is_active=True))
    columnas = datos.get('columnas') or COLUMNAS_INICIALES
    for orden, (nombre_col, final) in enumerate(columnas):
        Columna.objects.create(proyecto=proyecto, nombre=nombre_col, orden=orden, es_final=final)
    anotar(usuario, proyecto, f"Creó el proyecto «{proyecto.nombre}»")
    return proyecto


@con_respaldo(lambda p: p)
@transaction.atomic
def actualizar_proyecto(usuario, proyecto, datos):
    exigir_acceso(usuario, proyecto, administrar=True)
    cambios = {}
    if 'nombre' in datos:
        nuevo = _nombre_valido(datos['nombre'])
        if nuevo != proyecto.nombre:
            cambios['nombre'] = [proyecto.nombre, nuevo]
            proyecto.nombre = nuevo
    for campo in ('descripcion', 'color'):
        if campo in datos and (datos[campo] or '') != getattr(proyecto, campo):
            cambios[campo] = [getattr(proyecto, campo), datos[campo] or '']
            setattr(proyecto, campo, (datos[campo] or '')[:7] if campo == 'color' else (datos[campo] or ''))
    if 'estado' in datos and datos['estado'] != proyecto.estado:
        if datos['estado'] not in dict(Proyecto.ESTADO_CHOICES):
            raise ErrorGestion("Estado de proyecto no válido.")
        cambios['estado'] = [proyecto.get_estado_display(), dict(Proyecto.ESTADO_CHOICES)[datos['estado']]]
        proyecto.estado = datos['estado']
    if 'responsable' in datos:
        responsable = _usuario_activo(datos['responsable'])
        if responsable and responsable.pk != proyecto.responsable_id:
            cambios['responsable'] = [nombre_usuario(proyecto.responsable), nombre_usuario(responsable)]
            proyecto.responsable = responsable
    proyecto.save()
    if 'miembros' in datos:
        ids = {int(m) for m in datos['miembros'] or []} | {proyecto.responsable_id}
        antes = set(proyecto.miembros.values_list('pk', flat=True))
        if ids != antes:
            proyecto.miembros.set(get_user_model().objects.filter(pk__in=ids, is_active=True))
            cambios['miembros'] = [len(antes), len(ids)]
            # Quien deja el proyecto ya no queda como responsable de sus tareas
            Tarea.objects.filter(proyecto=proyecto, responsable__isnull=False).exclude(responsable_id__in=ids).update(responsable=None)
    elif 'responsable' in cambios:
        proyecto.miembros.add(proyecto.responsable)
    if cambios:
        anotar(usuario, proyecto, "Cambió la configuración del proyecto", cambios=cambios)
    return proyecto


def borrar_proyecto(usuario, proyecto):
    """Manda el proyecto a la papelera (se puede recuperar con todo su contenido)."""
    exigir_acceso(usuario, proyecto, administrar=True)
    proyecto.en_papelera_desde, proyecto.en_papelera_por = timezone.now(), nombre_usuario(usuario)
    proyecto.save(update_fields=['en_papelera_desde', 'en_papelera_por', 'actualizado_en'])
    anotar(usuario, proyecto, "Mandó el proyecto a la papelera")


def recuperar_proyecto(usuario, proyecto):
    exigir_acceso(usuario, proyecto, administrar=True)
    proyecto.en_papelera_desde, proyecto.en_papelera_por = None, ''
    proyecto.save(update_fields=['en_papelera_desde', 'en_papelera_por', 'actualizado_en'])
    anotar(usuario, proyecto, "Recuperó el proyecto de la papelera")


def eliminar_definitivo(usuario, proyecto):
    """Solo desde la papelera: borra el proyecto con su historial y sus versiones."""
    exigir_acceso(usuario, proyecto, administrar=True)
    if not proyecto.en_papelera_desde:
        raise ErrorGestion("Primero manda el proyecto a la papelera.")
    proyecto.delete()


@con_respaldo(lambda p: p)
@transaction.atomic
def guardar_linea_base(usuario, proyecto):
    exigir_acceso(usuario, proyecto)
    tareas = list(proyecto.tareas.all())
    for t in tareas:
        t.base_inicio, t.base_fin = t.inicio, t.fin
    Tarea.objects.bulk_update(tareas, ['base_inicio', 'base_fin'])
    proyecto.base_guardada_en = timezone.now()
    proyecto.save(update_fields=['base_guardada_en', 'actualizado_en'])
    anotar(usuario, proyecto, f"Guardó la línea base ({len(tareas)} tareas)")
    return len(tareas)


# ==============================================================================
# COLUMNAS Y ETIQUETAS
# ==============================================================================

@con_respaldo(lambda p: p)
@transaction.atomic
def guardar_columna(usuario, proyecto, datos, columna=None):
    exigir_acceso(usuario, proyecto, administrar=True)
    nombre = _nombre_valido(datos.get('nombre', columna.nombre if columna else ''), 'El nombre de la columna')[:60]
    limite = datos.get('limite', columna.limite if columna else None)
    try:
        limite = int(limite) if limite not in (None, '', 0, '0') else None
    except (TypeError, ValueError):
        raise ErrorGestion("El límite de tarjetas debe ser un número entero.")
    if columna is None:
        orden = (proyecto.columnas.aggregate(m=Max('orden'))['m'] or 0) + 1
        columna = Columna(proyecto=proyecto, orden=orden)
        descripcion = f"Agregó la columna «{nombre}»"
    else:
        descripcion = f"Cambió la columna «{columna.nombre}»"
    columna.nombre, columna.limite = nombre, limite
    if 'es_final' in datos:
        columna.es_final = bool(datos['es_final'])
    columna.save()
    if not proyecto.columnas.filter(es_final=False).exists():
        raise ErrorGestion("El tablero necesita al menos una columna que no sea final.")
    if 'posicion' in datos:
        ordenar_columnas(proyecto, columna, int(datos['posicion']))
    anotar(usuario, proyecto, descripcion)
    return columna


def ordenar_columnas(proyecto, columna, posicion):
    columnas = [c for c in proyecto.columnas.all() if c.pk != columna.pk]
    columnas.insert(max(0, min(posicion, len(columnas))), columna)
    for i, c in enumerate(columnas):
        c.orden = i
    Columna.objects.bulk_update(columnas, ['orden'])


@con_respaldo(lambda c: c.proyecto)
@transaction.atomic
def borrar_columna(usuario, columna):
    proyecto = columna.proyecto
    exigir_acceso(usuario, proyecto, administrar=True)
    otras = list(proyecto.columnas.exclude(pk=columna.pk))
    if not any(not c.es_final for c in otras):
        raise ErrorGestion("El tablero necesita al menos una columna que no sea final.")
    destino = next((c for c in reversed(otras) if c.orden < columna.orden), otras[0])
    movidas = columna.tareas.count()
    base = destino.tareas.aggregate(m=Max('orden_columna'))['m'] or 0
    for i, t in enumerate(columna.tareas.order_by('orden_columna')):
        t.columna, t.orden_columna = destino, base + i + 1
        _ajustar_por_columna(t)
        t.save()
    anotar(usuario, proyecto, f"Borró la columna «{columna.nombre}»" + (f"; sus {movidas} tarjetas pasaron a «{destino.nombre}»" if movidas else ''))
    columna.delete()


@con_respaldo(lambda p: p)
def guardar_etiqueta(usuario, proyecto, datos, etiqueta=None):
    exigir_acceso(usuario, proyecto)
    nombre = (datos.get('nombre', etiqueta.nombre if etiqueta else '') or '').strip()[:40]
    if not nombre:
        raise ErrorGestion("Escribe el nombre de la etiqueta.")
    nueva = etiqueta is None
    etiqueta = etiqueta or Etiqueta(proyecto=proyecto)
    antes = etiqueta.nombre
    etiqueta.nombre = nombre
    etiqueta.color = (datos.get('color') or etiqueta.color)[:7]
    etiqueta.save()
    anotar(usuario, proyecto, f"Creó la etiqueta «{nombre}»" if nueva else f"Cambió la etiqueta «{antes}»")
    return etiqueta


@con_respaldo(lambda e: e.proyecto)
def borrar_etiqueta(usuario, etiqueta):
    exigir_acceso(usuario, etiqueta.proyecto)
    anotar(usuario, etiqueta.proyecto, f"Borró la etiqueta «{etiqueta.nombre}»")
    etiqueta.delete()


# ==============================================================================
# TAREAS: fechas, dependencias y tablero
# ==============================================================================

def _fecha(valor, campo):
    if valor in (None, ''):
        return None
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        raise ErrorGestion(f"Fecha de {campo} no válida.")


def _es_resumen(tarea):
    return tarea.pk is not None and tarea.subtareas.exists()


def _columna_inicial(proyecto):
    return proyecto.columnas.filter(es_final=False).order_by('orden').first()


def _ajustar_por_columna(tarea):
    """Una tarjeta en columna final queda terminada (100 %); al salir de ella deja de estarlo."""
    if tarea.columna and tarea.columna.es_final:
        tarea.avance = 100
        tarea.completada_en = tarea.completada_en or timezone.now()
    else:
        tarea.completada_en = None
        if tarea.avance >= 100:
            tarea.avance = 90


def _ajustar_por_avance(tarea):
    """Llevar el avance a 100 % manda la tarjeta a la columna final; bajarlo la regresa a la última no final."""
    columnas = list(tarea.proyecto.columnas.all())
    if tarea.avance >= 100:
        final = next((c for c in columnas if c.es_final), None)
        if final and tarea.columna_id != final.pk:
            tarea.columna = final
            tarea.orden_columna = (final.tareas.aggregate(m=Max('orden_columna'))['m'] or 0) + 1
        tarea.completada_en = tarea.completada_en or timezone.now()
    else:
        tarea.completada_en = None
        if tarea.columna and tarea.columna.es_final:
            destino = [c for c in columnas if not c.es_final and c.orden < tarea.columna.orden] or [c for c in columnas if not c.es_final]
            tarea.columna = destino[-1] if destino else None


def _validar_fechas(tarea):
    if tarea.es_hito and tarea.inicio:
        tarea.fin = tarea.inicio
    if bool(tarea.inicio) != bool(tarea.fin):
        raise ErrorGestion("Indica inicio y fin, o deja ambas fechas vacías.")
    if tarea.inicio:
        tarea.inicio = habil_desde(tarea.inicio)
        if not tarea.es_hito:
            fin = tarea.fin
            while not es_habil(fin) and fin > tarea.inicio:
                fin -= timedelta(days=1)
            tarea.fin = max(fin, tarea.inicio)
        if tarea.fin < tarea.inicio:
            raise ErrorGestion("El fin no puede ser anterior al inicio.")
        for dep in tarea.dependencias_predecesoras.select_related('predecesora') if tarea.pk else []:
            minimo = inicio_minimo(dep.predecesora, dep.desfase_dias)
            if minimo and tarea.inicio < minimo:
                raise ErrorGestion(f"«{tarea.nombre}» no puede empezar antes del {minimo.strftime('%d/%m/%Y')}: depende de "
                                   f"«{dep.predecesora.nombre}».")


def propagar(tarea, movidas=None):
    """Empuja hacia adelante a las sucesoras que, por el nuevo fin de `tarea`, empezarían antes de lo permitido."""
    movidas = movidas if movidas is not None else []
    for dep in tarea.dependencias_sucesoras.select_related('sucesora'):
        suc = dep.sucesora
        minimo = inicio_minimo(tarea, dep.desfase_dias)
        if not minimo or not suc.inicio or suc.inicio >= minimo:
            continue
        dias = duracion(suc)
        suc.inicio, suc.fin = minimo, fin_por_duracion(minimo, dias, suc.es_hito)
        suc.save(update_fields=['inicio', 'fin', 'actualizado_en'])
        movidas.append(suc)
        propagar(suc, movidas)
    return movidas


def _orden_siguiente(proyecto, padre):
    return (proyecto.tareas.filter(padre=padre).aggregate(m=Max('orden'))['m'] or 0) + 1


def _validar_padre(tarea, padre):
    if padre is None:
        return
    if padre.proyecto_id != tarea.proyecto_id:
        raise ErrorGestion("La tarea resumen debe ser del mismo proyecto.")
    actual = padre
    while actual is not None:
        if tarea.pk and actual.pk == tarea.pk:
            raise ErrorGestion("Una tarea no puede quedar dentro de sí misma ni de sus subtareas.")
        actual = actual.padre
    if Dependencia.objects.filter(Q(predecesora=padre) | Q(sucesora=padre)).exists():
        raise ErrorGestion(f"«{padre.nombre}» tiene dependencias: quítalas antes de convertirla en tarea resumen.")


def _aplicar_datos(tarea, datos, proyecto):
    """Copia a la tarea los campos editables que vienen en `datos`; devuelve {campo: [antes, después]}."""
    cambios = {}

    def poner(campo, valor, texto=None):
        anterior = getattr(tarea, campo)
        if anterior != valor:
            cambios[campo] = [texto(anterior) if texto else _texto(anterior), texto(valor) if texto else _texto(valor)]
            setattr(tarea, campo, valor)

    if 'nombre' in datos:
        poner('nombre', _nombre_valido(datos['nombre'], 'El nombre de la tarea', minimo=1))
    if 'descripcion' in datos:
        poner('descripcion', (datos['descripcion'] or '').strip(), texto=lambda v: '(texto)' if v else None)
    if 'prioridad' in datos:
        if datos['prioridad'] not in dict(Tarea.PRIORIDAD_CHOICES):
            raise ErrorGestion("Prioridad no válida.")
        poner('prioridad', datos['prioridad'])
    if 'responsable' in datos:
        responsable = _usuario_activo(datos['responsable'])
        if responsable and not proyecto.miembros.filter(pk=responsable.pk).exists() and proyecto.responsable_id != responsable.pk:
            raise ErrorGestion("El responsable de la tarea debe ser miembro del proyecto.")
        poner('responsable', responsable, texto=lambda u: nombre_usuario(u) or None)
    if 'es_hito' in datos:
        poner('es_hito', bool(datos['es_hito']), texto=lambda v: 'Sí' if v else 'No')
    fechas = {k: _fecha(datos[k], k) for k in ('inicio', 'fin') if k in datos}
    if 'inicio' in fechas and 'fin' not in fechas and tarea.inicio and tarea.fin and fechas['inicio']:
        # Mover el inicio conserva la duración
        fechas['fin'] = fin_por_duracion(habil_desde(fechas['inicio']), duracion(tarea), tarea.es_hito)
    for campo, valor in fechas.items():
        poner(campo, valor)
    if 'avance' in datos:
        try:
            avance = int(round(float(datos['avance'])))
        except (TypeError, ValueError):
            raise ErrorGestion("El avance debe ser un número de 0 a 100.")
        poner('avance', max(0, min(100, avance)), texto=lambda v: f"{v} %")
    return cambios


@con_respaldo(lambda p: p)
@transaction.atomic
def crear_tarea(usuario, proyecto, datos):
    exigir_acceso(usuario, proyecto)
    padre = Tarea.objects.filter(pk=datos['padre'], proyecto=proyecto).first() if datos.get('padre') else None
    tarea = Tarea(proyecto=proyecto, creado_por=usuario, padre=padre)
    _validar_padre(tarea, padre)
    _aplicar_datos(tarea, {'nombre': datos.get('nombre'), **{k: v for k, v in datos.items() if k != 'nombre'}}, proyecto)
    columna = proyecto.columnas.filter(pk=datos['columna']).first() if datos.get('columna') else _columna_inicial(proyecto)
    tarea.columna = columna
    if columna:
        tarea.orden_columna = (columna.tareas.aggregate(m=Max('orden_columna'))['m'] or 0) + 1
    tarea.orden = _orden_siguiente(proyecto, padre)
    _validar_fechas(tarea)
    if columna and columna.es_final:
        _ajustar_por_columna(tarea)
    elif tarea.avance >= 100:
        _ajustar_por_avance(tarea)
    tarea.save()
    if 'etiquetas' in datos:
        tarea.etiquetas.set(proyecto.etiquetas.filter(pk__in=datos['etiquetas'] or []))
    if padre and padre.columna_id:
        padre.columna = None   # una tarea resumen no va en el tablero
        padre.save(update_fields=['columna'])
    anotar(usuario, proyecto, f"Creó la tarea «{tarea.nombre}»", tarea)
    return tarea


@con_respaldo(lambda t: t.proyecto)
@transaction.atomic
def actualizar_tarea(usuario, tarea, datos):
    """Aplica los cambios, valida fechas y dependencias y empuja a las sucesoras. Devuelve las tareas que se movieron."""
    proyecto = tarea.proyecto
    exigir_acceso(usuario, proyecto)
    resumen = _es_resumen(tarea)
    if resumen and any(k in datos for k in ('inicio', 'fin', 'avance', 'es_hito')):
        raise ErrorGestion("Las fechas y el avance de una tarea resumen salen de sus subtareas.")
    cambios = _aplicar_datos(tarea, datos, proyecto)
    if 'padre' in datos:
        padre = Tarea.objects.filter(pk=datos['padre'], proyecto=proyecto).first() if datos['padre'] else None
        if padre != tarea.padre:
            _validar_padre(tarea, padre)
            cambios['padre'] = [tarea.padre.nombre if tarea.padre else None, padre.nombre if padre else None]
            anterior = tarea.padre
            tarea.padre, tarea.orden = padre, _orden_siguiente(proyecto, padre)
            if padre and padre.columna_id:
                padre.columna = None
                padre.save(update_fields=['columna'])
            if anterior and not anterior.subtareas.exclude(pk=tarea.pk).exists() and not anterior.columna_id:
                anterior.columna = _columna_inicial(proyecto)   # vuelve a ser una tarea normal
                anterior.save(update_fields=['columna'])
    _validar_fechas(tarea)
    if 'avance' in cambios:
        _ajustar_por_avance(tarea)
    tarea.save()
    if 'etiquetas' in datos:
        antes = set(tarea.etiquetas.values_list('pk', flat=True))
        tarea.etiquetas.set(proyecto.etiquetas.filter(pk__in=datos['etiquetas'] or []))
        if antes != set(tarea.etiquetas.values_list('pk', flat=True)):
            cambios['etiquetas'] = [len(antes), tarea.etiquetas.count()]
    movidas = propagar(tarea) if ('inicio' in cambios or 'fin' in cambios or 'es_hito' in cambios) else []
    if cambios:
        anotar(usuario, proyecto, f"Cambió la tarea «{tarea.nombre}»" + (f"; se recorrieron {len(movidas)} sucesoras" if movidas else ''),
               tarea, cambios)
    return movidas


@con_respaldo(lambda t: t.proyecto)
@transaction.atomic
def borrar_tarea(usuario, tarea):
    proyecto = tarea.proyecto
    exigir_acceso(usuario, proyecto)
    n = tarea.subtareas.count()
    padre = tarea.padre
    anotar(usuario, proyecto, f"Borró la tarea «{tarea.nombre}»" + (f" y sus {n} subtareas" if n else ''))
    tarea.delete()
    if padre and not padre.subtareas.exists() and not padre.columna_id:
        padre.columna = _columna_inicial(proyecto)
        padre.save(update_fields=['columna'])


@con_respaldo(lambda t: t.proyecto)
@transaction.atomic
def mover_tarea(usuario, tarea, columna_id, posicion=None):
    """Mueve la tarjeta a otra columna (o dentro de la misma) en la posición indicada."""
    proyecto = tarea.proyecto
    exigir_acceso(usuario, proyecto)
    if _es_resumen(tarea):
        raise ErrorGestion("Una tarea resumen no va en el tablero: mueve sus subtareas.")
    columna = proyecto.columnas.filter(pk=columna_id).first()
    if not columna:
        raise ErrorGestion("La columna no existe en este proyecto.")
    otra_columna = columna.pk != tarea.columna_id
    if otra_columna and columna.limite and columna.tareas.count() >= columna.limite:
        raise ErrorGestion(f"La columna «{columna.nombre}» ya tiene su límite de {columna.limite} tarjetas.")
    anterior = tarea.columna
    tarjetas = [t for t in columna.tareas.order_by('orden_columna', 'id') if t.pk != tarea.pk]
    posicion = len(tarjetas) if posicion is None else max(0, min(int(posicion), len(tarjetas)))
    tarjetas.insert(posicion, tarea)
    tarea.columna = columna
    if otra_columna:
        _ajustar_por_columna(tarea)
    for i, t in enumerate(tarjetas):
        t.orden_columna = i
    Tarea.objects.bulk_update([t for t in tarjetas if t.pk != tarea.pk], ['orden_columna'])
    tarea.save()
    if otra_columna:
        anotar(usuario, proyecto, f"Movió «{tarea.nombre}» de «{anterior.nombre if anterior else '—'}» a «{columna.nombre}»", tarea,
               {'columna': [anterior.nombre if anterior else None, columna.nombre]})


@con_respaldo(lambda t: t.proyecto)
@transaction.atomic
def reordenar_tarea(usuario, tarea, posicion):
    """Cambia el orden de la tarea entre sus hermanas (lista y Gantt)."""
    exigir_acceso(usuario, tarea.proyecto)
    hermanas = [t for t in tarea.proyecto.tareas.filter(padre=tarea.padre).order_by('orden', 'id') if t.pk != tarea.pk]
    hermanas.insert(max(0, min(int(posicion), len(hermanas))), tarea)
    for i, t in enumerate(hermanas, start=1):
        t.orden = i
    Tarea.objects.bulk_update(hermanas, ['orden'])
    anotar(usuario, tarea.proyecto, f"Cambió el orden de «{tarea.nombre}»", tarea)


def _alcanzables(desde):
    """Tareas a las que se llega siguiendo sucesoras desde `desde` (para evitar ciclos)."""
    vistos, pila = set(), [desde.pk]
    while pila:
        actual = pila.pop()
        for suc in Dependencia.objects.filter(predecesora_id=actual).values_list('sucesora_id', flat=True):
            if suc not in vistos:
                vistos.add(suc)
                pila.append(suc)
    return vistos


@con_respaldo(lambda t: t.proyecto)
@transaction.atomic
def agregar_dependencia(usuario, sucesora, predecesora_id, desfase_dias=0):
    proyecto = sucesora.proyecto
    exigir_acceso(usuario, proyecto)
    predecesora = proyecto.tareas.filter(pk=predecesora_id).first()
    if not predecesora:
        raise ErrorGestion("La tarea predecesora no existe en este proyecto.")
    if predecesora.pk == sucesora.pk:
        raise ErrorGestion("Una tarea no puede depender de sí misma.")
    if _es_resumen(predecesora) or _es_resumen(sucesora):
        raise ErrorGestion("Las dependencias se ponen entre tareas, no con tareas resumen.")
    if Dependencia.objects.filter(predecesora=predecesora, sucesora=sucesora).exists():
        raise ErrorGestion("Esa dependencia ya existe.")
    if predecesora.pk in _alcanzables(sucesora):
        raise ErrorGestion(f"Se formaría un ciclo: «{predecesora.nombre}» ya depende de «{sucesora.nombre}».")
    try:
        desfase = int(desfase_dias or 0)
    except (TypeError, ValueError):
        raise ErrorGestion("El desfase debe ser un número entero de días hábiles.")
    dep = Dependencia.objects.create(predecesora=predecesora, sucesora=sucesora, desfase_dias=desfase)
    movidas = propagar(predecesora)
    anotar(usuario, proyecto, f"«{sucesora.nombre}» ahora depende de «{predecesora.nombre}»"
           + (f" (+{desfase} d)" if desfase > 0 else f" ({desfase} d)" if desfase < 0 else ''), sucesora)
    return dep, movidas


@con_respaldo(lambda d: d.sucesora.proyecto)
def quitar_dependencia(usuario, dependencia):
    proyecto = dependencia.sucesora.proyecto
    exigir_acceso(usuario, proyecto)
    anotar(usuario, proyecto, f"«{dependencia.sucesora.nombre}» ya no depende de «{dependencia.predecesora.nombre}»", dependencia.sucesora)
    dependencia.delete()


# ==============================================================================
# CHECKLIST Y COMENTARIOS
# ==============================================================================

@con_respaldo(lambda t: t.proyecto)
def agregar_checklist(usuario, tarea, texto):
    exigir_acceso(usuario, tarea.proyecto)
    texto = (texto or '').strip()[:300]
    if not texto:
        raise ErrorGestion("Escribe el elemento de la lista.")
    orden = (tarea.checklist.aggregate(m=Max('orden'))['m'] or 0) + 1
    elemento = ElementoChecklist.objects.create(tarea=tarea, texto=texto, orden=orden)
    anotar(usuario, tarea.proyecto, f"Agregó «{texto}» al checklist de «{tarea.nombre}»", tarea)
    return elemento


@con_respaldo(lambda e: e.tarea.proyecto)
def actualizar_checklist(usuario, elemento, datos):
    exigir_acceso(usuario, elemento.tarea.proyecto)
    if 'texto' in datos:
        texto = (datos['texto'] or '').strip()[:300]
        if not texto:
            raise ErrorGestion("Escribe el elemento de la lista.")
        elemento.texto = texto
    if 'hecho' in datos:
        elemento.hecho = bool(datos['hecho'])
    elemento.save()
    que = 'Marcó' if elemento.hecho else 'Desmarcó' if 'hecho' in datos else 'Cambió'
    anotar(usuario, elemento.tarea.proyecto, f"{que} «{elemento.texto}» en «{elemento.tarea.nombre}»", elemento.tarea)
    return elemento


@con_respaldo(lambda e: e.tarea.proyecto)
def borrar_checklist(usuario, elemento):
    exigir_acceso(usuario, elemento.tarea.proyecto)
    anotar(usuario, elemento.tarea.proyecto, f"Quitó «{elemento.texto}» del checklist de «{elemento.tarea.nombre}»", elemento.tarea)
    elemento.delete()


@con_respaldo(lambda t: t.proyecto)
def comentar(usuario, tarea, texto):
    exigir_acceso(usuario, tarea.proyecto)
    texto = (texto or '').strip()
    if not texto:
        raise ErrorGestion("Escribe el comentario.")
    comentario = Comentario.objects.create(tarea=tarea, autor=usuario, autor_nombre=nombre_usuario(usuario), texto=texto[:5000])
    anotar(usuario, tarea.proyecto, f"Comentó en «{tarea.nombre}»", tarea)
    return comentario


# ==============================================================================
# FOTOS DEL PROYECTO: deshacer, regresar a un punto y versiones
# ==============================================================================

def _iso(valor):
    return valor.isoformat() if valor else None


def foto_proyecto(proyecto):
    """Todo el contenido del proyecto en JSON (para deshacer, regresar o restaurar una versión)."""
    tareas = list(proyecto.tareas.prefetch_related('etiquetas'))
    ids = [t.pk for t in tareas]
    return {
        'formato': 1,
        'proyecto': {'nombre': proyecto.nombre, 'descripcion': proyecto.descripcion, 'color': proyecto.color,
                     'estado': proyecto.estado, 'responsable': proyecto.responsable_id,
                     'miembros': sorted(proyecto.miembros.values_list('pk', flat=True)),
                     'base_guardada_en': _iso(proyecto.base_guardada_en)},
        'columnas': [{'id': c.pk, 'nombre': c.nombre, 'orden': c.orden, 'es_final': c.es_final, 'limite': c.limite}
                     for c in proyecto.columnas.all()],
        'etiquetas': [{'id': e.pk, 'nombre': e.nombre, 'color': e.color} for e in proyecto.etiquetas.all()],
        'tareas': [{'id': t.pk, 'padre': t.padre_id, 'nombre': t.nombre, 'descripcion': t.descripcion, 'responsable': t.responsable_id,
                    'columna': t.columna_id, 'orden_columna': t.orden_columna, 'orden': t.orden, 'inicio': _iso(t.inicio),
                    'fin': _iso(t.fin), 'es_hito': t.es_hito, 'avance': t.avance, 'prioridad': t.prioridad,
                    'etiquetas': sorted(e.pk for e in t.etiquetas.all()), 'base_inicio': _iso(t.base_inicio),
                    'base_fin': _iso(t.base_fin), 'completada_en': _iso(t.completada_en), 'creado_por': t.creado_por_id,
                    'creado_en': _iso(t.creado_en)} for t in tareas],
        'dependencias': [{'id': d.pk, 'predecesora': d.predecesora_id, 'sucesora': d.sucesora_id, 'desfase_dias': d.desfase_dias}
                         for d in Dependencia.objects.filter(sucesora_id__in=ids)],
        'checklist': [{'id': c.pk, 'tarea': c.tarea_id, 'texto': c.texto, 'hecho': c.hecho, 'orden': c.orden}
                      for c in ElementoChecklist.objects.filter(tarea_id__in=ids)],
        'comentarios': [{'id': c.pk, 'tarea': c.tarea_id, 'autor': c.autor_id, 'autor_nombre': c.autor_nombre, 'texto': c.texto,
                         'creado_en': _iso(c.creado_en)} for c in Comentario.objects.filter(tarea_id__in=ids)],
    }


def _resumen_foto(foto):
    tareas = foto['tareas']
    padres = {t['padre'] for t in tareas if t['padre']}
    hojas = [t for t in tareas if t['id'] not in padres]
    return {'tareas': len(hojas), 'terminadas': sum(1 for t in hojas if t['avance'] >= 100),
            'avance': round(sum(t['avance'] for t in hojas) / len(hojas)) if hojas else 0}


def _sincronizar(modelo, existentes, filas, asignar, borrar=True):
    """Deja en la base exactamente `filas` (por id): actualiza las que existen, crea las que faltan y borra las demás."""
    por_id = {o.pk: o for o in existentes}
    vistos = set()
    for fila in filas:
        obj = por_id.get(fila['id']) or modelo(pk=fila['id'])
        asignar(obj, fila)
        obj.save()
        vistos.add(fila['id'])
    if borrar:
        modelo.objects.filter(pk__in=[pk for pk in por_id if pk not in vistos]).delete()
    return vistos


@transaction.atomic
def restaurar_foto(proyecto, foto):
    """Regresa el proyecto al contenido de `foto` conservando los ids (el historial sigue ligado a sus tareas)."""
    Usuario = get_user_model()
    usuarios = set(Usuario.objects.values_list('pk', flat=True))
    valido = lambda pk: pk if pk in usuarios else None
    fecha = lambda v: date.fromisoformat(v) if v else None
    momento = lambda v: datetime.fromisoformat(v) if v else None

    datos = foto['proyecto']
    proyecto.nombre, proyecto.descripcion, proyecto.color = datos['nombre'], datos['descripcion'], datos['color']
    proyecto.estado = datos['estado']
    if valido(datos['responsable']):
        proyecto.responsable_id = datos['responsable']
    proyecto.base_guardada_en = momento(datos['base_guardada_en'])
    proyecto.save()
    proyecto.miembros.set([pk for pk in datos['miembros'] if pk in usuarios])

    def columna(obj, f):
        obj.proyecto, obj.nombre, obj.orden, obj.es_final, obj.limite = proyecto, f['nombre'], f['orden'], f['es_final'], f['limite']
    def etiqueta(obj, f):
        obj.proyecto, obj.nombre, obj.color = proyecto, f['nombre'], f['color']
    _sincronizar(Columna, proyecto.columnas.all(), foto['columnas'], columna, borrar=False)
    _sincronizar(Etiqueta, proyecto.etiquetas.all(), foto['etiquetas'], etiqueta, borrar=False)

    def tarea(obj, f):
        obj.proyecto, obj.padre_id = proyecto, None      # el padre se pone después (puede crearse más adelante)
        obj.nombre, obj.descripcion, obj.responsable_id = f['nombre'], f['descripcion'], valido(f['responsable'])
        obj.columna_id, obj.orden_columna, obj.orden = f['columna'], f['orden_columna'], f['orden']
        obj.inicio, obj.fin, obj.es_hito, obj.avance, obj.prioridad = fecha(f['inicio']), fecha(f['fin']), f['es_hito'], f['avance'], f['prioridad']
        obj.base_inicio, obj.base_fin, obj.completada_en = fecha(f['base_inicio']), fecha(f['base_fin']), momento(f['completada_en'])
        obj.creado_por_id = valido(f['creado_por'])
    existentes = list(proyecto.tareas.all())
    Tarea.objects.filter(proyecto=proyecto).update(padre=None)    # evita que el borrado en cascada alcance a las que se quedan
    _sincronizar(Tarea, existentes, foto['tareas'], tarea)
    for f in foto['tareas']:
        Tarea.objects.filter(pk=f['id']).update(padre_id=f['padre'], creado_en=momento(f['creado_en']) or timezone.now())
        Tarea.objects.get(pk=f['id']).etiquetas.set(f['etiquetas'])
    proyecto.columnas.exclude(pk__in=[c['id'] for c in foto['columnas']]).delete()
    proyecto.etiquetas.exclude(pk__in=[e['id'] for e in foto['etiquetas']]).delete()

    ids = [t['id'] for t in foto['tareas']]
    def dependencia(obj, f):
        obj.predecesora_id, obj.sucesora_id, obj.desfase_dias = f['predecesora'], f['sucesora'], f['desfase_dias']
    def elemento(obj, f):
        obj.tarea_id, obj.texto, obj.hecho, obj.orden = f['tarea'], f['texto'], f['hecho'], f['orden']
    def comentario(obj, f):
        obj.tarea_id, obj.autor_id, obj.autor_nombre, obj.texto = f['tarea'], valido(f['autor']), f['autor_nombre'], f['texto']
    _sincronizar(Dependencia, Dependencia.objects.filter(sucesora_id__in=ids), foto['dependencias'], dependencia)
    _sincronizar(ElementoChecklist, ElementoChecklist.objects.filter(tarea_id__in=ids), foto['checklist'], elemento)
    _sincronizar(Comentario, Comentario.objects.filter(tarea_id__in=ids), foto['comentarios'], comentario)
    for f in foto['comentarios']:
        Comentario.objects.filter(pk=f['id']).update(creado_en=momento(f['creado_en']) or timezone.now())


def _crear_version(usuario, proyecto, nombre, datos, automatica=False):
    numero = (proyecto.versiones.aggregate(m=Max('numero'))['m'] or 0) + 1
    return VersionProyecto.objects.create(proyecto=proyecto, numero=numero, nombre=nombre[:200], automatica=automatica, datos=datos,
                                          resumen=_resumen_foto(datos), creado_por=usuario, creado_por_nombre=nombre_usuario(usuario))


def ultimo_deshacible(proyecto):
    """El cambio más reciente que aún no se deshace (los registros de "deshacer" no cuentan)."""
    return (proyecto.historial.filter(tipo__in=['CAMBIO', 'RESTAURAR'], deshecho=False).order_by('-id').first())


@transaction.atomic
def deshacer(usuario, proyecto):
    exigir_acceso(usuario, proyecto)
    ultimo = ultimo_deshacible(proyecto)
    if not ultimo:
        raise ErrorGestion("No hay cambios para deshacer.")
    if ultimo.estado_previo is None:
        raise ErrorGestion(f"«{ultimo.descripcion}» ya no se puede deshacer paso a paso: restaura una versión anterior.")
    actual = foto_proyecto(proyecto)
    restaurar_foto(proyecto, ultimo.estado_previo)
    ultimo.deshecho = True
    ultimo.save(update_fields=['deshecho'])
    if ultimo.tipo == 'RESTAURAR' and ultimo.deshace:
        # Deshacer un "regresar" vuelve a dejar vigentes los cambios que había marcado como deshechos
        Historial.objects.filter(id__in=ultimo.deshace).update(deshecho=False)
    anotar(usuario, proyecto, f"Deshizo: {ultimo.descripcion}", tipo='DESHACER', estado_previo=actual, deshace=[ultimo.pk])
    return ultimo


@transaction.atomic
def regresar(usuario, proyecto, historial_id):
    """Deja el proyecto como estaba justo antes de ese cambio (y deshace todos los posteriores)."""
    exigir_acceso(usuario, proyecto)
    punto = proyecto.historial.filter(pk=historial_id).first()
    if not punto:
        raise ErrorGestion("Ese cambio no es de este proyecto.")
    if punto.estado_previo is None:
        raise ErrorGestion("Ese cambio es muy antiguo para regresar a él: restaura una versión anterior.")
    actual = foto_proyecto(proyecto)
    _crear_version(usuario, proyecto, f"Antes de regresar a: {punto.descripcion}", actual, automatica=True)
    restaurar_foto(proyecto, punto.estado_previo)
    marcados = list(proyecto.historial.filter(id__gte=punto.pk, tipo__in=['CAMBIO', 'RESTAURAR'], deshecho=False)
                    .values_list('id', flat=True))
    Historial.objects.filter(id__in=marcados).update(deshecho=True)
    anotar(usuario, proyecto, f"Regresó el proyecto a antes de: {punto.descripcion}", tipo='RESTAURAR',
           estado_previo=actual, deshace=marcados)


def guardar_version(usuario, proyecto, nombre):
    exigir_acceso(usuario, proyecto)
    nombre = (nombre or '').strip() or f"Versión del {timezone.localtime().strftime('%d/%m/%Y %H:%M')}"
    version = _crear_version(usuario, proyecto, nombre, foto_proyecto(proyecto))
    anotar(usuario, proyecto, f"Guardó la versión {version.numero} «{version.nombre}»", tipo='CAMBIO')
    return version


@transaction.atomic
def restaurar_version(usuario, proyecto, version_id):
    exigir_acceso(usuario, proyecto)
    version = proyecto.versiones.filter(pk=version_id).first()
    if not version:
        raise ErrorGestion("La versión no es de este proyecto.")
    actual = foto_proyecto(proyecto)
    _crear_version(usuario, proyecto, f"Antes de restaurar la versión {version.numero}", actual, automatica=True)
    restaurar_foto(proyecto, version.datos)
    anotar(usuario, proyecto, f"Restauró la versión {version.numero} «{version.nombre}»", tipo='RESTAURAR', estado_previo=actual)
    return version


def lista_versiones(proyecto):
    return [{'id': v.pk, 'numero': v.numero, 'nombre': v.nombre, 'automatica': v.automatica, 'resumen': v.resumen,
             'creado_por': v.creado_por_nombre, 'creado_en': v.creado_en} for v in proyecto.versiones.all()[:200]]


def lista_historial(proyecto, tarea_id=None, limite=300):
    registros = proyecto.historial.all()
    if tarea_id:
        registros = registros.filter(tarea_id=tarea_id)
    registros = registros.defer('estado_previo').annotate(
        tiene_foto=ExpressionWrapper(Q(estado_previo__isnull=False), output_field=BooleanField()))
    return [{'id': h.pk, 'fecha': h.fecha, 'usuario': h.usuario_nombre, 'tarea': h.tarea_id, 'tarea_nombre': h.tarea_nombre,
             'descripcion': h.descripcion, 'cambios': h.cambios, 'tipo': h.tipo, 'deshecho': h.deshecho,
             'puede_regresar': h.tiene_foto} for h in registros[:limite]]


# ==============================================================================
# CÁLCULOS: resúmenes, ruta crítica, atraso contra la línea base
# ==============================================================================

def _ruta_critica(hojas, dependencias):
    """{tarea_id: holgura en días hábiles} de las tareas con fechas (CPM con las fechas vigentes como inicio temprano)."""
    con_fechas = {t.pk: t for t in hojas if t.inicio and t.fin}
    if not con_fechas:
        return {}
    es = {pk: indice_habil(t.inicio) for pk, t in con_fechas.items()}
    ef = {pk: es[pk] + duracion(t) - 1 for pk, t in con_fechas.items()}   # un hito termina "antes" de empezar
    fin_proyecto = max(ef.values())
    sucesoras = {}
    for d in dependencias:
        if d.predecesora_id in con_fechas and d.sucesora_id in con_fechas:
            sucesoras.setdefault(d.predecesora_id, []).append(d)
    lf = {}

    def tardio(pk, pila=()):
        if pk in lf:
            return lf[pk]
        limite = fin_proyecto
        for d in sucesoras.get(pk, []):
            if d.sucesora_id in pila:
                continue
            ls_suc = tardio(d.sucesora_id, pila + (pk,)) - (ef[d.sucesora_id] - es[d.sucesora_id])
            limite = min(limite, ls_suc - 1 - (d.desfase_dias or 0))
        lf[pk] = limite
        return limite

    return {pk: tardio(pk) - ef[pk] for pk in con_fechas}


def _ultimo_cambio(proyecto):
    h = (proyecto.historial.filter(tipo__in=['CAMBIO', 'RESTAURAR'], deshecho=False).defer('estado_previo')
         .annotate(tiene_foto=ExpressionWrapper(Q(estado_previo__isnull=False), output_field=BooleanField())).order_by('-id').first())
    return {'id': h.pk, 'descripcion': h.descripcion, 'usuario': h.usuario_nombre, 'fecha': h.fecha,
            'deshacible': h.tiene_foto} if h else None


def detalle_proyecto(proyecto, usuario, hoy=None):
    """Todo lo que pintan el Gantt y el tablero: tareas en orden de árbol con resúmenes, ruta crítica y atrasos."""
    hoy = hoy or timezone.localdate()
    tareas = list(proyecto.tareas.select_related('responsable').prefetch_related('etiquetas'))
    conteos = {r['pk']: r for r in proyecto.tareas.values('pk').annotate(
        n_check=Count('checklist', distinct=True), n_hecho=Count('checklist', filter=Q(checklist__hecho=True), distinct=True),
        n_coment=Count('comentarios', distinct=True))}
    dependencias = list(Dependencia.objects.filter(sucesora__proyecto=proyecto))
    hijos = {}
    for t in tareas:
        hijos.setdefault(t.padre_id, []).append(t)
    for lista in hijos.values():
        lista.sort(key=lambda t: (t.orden, t.pk))
    hojas = [t for t in tareas if t.pk not in hijos]
    holguras = _ruta_critica(hojas, dependencias)
    filas = []

    def recorrer(padre_id, nivel, prefijo):
        resultado = []
        for i, t in enumerate(hijos.get(padre_id, []), start=1):
            wbs = f"{prefijo}{i}"
            fila = {'id': t.pk, 'wbs': wbs, 'nivel': nivel, 'padre': t.padre_id, 'nombre': t.nombre, 'descripcion': t.descripcion,
                    'responsable': t.responsable_id, 'responsable_nombre': nombre_usuario(t.responsable),
                    'columna': t.columna_id, 'orden_columna': t.orden_columna, 'prioridad': t.prioridad, 'es_hito': t.es_hito,
                    'etiquetas': [e.pk for e in t.etiquetas.all()], 'resumen': t.pk in hijos,
                    'inicio': t.inicio, 'fin': t.fin, 'avance': t.avance, 'base_inicio': t.base_inicio, 'base_fin': t.base_fin,
                    'completada_en': t.completada_en, 'checklist': [conteos[t.pk]['n_hecho'], conteos[t.pk]['n_check']],
                    'comentarios': conteos[t.pk]['n_coment']}
            filas.append(fila)
            if t.pk in hijos:
                subfilas = recorrer(t.pk, nivel + 1, f"{wbs}.")
                fechas = [(f['inicio'], f['fin'], f['base_inicio'], f['base_fin']) for f in subfilas]
                inicios = [f[0] for f in fechas if f[0]]
                fines = [f[1] for f in fechas if f[1]]
                fila['inicio'] = min(inicios) if inicios else None
                fila['fin'] = max(fines) if fines else None
                bases_i = [f[2] for f in fechas if f[2]]
                bases_f = [f[3] for f in fechas if f[3]]
                fila['base_inicio'] = min(bases_i) if bases_i else None
                fila['base_fin'] = max(bases_f) if bases_f else None
                pesos = [(max(1, f['duracion']), f['avance']) for f in subfilas if f['padre'] == t.pk]
                fila['avance'] = round(sum(p * a for p, a in pesos) / sum(p for p, _ in pesos)) if pesos else 0
                fila['critica'] = any(f['critica'] for f in subfilas)
                fila['holgura'] = None
            else:
                fila['holgura'] = holguras.get(t.pk)
                fila['critica'] = fila['holgura'] is not None and fila['holgura'] <= 0
            fila['duracion'] = 0 if t.es_hito and not fila['resumen'] else dias_habiles(fila['inicio'], fila['fin'])
            fila['atraso'] = (indice_habil(fila['fin']) - indice_habil(fila['base_fin'])) if fila['fin'] and fila['base_fin'] else None
            fila['vencida'] = bool(fila['fin'] and fila['fin'] < hoy and fila['avance'] < 100)
            resultado.append(fila)
            if t.pk in hijos:
                resultado.extend(subfilas)
        return resultado

    recorrer(None, 0, '')
    hojas_filas = [f for f in filas if not f['resumen']]
    pesos = [(max(1, f['duracion']), f['avance']) for f in hojas_filas]
    inicios = [f['inicio'] for f in filas if f['inicio']]
    fines = [f['fin'] for f in filas if f['fin']]
    bases = [f['base_fin'] for f in filas if f['base_fin']]
    # Avance esperado a hoy (según la línea base, o las fechas vigentes si no hay): para decir si el proyecto va atrasado
    esperado = []
    for f in hojas_filas:
        ini, fin = (f['base_inicio'], f['base_fin']) if f['base_fin'] else (f['inicio'], f['fin'])
        if not ini or not fin:
            continue
        total = max(1, dias_habiles(ini, fin))
        hecho = 0 if hoy < ini else total if hoy > fin else dias_habiles(ini, hoy)
        esperado.append((max(1, f['duracion']), 100 * hecho / total))
    resumen = {
        'tareas': len(hojas_filas), 'terminadas': sum(1 for f in hojas_filas if f['avance'] >= 100),
        'vencidas': sum(1 for f in hojas_filas if f['vencida']),
        'avance': round(sum(p * a for p, a in pesos) / sum(p for p, _ in pesos)) if pesos else 0,
        'avance_esperado': round(sum(p * a for p, a in esperado) / sum(p for p, _ in esperado)) if esperado else None,
        'inicio': min(inicios) if inicios else None, 'fin': max(fines) if fines else None,
        'base_fin': max(bases) if bases else None,
        'atraso': (indice_habil(max(fines)) - indice_habil(max(bases))) if fines and bases else None,
    }
    return {
        'id': proyecto.pk, 'nombre': proyecto.nombre, 'descripcion': proyecto.descripcion, 'color': proyecto.color,
        'estado': proyecto.estado, 'estado_texto': proyecto.get_estado_display(),
        'responsable': proyecto.responsable_id, 'responsable_nombre': nombre_usuario(proyecto.responsable),
        'miembros': [{'id': u.pk, 'nombre': nombre_usuario(u), 'usuario': u.get_username()}
                     for u in proyecto.miembros.order_by('first_name', 'username')],
        'base_guardada_en': proyecto.base_guardada_en, 'hoy': hoy,
        'en_papelera_desde': proyecto.en_papelera_desde, 'en_papelera_por': proyecto.en_papelera_por,
        'ultimo_cambio': _ultimo_cambio(proyecto),
        'puede_administrar': puede_administrar(usuario, proyecto),
        'columnas': [{'id': c.pk, 'nombre': c.nombre, 'orden': c.orden, 'es_final': c.es_final, 'limite': c.limite}
                     for c in proyecto.columnas.all()],
        'etiquetas': [{'id': e.pk, 'nombre': e.nombre, 'color': e.color} for e in proyecto.etiquetas.all()],
        'dependencias': [{'id': d.pk, 'predecesora': d.predecesora_id, 'sucesora': d.sucesora_id, 'desfase_dias': d.desfase_dias}
                         for d in dependencias],
        'tareas': filas, 'resumen': resumen,
    }


def resumen_proyectos(usuario, incluir_archivados=False, hoy=None, papelera=False):
    """Tarjetas de la lista de proyectos: avance, vencidas, fin y atraso contra la línea base (o los de la papelera)."""
    hoy = hoy or timezone.localdate()
    proyectos = proyectos_visibles(usuario, papelera).select_related('responsable')
    if not incluir_archivados and not papelera:
        proyectos = proyectos.exclude(estado='ARCHIVADO')
    resultado = []
    for p in proyectos:
        d = detalle_proyecto(p, usuario, hoy)
        resultado.append({k: d[k] for k in ('id', 'nombre', 'descripcion', 'color', 'estado', 'estado_texto', 'responsable',
                                              'responsable_nombre', 'puede_administrar', 'resumen', 'en_papelera_desde',
                                              'en_papelera_por')}
                         | {'miembros': len(d['miembros'])})
    return resultado


def tareas_de(usuario, hoy=None):
    """«Mis tareas»: las tareas sin terminar asignadas al usuario en proyectos activos o en pausa."""
    hoy = hoy or timezone.localdate()
    tareas = (Tarea.objects.filter(responsable=usuario, completada_en__isnull=True, subtareas__isnull=True,
                                   proyecto__estado__in=['ACTIVO', 'PAUSADO'], proyecto__en_papelera_desde__isnull=True)
              .filter(Q(proyecto__responsable=usuario) | Q(proyecto__miembros=usuario)).distinct()
              .select_related('proyecto', 'columna').order_by('fin', 'proyecto__nombre', 'orden'))
    return [{'id': t.pk, 'nombre': t.nombre, 'proyecto': t.proyecto_id, 'proyecto_nombre': t.proyecto.nombre,
             'proyecto_color': t.proyecto.color, 'columna_nombre': t.columna.nombre if t.columna else '',
             'inicio': t.inicio, 'fin': t.fin, 'avance': t.avance, 'prioridad': t.prioridad, 'es_hito': t.es_hito,
             'vencida': bool(t.fin and t.fin < hoy)} for t in tareas]


def detalle_tarea(tarea):
    """Lo que muestra la ventana de la tarea: checklist, comentarios, dependencias e historial."""
    return {
        'id': tarea.pk,
        'checklist': [{'id': c.pk, 'texto': c.texto, 'hecho': c.hecho} for c in tarea.checklist.all()],
        'comentarios': [{'id': c.pk, 'autor': c.autor_nombre, 'texto': c.texto, 'fecha': c.creado_en} for c in tarea.comentarios.all()],
        'predecesoras': [{'id': d.pk, 'tarea': d.predecesora_id, 'nombre': d.predecesora.nombre, 'desfase_dias': d.desfase_dias}
                         for d in tarea.dependencias_predecesoras.select_related('predecesora')],
        'sucesoras': [{'id': d.pk, 'tarea': d.sucesora_id, 'nombre': d.sucesora.nombre, 'desfase_dias': d.desfase_dias}
                      for d in tarea.dependencias_sucesoras.select_related('sucesora')],
        'historial': lista_historial(tarea.proyecto, tarea.pk, 50),
    }
