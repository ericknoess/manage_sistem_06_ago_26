# gestion/views.py — API de proyectos, tareas y tableros de oficina (no GMP).
#
# Solo usuarios web con sesión. Las reglas de quién puede ver o modificar cada proyecto (miembros, responsable,
# administradores) están en services.py; por eso las acciones de escritura se declaran SOLO_SESION.
# Cada escritura responde poco ({ok, mensaje, ...}): la pantalla vuelve a pedir el proyecto completo.

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from usuarios.permisos import SOLO_SESION

from . import services
from .models import Columna, Dependencia, ElementoChecklist, Etiqueta, Proyecto, Tarea
from .services import ErrorGestion


def _error(e):
    return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


def _sesion(*acciones):
    return {a: SOLO_SESION for a in acciones}


class ProyectoPaginaView(TemplateView):
    template_name = 'gestion/proyecto.html'


class ProyectoViewSet(viewsets.ViewSet):
    """/api/gestion/proyectos/: lista, detalle (Gantt y tablero), alta, cambios, borrado, línea base e historial."""
    permisos_por_accion = _sesion('create', 'partial_update', 'destroy', 'linea_base', 'deshacer', 'regresar', 'versiones',
                                  'restaurar_version', 'recuperar', 'eliminar_definitivo')

    def _proyecto(self, request, pk):
        proyecto = get_object_or_404(Proyecto.objects.select_related('responsable'), pk=pk)
        if not services.puede_ver(request.user, proyecto):
            raise services.ErrorGestion("No eres miembro de este proyecto.")
        return proyecto

    def list(self, request):
        q = request.query_params
        return Response(services.resumen_proyectos(request.user, q.get('archivados') == '1', papelera=q.get('papelera') == '1'))

    def retrieve(self, request, pk=None):
        try:
            return Response(services.detalle_proyecto(self._proyecto(request, pk), request.user))
        except ErrorGestion as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)

    def create(self, request):
        try:
            proyecto = services.crear_proyecto(request.user, request.data)
        except ErrorGestion as e:
            return _error(e)
        return Response({'id': proyecto.pk, 'mensaje': f"Proyecto «{proyecto.nombre}» creado."}, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        try:
            services.actualizar_proyecto(request.user, self._proyecto(request, pk), request.data)
        except ErrorGestion as e:
            return _error(e)
        return Response({'ok': True})

    def destroy(self, request, pk=None):
        try:
            services.borrar_proyecto(request.user, self._proyecto(request, pk))
        except ErrorGestion as e:
            return _error(e)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='linea-base')
    def linea_base(self, request, pk=None):
        try:
            n = services.guardar_linea_base(request.user, self._proyecto(request, pk))
        except ErrorGestion as e:
            return _error(e)
        return Response({'ok': True, 'mensaje': f"Línea base guardada con {n} tareas."})

    @action(detail=True, methods=['get'], url_path='historial')
    def historial(self, request, pk=None):
        """Quién cambió qué y cuándo (?tarea=<id> para una tarea), con los cambios a los que se puede regresar."""
        try:
            proyecto = self._proyecto(request, pk)
        except ErrorGestion as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
        return Response(services.lista_historial(proyecto, request.query_params.get('tarea')))

    def _accion(self, request, pk, funcion, mensaje):
        try:
            resultado = funcion(self._proyecto(request, pk))
        except ErrorGestion as e:
            return _error(e)
        return Response({'ok': True, 'mensaje': mensaje(resultado) if callable(mensaje) else mensaje})

    @action(detail=True, methods=['post'])
    def deshacer(self, request, pk=None):
        return self._accion(request, pk, lambda p: services.deshacer(request.user, p), lambda h: f"Se deshizo: {h.descripcion}")

    @action(detail=True, methods=['post'])
    def regresar(self, request, pk=None):
        return self._accion(request, pk, lambda p: services.regresar(request.user, p, request.data.get('historial')),
                            "El proyecto regresó a ese punto. El estado anterior quedó guardado como versión.")

    @action(detail=True, methods=['get', 'post'])
    def versiones(self, request, pk=None):
        """GET: versiones guardadas. POST {nombre}: guarda la versión actual."""
        if request.method == 'GET':
            try:
                return Response(services.lista_versiones(self._proyecto(request, pk)))
            except ErrorGestion as e:
                return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
        return self._accion(request, pk, lambda p: services.guardar_version(request.user, p, request.data.get('nombre')),
                            lambda v: f"Versión {v.numero} «{v.nombre}» guardada.")

    @action(detail=True, methods=['post'], url_path='restaurar-version')
    def restaurar_version(self, request, pk=None):
        return self._accion(request, pk, lambda p: services.restaurar_version(request.user, p, request.data.get('version')),
                            lambda v: f"Se restauró la versión {v.numero}. El estado anterior quedó guardado como versión.")

    @action(detail=True, methods=['post'])
    def recuperar(self, request, pk=None):
        return self._accion(request, pk, lambda p: services.recuperar_proyecto(request.user, p), "Proyecto recuperado de la papelera.")

    @action(detail=True, methods=['post'], url_path='eliminar-definitivo')
    def eliminar_definitivo(self, request, pk=None):
        return self._accion(request, pk, lambda p: services.eliminar_definitivo(request.user, p), "Proyecto eliminado definitivamente.")

    @action(detail=False, methods=['get'], url_path='usuarios')
    def usuarios(self, request):
        """Usuarios web activos que se pueden agregar como miembros o responsables."""
        usuarios = get_user_model().objects.filter(is_active=True).order_by('first_name', 'last_name', 'username')
        return Response([{'id': u.pk, 'nombre': services.nombre_usuario(u), 'usuario': u.get_username()} for u in usuarios])


