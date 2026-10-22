# actividades/management/commands/poblar_actividades.py

from django.core.management.base import BaseCommand
from actividades.models import Equipo, MaterialInsumo, TipoEquipo

class Command(BaseCommand):
    help = 'Pobla los catálogos de equipos y materiales.'

    def handle(self, *args, **options):
        self.stdout.write("Iniciando carga completa de datos semilla...")

        # 1. Creación de Equipos Críticos
        equipos_data = [
            {"id": "EQ-01", "nombre": "Biorreactor BR-01 (500L)", "tipo": "BIORREACTOR"},
            {"id": "EQ-02", "nombre": "Biorreactor BR-02 (200L)", "tipo": "BIORREACTOR"},
            {"id": "EQ-03", "nombre": "Tanque Preparador T-02", "tipo": "TANQUE"},
            {"id": "EQ-04", "nombre": "Centrífuga Industrial C-01", "tipo": "CENTRIFUGA"},
            {"id": "EQ-05", "nombre": "Incubadora Agitadora Inc-03", "tipo": "INCUBADORA"},
            {"id": "EQ-06", "nombre": "Analizador de Metabolitos BioProfile", "tipo": "ANALIZADOR"},
        ]

        equipos_objs = {}
        for eq in equipos_data:
            TipoEquipo.objects.get_or_create(codigo=eq["tipo"], defaults={"nombre": eq["tipo"].capitalize()})
            obj, _ = Equipo.objects.update_or_create(
                id=eq["id"],
                defaults={"nombre": eq["nombre"], "tipo_id": eq["tipo"], "activo": True}
            )
            equipos_objs[eq["id"]] = obj

        # 2. Creación de Materiales e Insumos
        materiales_data = [
            {"id": "MAT-01", "nombre": "Medio de Cultivo CHO-K1 (200L)", "stock_controlado": True},
            {"id": "MAT-02", "nombre": "Solución de Glucosa 45%", "stock_controlado": True},
            {"id": "MAT-03", "nombre": "Bolsa de Transferencia Estéril 20L", "stock_controlado": False},
            {"id": "MAT-04", "nombre": "Kit Muestreo Ciego Estéril x10", "stock_controlado": False},
            {"id": "MAT-05", "nombre": "Agua Inyectable WFI 100L", "stock_controlado": True},
            {"id": "MAT-06", "nombre": "Detergente Alcalino CIP-100", "stock_controlado": True},
        ]

        materiales_objs = {}
        for mat in materiales_data:
            obj, _ = MaterialInsumo.objects.update_or_create(
                id=mat["id"],
                defaults={"nombre": mat["nombre"], "stock_controlado": mat["stock_controlado"], "activo": True}
            )
            materiales_objs[mat["id"]] = obj
