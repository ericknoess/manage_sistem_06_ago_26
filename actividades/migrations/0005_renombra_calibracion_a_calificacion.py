from django.db import migrations, models


class Migration(migrations.Migration):
    """Renombra el vencimiento de calibración a calificación (conserva las fechas ya capturadas)."""

    dependencies = [
        ('actividades', '0004_tipos_y_estado_de_equipo'),
    ]

    operations = [
        migrations.RenameField(
            model_name='equipo',
            old_name='calibracion_vence',
            new_name='calificacion_vence',
        ),
        migrations.AlterField(
            model_name='equipo',
            name='calificacion_vence',
            field=models.DateField(blank=True, null=True,
                                   help_text='Vencimiento de la calificación; después de esa fecha no se reserva'),
        ),
    ]
