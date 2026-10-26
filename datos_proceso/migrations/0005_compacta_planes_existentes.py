# Compacta los planes de captura ya guardados en fases y tomas (ver datos_proceso/planes.py).
# Solo cambia cómo se guardan: cada plan compactado se expande idéntico al original (se verifica uno por uno).

from django.db import migrations

LOTE = 500


def _recorrer(modelo, campo):
    ids = list(modelo.objects.exclude(**{campo: {}}).values_list('id', flat=True).order_by('id'))
    for i in range(0, len(ids), LOTE):
        yield list(modelo.objects.filter(id__in=ids[i:i + LOTE]).only('id', campo))


def _tiene_en_linea(plan):
    return any('parametros' in s for s in (plan or {}).get('secciones', []))


def compactar(apps, schema_editor):
    from datos_proceso.planes import compactar_planes, expandir_planes
    PlanParametros = apps.get_model('datos_proceso', 'PlanParametros')
    for modelo, campo in ((apps.get_model('procesos', 'FaseLote'), 'plan_captura'),
                          (apps.get_model('datos_proceso', 'TomaDatos'), 'plan')):
        for grupo in _recorrer(modelo, campo):
            grupo = [o for o in grupo if _tiene_en_linea(getattr(o, campo))]
            if not grupo:
                continue
            originales = [getattr(o, campo) for o in grupo]
            compactos = compactar_planes(originales, PlanParametros)
            if expandir_planes(compactos, PlanParametros) != originales:
                raise RuntimeError(f"Un plan de {modelo.__name__} no se reconstruye igual; no se compacta nada.")
            for o, c in zip(grupo, compactos):
                setattr(o, campo, c)
            modelo.objects.bulk_update(grupo, [campo])


def expandir(apps, schema_editor):
    from datos_proceso.planes import expandir_planes
    PlanParametros = apps.get_model('datos_proceso', 'PlanParametros')
    for modelo, campo in ((apps.get_model('procesos', 'FaseLote'), 'plan_captura'),
                          (apps.get_model('datos_proceso', 'TomaDatos'), 'plan')):
        for grupo in _recorrer(modelo, campo):
            for o, e in zip(grupo, expandir_planes([getattr(o, campo) for o in grupo], PlanParametros)):
                setattr(o, campo, e)
            modelo.objects.bulk_update(grupo, [campo])


class Migration(migrations.Migration):

    dependencies = [
        ('datos_proceso', '0004_planes_compactos'),
        ('procesos', '0022_indices_fases'),
    ]

    operations = [migrations.RunPython(compactar, expandir)]
