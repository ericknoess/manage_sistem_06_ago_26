# Reemplaza fecha + hora_inicio + hora_fin (que no soportaban fases de más de 24 h)
# por fecha-hora completas de inicio y fin, tanto para la línea base CPM como para el forecast.

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import migrations, models


def _duracion(fase):
    op = fase.operacion_maestra
    horas = op.duracion_muestreo_horas if fase.es_subtarea_muestreo else op.duracion_horas
    return timedelta(hours=horas or 0)


def a_fechas_completas(apps, schema_editor):
    """Los valores antiguos se guardaban en hora local; el fin se recalcula con la duración
    porque la hora de fin sola perdía los días de las fases largas."""
    FaseLote = apps.get_model('procesos', 'FaseLote')
    tz = ZoneInfo(settings.TIME_ZONE)
    for fase in FaseLote.objects.select_related('operacion_maestra'):
        duracion = _duracion(fase)
        if fase.fecha_programada and fase.hora_inicio_programada:
            fase.inicio_programado = datetime.combine(fase.fecha_programada, fase.hora_inicio_programada, tzinfo=tz)
            fase.fin_programado = fase.inicio_programado + duracion
        if fase.fecha_base_cpm and fase.hora_inicio_base_cpm:
            fase.inicio_base_cpm = datetime.combine(fase.fecha_base_cpm, fase.hora_inicio_base_cpm, tzinfo=tz)
            fase.fin_base_cpm = fase.inicio_base_cpm + duracion
        fase.save(update_fields=['inicio_programado', 'fin_programado', 'inicio_base_cpm', 'fin_base_cpm'])


def a_fecha_y_horas(apps, schema_editor):
    FaseLote = apps.get_model('procesos', 'FaseLote')
    tz = ZoneInfo(settings.TIME_ZONE)
    for fase in FaseLote.objects.all():
        if fase.inicio_programado and fase.fin_programado:
            inicio, fin = fase.inicio_programado.astimezone(tz), fase.fin_programado.astimezone(tz)
            fase.fecha_programada, fase.hora_inicio_programada, fase.hora_fin_programada = inicio.date(), inicio.time(), fin.time()
        if fase.inicio_base_cpm and fase.fin_base_cpm:
            inicio, fin = fase.inicio_base_cpm.astimezone(tz), fase.fin_base_cpm.astimezone(tz)
            fase.fecha_base_cpm, fase.hora_inicio_base_cpm, fase.hora_fin_base_cpm = inicio.date(), inicio.time(), fin.time()
        fase.save(update_fields=[
            'fecha_programada', 'hora_inicio_programada', 'hora_fin_programada',
            'fecha_base_cpm', 'hora_inicio_base_cpm', 'hora_fin_base_cpm',
        ])


class Migration(migrations.Migration):

    dependencies = [
        ('procesos', '0013_operacionproceso_unique_paso_per_proceso'),
    ]

    operations = [
        migrations.AddField(
            model_name='faselote',
            name='inicio_base_cpm',
            field=models.DateTimeField(blank=True, null=True, help_text='Inicio según la línea base CPM al instanciar el lote'),
        ),
        migrations.AddField(
            model_name='faselote',
            name='fin_base_cpm',
            field=models.DateTimeField(blank=True, null=True, help_text='Fin según la línea base CPM al instanciar el lote'),
        ),
        migrations.AddField(
            model_name='faselote',
            name='inicio_programado',
            field=models.DateTimeField(blank=True, null=True, help_text='Inicio vigente (forecast) tras reprogramaciones'),
        ),
        migrations.AddField(
            model_name='faselote',
            name='fin_programado',
            field=models.DateTimeField(blank=True, null=True, help_text='Fin vigente (forecast) tras reprogramaciones'),
        ),
        migrations.RunPython(a_fechas_completas, a_fecha_y_horas),
        migrations.RemoveField(model_name='faselote', name='fecha_base_cpm'),
        migrations.RemoveField(model_name='faselote', name='hora_inicio_base_cpm'),
        migrations.RemoveField(model_name='faselote', name='hora_fin_base_cpm'),
        migrations.RemoveField(model_name='faselote', name='fecha_programada'),
        migrations.RemoveField(model_name='faselote', name='hora_inicio_programada'),
        migrations.RemoveField(model_name='faselote', name='hora_fin_programada'),
    ]
