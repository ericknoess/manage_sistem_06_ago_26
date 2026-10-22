# core/estaticos.py — Versión en la URL de cada archivo estático para que el navegador no use copias viejas.
#
# {% static 'core/js/utils.js' %} → /static/core/js/utils.js?v=3f9a1c2e
# La versión es un fragmento del hash del contenido: cambia solo cuando el archivo cambia, así que tras
# una actualización el navegador descarga lo nuevo y lo demás sigue saliendo de su caché.

import hashlib
import os

from django.contrib.staticfiles import finders
from django.core.exceptions import ImproperlyConfigured
from django.contrib.staticfiles.storage import StaticFilesStorage

# {ruta absoluta: (fecha de modificación, versión)}; se recalcula solo si el archivo cambió
_versiones = {}


def _ruta_del_archivo(storage, nombre):
    """El archivo publicado (tras collectstatic) o, en desarrollo, el que sirve la app o static/."""
    try:
        ruta = storage.path(nombre)
        if os.path.exists(ruta):
            return ruta
    except (ImproperlyConfigured, NotImplementedError):
        pass  # sin STATIC_ROOT (desarrollo): se busca en las carpetas static de las apps
    return finders.find(nombre)


def version_de(ruta):
    modificado = os.path.getmtime(ruta)
    guardada = _versiones.get(ruta)
    if guardada and guardada[0] == modificado:
        return guardada[1]
    with open(ruta, 'rb') as archivo:
        version = hashlib.md5(archivo.read(), usedforsecurity=False).hexdigest()[:8]
    _versiones[ruta] = (modificado, version)
    return version


class EstaticosVersionados(StaticFilesStorage):
    def url(self, name):
        url = super().url(name)
        ruta = _ruta_del_archivo(self, name) if name else None
        if not ruta or isinstance(ruta, list):
            return url
        return f"{url}{'&' if '?' in url else '?'}v={version_de(ruta)}"
