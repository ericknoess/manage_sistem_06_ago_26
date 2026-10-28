# Permiso para evaluar eventos GMP y rol Calidad.
# Se agrega a Administrador, Jefatura, Supervisor de turno y Calidad; después se ajusta desde el admin.

from django.db import migrations

CON_PERMISO = ['Administrador', 'Jefatura', 'Supervisor de turno', 'Calidad']


def dar_permiso(apps, schema_editor):
    from django.contrib.auth.management import create_permissions
    config = apps.get_app_config('usuarios')
    config.models_module = True
    create_permissions(config, verbosity=0, apps=apps)

    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    permiso = Permission.objects.get(content_type__app_label='usuarios', codename='evaluar_evento')
    for nombre in CON_PERMISO:
        grupo, _ = Group.objects.get_or_create(name=nombre)
        grupo.permissions.add(permiso)


def quitar_permiso(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name='Calidad').delete()
    Permission = apps.get_model('auth', 'Permission')
    Permission.objects.filter(content_type__app_label='usuarios', codename='evaluar_evento').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0004_surtido_material'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='perfil',
            options={'default_permissions': (), 'permissions': [('instanciar_lote', 'Crear e iniciar lotes'), ('abortar_lote', 'Abortar, eliminar y archivar lotes'), ('reprogramar_fase', 'Reprogramar fases de lote'), ('asignar_personal', 'Asignar operadores y equipos a fases'), ('ejecutar_fase', 'Iniciar y completar fases'), ('ajustar_material_lote', 'Agregar, ajustar y retirar materiales de un lote'), ('surtir_material', 'Entregar materiales a las fases y recibir devoluciones'), ('editar_receta', 'Crear y editar recetas maestras'), ('archivar_receta', 'Archivar y restaurar recetas maestras'), ('gestionar_catalogos', 'Gestionar catálogos de materiales y equipos'), ('gestionar_roster', 'Gestionar turnos, cuadrillas, operadores e incidencias'), ('gestionar_usuarios', 'Gestionar usuarios y roles'), ('evaluar_evento', 'Evaluar, cerrar y anular eventos GMP')], 'verbose_name': 'Perfil de usuario', 'verbose_name_plural': 'Perfiles de usuario'},
        ),
        migrations.RunPython(dar_permiso, quitar_permiso),
    ]
