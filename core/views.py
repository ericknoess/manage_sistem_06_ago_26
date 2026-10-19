# core/views.py

from django.views.generic import TemplateView

from procesos.models import LoteProduccion, ProcesoMaestro
from roster.models import Cuadrilla, Operador


class InicioView(TemplateView):
    """
    Página central del sistema: acceso a todas las aplicaciones y un resumen
    rápido del estado de la planta.
    """
    template_name = 'inicio.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lotes_activos = LoteProduccion.objects.filter(archivado=False)
        context['indicadores'] = [
            {'valor': lotes_activos.filter(estado='EN_PROGRESO').count(), 'etiqueta': 'Lotes en progreso'},
            {'valor': lotes_activos.filter(estado='PLANEADO').count(), 'etiqueta': 'Lotes planeados'},
            {'valor': ProcesoMaestro.objects.filter(activo=True).count(), 'etiqueta': 'Recetas maestras activas'},
            {'valor': Operador.objects.filter(activo=True).count(), 'etiqueta': 'Operadores activos'},
            {'valor': Cuadrilla.objects.filter(activa=True).count(), 'etiqueta': 'Cuadrillas'},
        ]
        return context
