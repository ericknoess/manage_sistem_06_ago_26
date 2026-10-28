# eventos/views.py — API de eventos GMP (/api/eventos/) y la pantalla /eventos/.
#
# Leer y reportar: usuario web o persona que entró con su PIN en /mobile/. Cerrar y anular: permiso
# `evaluar_evento` y firma electrónica (contraseña); la regla de cuatro ojos la revisa services.py.

from datetime import datetime

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from auditoria.services import quien
from usuarios.firmas import FirmaRechazada, verificar_firma
from usuarios.permisos import PermisoUsuarioOTerminal, tiene_permiso

from .models import EventoGMP
from .serializers import EventoGMPSerializer
from .services import (ErrorEvento, anular_evento, cerrar_evento, reportar_evento, validar_anulacion, validar_cierre)

LIMITE_LISTA = 500


def _fecha_hora(valor):
    """'2026-10-28T14:05' (local) o ISO con zona → datetime con zona; vacío → None."""
    if not valor:
        return None
    try:
        momento = datetime.fromisoformat(str(valor).replace('Z', '+00:00'))
    except ValueError:
        raise ErrorEvento("La fecha y hora del evento no tiene un formato válido.")
    return timezone.make_aware(momento) if timezone.is_naive(momento) else momento


class EventoGMPViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET  /api/eventos/?lote=&estado=&tipo=&desde=&hasta=&q=   lista (más recientes primero, hasta 500)
    GET  /api/eventos/resumen/?lote=                           conteo por estado
    GET  /api/eventos/opciones/                                tipos, estados y clasificaciones
    POST /api/eventos/                                         reportar {lote | fase, tipo, titulo, descripcion, accion_inmediata, ocurrio_en, equipo}
    POST /api/eventos/<id>/cerrar/                             {clasificacion, evaluacion, numero_desviacion, firma_password}
    POST /api/eventos/<id>/anular/                             {motivo, firma_password}
    """
    serializer_class = EventoGMPSerializer
    permission_classes = [PermisoUsuarioOTerminal]

    def get_queryset(self):
        qs = (EventoGMP.objects.select_related('lote', 'fase__operacion_maestra', 'equipo', 'valor__parametro',
                                               'registro_cierre__firma', 'reportado_por_usuario__perfil',
                                               'reportado_por_operador__usuario_sistema'))
        p = self.request.query_params
        if p.get('lote'):
            qs = qs.filter(lote_id=p['lote'])
        if p.get('fase'):
            qs = qs.filter(fase_id=p['fase'])
        if p.get('estado'):
            qs = qs.filter(estado__in=p['estado'].split(','))
        if p.get('tipo'):
            qs = qs.filter(tipo=p['tipo'])
        if p.get('desde'):
            qs = qs.filter(ocurrio_en__date__gte=p['desde'])
        if p.get('hasta'):
            qs = qs.filter(ocurrio_en__date__lte=p['hasta'])
        if p.get('q'):
            t = p['q'].strip()
            qs = qs.filter(Q(folio__icontains=t) | Q(titulo__icontains=t) | Q(lote__identificador_lote__icontains=t)
                           | Q(numero_desviacion__icontains=t) | Q(descripcion__icontains=t))
        return qs

    def get_serializer_context(self):
        contexto = super().get_serializer_context()
        usuario, operador, _, _ = quien(self.request)
        contexto['quien'] = (usuario, operador)
        return contexto

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        total = qs.count()
        datos = self.get_serializer(qs[:LIMITE_LISTA], many=True).data
        return Response({'total': total, 'limite': LIMITE_LISTA, 'eventos': datos})

    @action(detail=False, methods=['get'])
    def resumen(self, request):
        qs = EventoGMP.objects.all()
        if request.query_params.get('lote'):
            qs = qs.filter(lote_id=request.query_params['lote'])
        conteo = dict(qs.values_list('estado').annotate(n=Count('id')))
        return Response({e: conteo.get(e, 0) for e, _ in EventoGMP.ESTADO_CHOICES})

    @action(detail=False, methods=['get'])
    def opciones(self, request):
        usuario = request.user if request.user.is_authenticated else None
        return Response({
            'tipos': [{'valor': v, 'nombre': n} for v, n in EventoGMP.TIPO_CHOICES],
            'tipos_manuales': [{'valor': v, 'nombre': n} for v, n in EventoGMP.TIPO_CHOICES if v != 'INICIO_FUERA_VENTANA'],
            'estados': [{'valor': v, 'nombre': n} for v, n in EventoGMP.ESTADO_CHOICES],
            'clasificaciones': [{'valor': v, 'nombre': n} for v, n in EventoGMP.CLASIFICACION_CHOICES],
            'puede_evaluar': tiene_permiso(usuario, 'evaluar_evento'),
        })

    @staticmethod
    def _error(mensaje, estado=status.HTTP_400_BAD_REQUEST):
        return Response({'error': mensaje}, status=estado)

    def create(self, request, *args, **kwargs):
        from actividades.models import Equipo
        from procesos.models import FaseLote, LoteProduccion
        d = request.data
        try:
            fase = FaseLote.objects.select_related('lote', 'operacion_maestra').filter(pk=d.get('fase')).first() if d.get('fase') else None
            lote = LoteProduccion.objects.filter(pk=d.get('lote')).first() if d.get('lote') else None
            if d.get('fase') and not fase:
                raise ErrorEvento("La tarea no existe.")
            if d.get('lote') and not lote:
                raise ErrorEvento("El lote no existe.")
            equipo = Equipo.objects.filter(pk=d.get('equipo')).first() if d.get('equipo') else None
            if d.get('equipo') and not equipo:
                raise ErrorEvento("El equipo no existe.")
            evento = reportar_evento(request, lote=lote, fase=fase, tipo=d.get('tipo'), titulo=d.get('titulo'),
                                     descripcion=d.get('descripcion'), accion_inmediata=d.get('accion_inmediata'),
                                     ocurrio_en=_fecha_hora(d.get('ocurrio_en')), equipo=equipo)
        except ErrorEvento as e:
            return self._error(str(e))
        return Response(self.get_serializer(evento).data, status=status.HTTP_201_CREATED)

    def _evaluar(self, request, accion, validar, ejecutar):
        """Permiso → reglas → firma → acción. La firma se pide al final para que un error de captura no cuente como intento fallido."""
        if not tiene_permiso(request.user, 'evaluar_evento'):
            return self._error("Tu rol no permite evaluar eventos GMP.", status.HTTP_403_FORBIDDEN)
        evento = self.get_object()
        try:
            validar(evento)
            firmante = verificar_firma(request, accion)
            evento = ejecutar(evento, firmante)
        except ErrorEvento as e:
            return self._error(str(e))
        except FirmaRechazada as e:
            return Response(e.como_respuesta(), status=e.estado_http)
        return Response(self.get_serializer(evento).data)

    @action(detail=True, methods=['post'])
    def cerrar(self, request, pk=None):
        d = request.data
        datos = {'clasificacion': d.get('clasificacion'), 'evaluacion': d.get('evaluacion') or '',
                 'numero_desviacion': d.get('numero_desviacion') or ''}
        return self._evaluar(request, 'CERRAR_EVENTO',
                             lambda ev: validar_cierre(ev, request, **datos),
                             lambda ev, firmante: cerrar_evento(request, ev, firmante, **datos))

    @action(detail=True, methods=['post'])
    def anular(self, request, pk=None):
        motivo = request.data.get('motivo') or ''
        return self._evaluar(request, 'ANULAR_EVENTO',
                             lambda ev: validar_anulacion(ev, request, motivo),
                             lambda ev, firmante: anular_evento(request, ev, firmante, motivo=motivo))
