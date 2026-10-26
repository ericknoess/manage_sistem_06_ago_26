"""
Importa el histórico de lotes de EPO de la app Cultivo (ver datos_proceso/importacion_cultivo.py).

    python manage.py importar_cultivo --bd "host=localhost port=5433 user=postgres dbname=base_proceso" \
        --curva ../cultivo_local/app/datos_modelo.csv [--lote EMAS26009 ...] [--simular] [--detalle]

La base de Cultivo solo se lee. La contraseña, si hace falta, va en la variable PGPASSWORD (nunca en la línea de comandos).
Se puede repetir: solo agrega los muestreos nuevos de cada lote.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from datos_proceso import importacion_cultivo as imp


class _Simulacion(Exception):
    pass


class Command(BaseCommand):
    help = "Importa los lotes de EPO de Cultivo (receta «EPO – Cultivo (histórico)»)."

    def add_arguments(self, parser):
        parser.add_argument('--bd', required=True, help="Conexión a la base de Cultivo (formato libpq)")
        parser.add_argument('--curva', help="datos_modelo.csv de Cultivo, para la curva Modelo_2024 de células")
        parser.add_argument('--lote', action='append', dest='lotes', help="Solo este lote (se puede repetir)")
        parser.add_argument('--simular', action='store_true', help="Hace todo y al final lo deshace")
        parser.add_argument('--detalle', action='store_true', help="Muestra los registros duplicados descartados")

    def handle(self, *args, **opciones):
        curva = imp.leer_curva_modelo(opciones['curva']) if opciones.get('curva') else []
        try:
            datos = imp.leer_cultivo(opciones['bd'], opciones.get('lotes'))
        except Exception as e:  # noqa: BLE001 — error de conexión o de consulta de psycopg2
            raise CommandError(f"No se pudo leer Cultivo: {e}")
        if not datos['lotes']:
            raise CommandError("No hay lotes que importar.")
        self.stdout.write(f"Cultivo: {len(datos['lotes'])} lotes, "
                          f"{sum(len(v) for v in datos['registros'].values())} registros.")
        try:
            with transaction.atomic():
                resumen = imp.importar(datos, curva)
                self._informar(resumen, opciones['detalle'])
                if opciones['simular']:
                    raise _Simulacion()
        except _Simulacion:
            self.stdout.write(self.style.WARNING("Simulación: no se guardó nada."))
        except imp.ErrorImportacion as e:
            raise CommandError(str(e))

    def _informar(self, resumen, detalle):
        receta = resumen['receta']
        self.stdout.write(f"Receta: {receta.nombre} (id {receta.id}){' — creada' if resumen['receta_creada'] else ''}")
        if resumen['corte']:
            self.stdout.write(f"Último dato en Cultivo: {timezone.localtime(resumen['corte']):%Y-%m-%d %H:%M}")
        tomas = valores = nuevos = 0
        for r in resumen['lotes']:
            if r['aviso']:
                self.stdout.write(self.style.WARNING(f"  {r['lote']}: {r['aviso']}"))
                continue
            tomas, valores, nuevos = tomas + r['tomas'], valores + r['valores'], nuevos + r['nuevo']
            extra = f", {len(r['diferencias'])} duplicados con valores distintos" if r['diferencias'] else ''
            self.stdout.write(f"  {r['lote']}: {r['estado']}{' (nuevo)' if r['nuevo'] else ''}, "
                              f"{r['tomas']} tomas, {r['valores']} valores{extra}")
            if detalle:
                for d in r['diferencias']:
                    cambios = '; '.join(f"{c}: {v[0]} → se conserva {v[1]}" for c, v in d['valores'].items())
                    self.stdout.write(f"      {d['etapa']} {d['edad']} h (registro {d['descartado']} descartado, "
                                      f"{d['conservado']} conservado): {cambios}")
        self.stdout.write(self.style.SUCCESS(f"Listo: {nuevos} lotes nuevos, {tomas} tomas, {valores} valores."))
