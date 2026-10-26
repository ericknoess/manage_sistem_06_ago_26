# datos_proceso/planes.py — Planes de captura compactos.
#
# Cada fase (FaseLote.plan_captura) y cada toma (TomaDatos.plan) guardan qué se pidió, con los parámetros de cada
# sección tal como eran (snapshot con límites y curva). Un lote de mil tareas repetiría esas listas mil veces, así que
# cada lista se guarda una sola vez en `PlanParametros`, identificada por su huella SHA-256 (es inmutable: misma huella,
# mismo contenido), y la sección guarda solo `parametros_ref`. Al leer, `expandir_plan` devuelve el plan completo, igual
# que antes. Los planes viejos con `parametros` en línea se siguen leyendo tal cual.

import copy
import hashlib
import json

_CACHE = {}          # huella -> parametros (seguro: el contenido de una huella nunca cambia)
_MAX_CACHE = 5000


def huella_parametros(parametros):
    texto = json.dumps(parametros, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()


def _modelo(modelo):
    if modelo is not None:
        return modelo
    from .models import PlanParametros
    return PlanParametros


def _recordar(huella, parametros):
    if len(_CACHE) >= _MAX_CACHE:
        _CACHE.clear()
    _CACHE[huella] = parametros


def compactar_planes(planes, modelo=None):
    """Planes con las listas de parámetros cambiadas por su huella (guarda las listas nuevas en una sola consulta)."""
    modelo = _modelo(modelo)
    nuevos, listas = [], {}
    for plan in planes:
        if not plan or not plan.get('secciones'):
            nuevos.append(plan or {})
            continue
        secciones = []
        for seccion in plan['secciones']:
            seccion = dict(seccion)
            if 'parametros' in seccion:
                parametros = seccion.pop('parametros')
                huella = huella_parametros(parametros)
                listas[huella] = parametros
                seccion['parametros_ref'] = huella
            secciones.append(seccion)
        nuevos.append({**plan, 'secciones': secciones})
    if listas:
        existentes = set(modelo.objects.filter(huella__in=list(listas)).values_list('huella', flat=True))
        modelo.objects.bulk_create([modelo(huella=h, parametros=p) for h, p in listas.items() if h not in existentes],
                                   ignore_conflicts=True)
        for h, p in listas.items():
            _recordar(h, p)
    return nuevos


def compactar_plan(plan, modelo=None):
    return compactar_planes([plan], modelo)[0]


def _cargar(huellas, modelo=None):
    faltan = [h for h in huellas if h not in _CACHE]
    if faltan:
        for h, p in _modelo(modelo).objects.filter(huella__in=faltan).values_list('huella', 'parametros'):
            _recordar(h, p)


def parametros_de_seccion(seccion, modelo=None):
    """La lista de parámetros de una sección (en línea o por huella). Es la copia en memoria: no modificarla."""
    if 'parametros' in seccion:
        return seccion['parametros']
    ref = seccion['parametros_ref']
    if ref not in _CACHE:
        _cargar([ref], modelo)
        if ref not in _CACHE:
            raise LookupError(f"Falta la lista de parámetros {ref[:12]}… del plan de captura.")
    return _CACHE[ref]


def expandir_planes(planes, modelo=None):
    """Planes completos (cada sección con su lista `parametros`); copias, se pueden modificar sin riesgo."""
    planes = list(planes)
    _cargar({s['parametros_ref'] for plan in planes for s in (plan or {}).get('secciones', []) if 'parametros_ref' in s}, modelo)
    resultado = []
    for plan in planes:
        if not plan or not plan.get('secciones'):
            resultado.append(copy.deepcopy(plan or {}))
            continue
        secciones = []
        for seccion in plan['secciones']:
            seccion = copy.deepcopy(seccion)
            ref = seccion.pop('parametros_ref', None)
            if ref is not None:
                if ref not in _CACHE:
                    raise LookupError(f"Falta la lista de parámetros {ref[:12]}… del plan de captura.")
                seccion['parametros'] = copy.deepcopy(_CACHE[ref])
            secciones.append(seccion)
        resultado.append({**plan, 'secciones': secciones})
    return resultado


def expandir_plan(plan, modelo=None):
    return expandir_planes([plan], modelo)[0]
