# Crea los roles del sistema (grupos de Django) con su matriz de permisos inicial.
# Después se ajustan desde el admin; esta migración no los vuelve a tocar.

from django.db import migrations

ROLES = {
    'Administrador': [
        'instanciar_lote', 'abortar_lote', 'reprogramar_fase', 'asignar_personal', 'ejecutar_fase',
        'ajustar_material_lote', 'editar_receta', 'archivar_receta', 'gestionar_catalogos',
        'gestionar_roster', 'gestionar_usuarios',
    ],
    'Jefatura': [
        'instanciar_lote', 'abortar_lote', 'reprogramar_fase', 'asignar_personal', 'ejecutar_fase',
        'ajustar_material_lote', 'archivar_receta', 'gestionar_roster',
    ],
    'Planeador': ['instanciar_lote', 'reprogramar_fase', 'asignar_personal', 'ajustar_material_lote'],
    'Supervisor de turno': ['asignar_personal', 'ejecutar_fase', 'gestionar_roster'],
    'Ingeniería de procesos': ['editar_receta', 'archivar_receta', 'gestionar_catalogos'],
    'Operador': [],
    'Consulta': [],
}


def crear_roles(apps, schema_editor):
    from django.contrib.auth.management import create_permissions
    # Los permisos de Perfil se crean normalmente después de migrar; aquí se necesitan ya.
    config = apps.get_app_config('usuarios')
    config.models_module = True  # el stub histórico no lo trae y create_permissions lo exige
    create_permissions(config, verbosity=0, apps=apps)

    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    for nombre, codigos in ROLES.items():
        grupo, _ = Group.objects.get_or_create(name=nombre)
        grupo.permissions.set(Permission.objects.filter(content_type__app_label='usuarios', codename__in=codigos))


def quitar_roles(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.filter(name__in=ROLES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(crear_roles, quitar_roles),
    ]