class TareaViewSet(viewsets.ViewSet):
    """/api/gestion/tareas/: «mis tareas» (?mias=1), detalle, alta, cambios, borrado, mover en el tablero,
    reordenar, dependencias, checklist y comentarios."""
    permisos_por_accion = _sesion('create', 'partial_update', 'destroy', 'mover', 'reordenar', 'dependencias', 'checklist',
                                  'comentarios')

    def _tarea(self, request, pk):
        tarea = get_object_or_404(Tarea.objects.select_related('proyecto'), pk=pk)
        if not services.puede_ver(request.user, tarea.proyecto):
            raise ErrorGestion("No eres miembro de este proyecto.")
        return tarea

    def list(self, request):
        return Response(services.tareas_de(request.user))

    def retrieve(self, request, pk=None):
        try:
            return Response(services.detalle_tarea(self._tarea(request, pk)))
        except ErrorGestion as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)

    def create(self, request):
        proyecto = get_object_or_404(Proyecto, pk=request.data.get('proyecto'))
        try:
            tarea = services.crear_tarea(request.user, proyecto, request.data)
        except ErrorGestion as e:
            return _error(e)
        return Response({'id': tarea.pk, 'mensaje': f"Tarea «{tarea.nombre}» creada."}, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        try:
            movidas = services.actualizar_tarea(request.user, self._tarea(request, pk), request.data)
        except ErrorGestion as e:
            return _error(e)
        return Response({'ok': True, 'movidas': [t.nombre for t in movidas]})

    def destroy(self, request, pk=None):
        try:
            services.borrar_tarea(request.user, self._tarea(request, pk))
        except ErrorGestion as e:
            return _error(e)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def mover(self, request, pk=None):
        try:
            services.mover_tarea(request.user, self._tarea(request, pk), request.data.get('columna'), request.data.get('posicion'))
        except ErrorGestion as e:
            return _error(e)
        return Response({'ok': True})

    @action(detail=True, methods=['post'])
    def reordenar(self, request, pk=None):
        try:
            services.reordenar_tarea(request.user, self._tarea(request, pk), request.data.get('posicion', 0))
        except (ErrorGestion, ValueError) as e:
            return _error(e)
        return Response({'ok': True})

    @action(detail=True, methods=['post'])
    def dependencias(self, request, pk=None):
        try:
            _, movidas = services.agregar_dependencia(request.user, self._tarea(request, pk), request.data.get('predecesora'),
                                                      request.data.get('desfase_dias', 0))
        except ErrorGestion as e:
            return _error(e)
        return Response({'ok': True, 'movidas': [t.nombre for t in movidas]}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def checklist(self, request, pk=None):
        try:
            elemento = services.agregar_checklist(request.user, self._tarea(request, pk), request.data.get('texto'))
        except ErrorGestion as e:
            return _error(e)
        return Response({'id': elemento.pk}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def comentarios(self, request, pk=None):
        try:
            comentario = services.comentar(request.user, self._tarea(request, pk), request.data.get('texto'))
        except ErrorGestion as e:
            return _error(e)
        return Response({'id': comentario.pk}, status=status.HTTP_201_CREATED)


class _ElementoViewSet(viewsets.ViewSet):
    """Base de los elementos sueltos de un proyecto (columnas, etiquetas, dependencias, checklist)."""
    modelo = None
    permisos_por_accion = _sesion('create', 'partial_update', 'destroy')

    def _proyecto_de(self, obj):
        raise NotImplementedError

    def _objeto(self, request, pk):
        obj = get_object_or_404(self.modelo, pk=pk)
        if not services.puede_ver(request.user, self._proyecto_de(obj)):
            raise ErrorGestion("No eres miembro de este proyecto.")
        return obj


class ColumnaViewSet(_ElementoViewSet):
    modelo = Columna

    def _proyecto_de(self, obj):
        return obj.proyecto

    def create(self, request):
        proyecto = get_object_or_404(Proyecto, pk=request.data.get('proyecto'))
        try:
            columna = services.guardar_columna(request.user, proyecto, request.data)
        except ErrorGestion as e:
            return _error(e)
        return Response({'id': columna.pk}, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        try:
            columna = self._objeto(request, pk)
            services.guardar_columna(request.user, columna.proyecto, request.data, columna)
        except (ErrorGestion, ValueError) as e:
            return _error(e)
        return Response({'ok': True})

    def destroy(self, request, pk=None):
        try:
            services.borrar_columna(request.user, self._objeto(request, pk))
        except ErrorGestion as e:
            return _error(e)
        return Response(status=status.HTTP_204_NO_CONTENT)


class EtiquetaViewSet(_ElementoViewSet):
    modelo = Etiqueta

    def _proyecto_de(self, obj):
        return obj.proyecto

    def create(self, request):
        proyecto = get_object_or_404(Proyecto, pk=request.data.get('proyecto'))
        try:
            etiqueta = services.guardar_etiqueta(request.user, proyecto, request.data)
        except ErrorGestion as e:
            return _error(e)
        return Response({'id': etiqueta.pk}, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        try:
            etiqueta = self._objeto(request, pk)
            services.guardar_etiqueta(request.user, etiqueta.proyecto, request.data, etiqueta)
        except ErrorGestion as e:
            return _error(e)
        return Response({'ok': True})

    def destroy(self, request, pk=None):
        try:
            services.borrar_etiqueta(request.user, self._objeto(request, pk))
        except ErrorGestion as e:
            return _error(e)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DependenciaViewSet(_ElementoViewSet):
    modelo = Dependencia
    permisos_por_accion = _sesion('destroy')

    def _proyecto_de(self, obj):
        return obj.sucesora.proyecto

    def destroy(self, request, pk=None):
        try:
            services.quitar_dependencia(request.user, self._objeto(request, pk))
        except ErrorGestion as e:
            return _error(e)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChecklistViewSet(_ElementoViewSet):
    modelo = ElementoChecklist
    permisos_por_accion = _sesion('partial_update', 'destroy')

    def _proyecto_de(self, obj):
        return obj.tarea.proyecto

    def partial_update(self, request, pk=None):
        try:
            services.actualizar_checklist(request.user, self._objeto(request, pk), request.data)
        except ErrorGestion as e:
            return _error(e)
        return Response({'ok': True})

    def destroy(self, request, pk=None):
        try:
            services.borrar_checklist(request.user, self._objeto(request, pk))
        except ErrorGestion as e:
            return _error(e)
        return Response(status=status.HTTP_204_NO_CONTENT)
