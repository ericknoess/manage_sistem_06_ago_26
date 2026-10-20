# auditoria/views.py

from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import RegistroAuditoria
from .serializers import RegistroAuditoriaSerializer

LIMITE_POR_DEFECTO = 200
LIMITE_MAXIMO = 1000


class RegistroAuditoriaViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Bitácora de auditoría, solo lectura (nadie la puede modificar por la API).
    Filtros: ?lote=<id> ?fase=<id> ?categoria= ?accion= ?usuario=<id> ?operador=<id>
             ?desde=YYYY-MM-DD ?hasta=YYYY-MM-DD ?q=<texto> ?limite=<n, máx. 1000>
    """
    serializer_class = RegistroAuditoriaSerializer

    def get_queryset(self):
        qs = RegistroAuditoria.objects.select_related('fase__operacion_maestra')
        p = self.request.query_params
        for campo in ('lote', 'fase', 'categoria', 'accion', 'usuario', 'operador'):
            if p.get(campo):
                qs = qs.filter(**{campo: p[campo]})
        if p.get('desde'):
            qs = qs.filter(fecha__gte=self._dia(p['desde']))
        if p.get('hasta'):
            qs = qs.filter(fecha__lt=self._dia(p['hasta']) + timedelta(days=1))
        if p.get('q'):
            texto = p['q'].strip()
            qs = qs.filter(Q(descripcion__icontains=texto) | Q(actor__icontains=texto) | Q(lote_codigo__icontains=texto) | Q(motivo__icontains=texto))
        return qs

    @staticmethod
    def _dia(texto):
        try:
            return timezone.make_aware(datetime.combine(datetime.strptime(texto, '%Y-%m-%d').date(), time.min))
        except ValueError:
            return timezone.now()

    def list(self, request, *args, **kwargs):
        try:
            limite = min(int(request.query_params.get('limite', LIMITE_POR_DEFECTO)), LIMITE_MAXIMO)
        except ValueError:
            limite = LIMITE_POR_DEFECTO
        qs = self.filter_queryset(self.get_queryset())
        total = qs.count()
        return Response({'total': total, 'limite': limite, 'resultados': self.get_serializer(qs[:limite], many=True).data})

    @action(detail=False, methods=['get'])
    def opciones(self, request):
        return Response({'categorias': [{'valor': v, 'texto': t} for v, t in RegistroAuditoria.CATEGORIA_CHOICES]})
