"""
Deja preparadas las gráficas (series reducidas e indicadores) de los lotes terminados, para que la primera vez que se
grafiquen muchos lotes no haya que esperar. Es opcional: si falta alguna, se prepara sola al graficar.

    python manage.py preparar_series [--receta <id>]
"""
from django.core.management.base import BaseCommand

from datos_proceso.models import IndicadorProceso
from datos_proceso.services import series_preparadas
from procesos.models import LoteProduccion, ProcesoMaestro

TANDA = 25


class Command(BaseCommand):
    help = "Prepara las series de los lotes terminados (las de Gráficas con muchos lotes)."

    def add_arguments(self, parser):
        parser.add_argument('--receta', type=int, help="Solo los lotes de esta receta")

    def handle(self, *args, **opciones):
        recetas = ProcesoMaestro.objects.all()
        if opciones.get('receta'):
            recetas = recetas.filter(pk=opciones['receta'])
        for receta in recetas:
            lotes = list(LoteProduccion.objects.filter(proceso_maestro=receta, estado='COMPLETADO'))
            if not lotes:
                continue
            indicadores = list(IndicadorProceso.objects.filter(proceso=receta, activo=True).select_related('parametro', 'etapa'))
            for i in range(0, len(lotes), TANDA):
                series_preparadas(lotes[i:i + TANDA], indicadores)
            self.stdout.write(f"{receta.nombre}: {len(lotes)} lotes terminados listos.")
