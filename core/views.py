# core/views.py

from django.urls import reverse
from django.views.generic import TemplateView

from eventos.models import EventoGMP
from gestion.models import Tarea
from procesos.models import LoteProduccion, ProcesoMaestro
from procesos.services import personal_en_turno
from roster.models import Operador


class InicioView(TemplateView):
    """
    Página central del sistema (Centro de Control de Operaciones): acceso a todas las aplicaciones y un
    resumen en vivo de la planta. Cada indicador lleva su ícono, color y la pantalla a la que lleva.
    """
    template_name = 'inicio.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lotes_activos = LoteProduccion.objects.filter(archivado=False)
        usuario = self.request.user
        mis_tareas = (Tarea.objects.filter(responsable=usuario, completada_en__isnull=True, subtareas__isnull=True,
                                           proyecto__estado__in=['ACTIVO', 'PAUSADO'], proyecto__en_papelera_desde__isnull=True)
                      .count() if usuario.is_authenticated else 0)
        context['indicadores'] = [
            {'valor': lotes_activos.filter(estado='EN_PROGRESO').count(), 'etiqueta': 'Lotes en progreso', 'icono': '🧪',
             'color': 'verde', 'url': reverse('ejecucion-lotes')},
            {'valor': lotes_activos.filter(estado='PLANEADO').count(), 'etiqueta': 'Lotes planeados', 'icono': '🗓️',
             'color': 'azul', 'url': reverse('planificacion-semanal')},
            {'valor': personal_en_turno(), 'etiqueta': 'Personal en turno ahora', 'icono': '👷',
             'color': 'naranja', 'url': reverse('roster_dashboard')},
            {'valor': EventoGMP.objects.filter(estado='ABIERTO').count(), 'etiqueta': 'Eventos GMP abiertos', 'icono': '⚠️',
             'color': 'rojo', 'url': reverse('eventos-gmp')},
            {'valor': ProcesoMaestro.objects.filter(activo=True).count(), 'etiqueta': 'Recetas maestras activas', 'icono': '🧬',
             'color': 'morado', 'url': reverse('procesos-index')},
            {'valor': mis_tareas, 'etiqueta': 'Mis tareas de oficina', 'icono': '✅',
             'color': 'rosa', 'url': reverse('gestion-proyectos')},
        ]
        return context
