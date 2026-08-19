# actividades/management/commands/poblar_actividades.py

from django.core.management.base import BaseCommand
from actividades.models import Equipo, MaterialInsumo, ActividadSemanal
from roster.models import Operador
from datetime import date

class Command(BaseCommand):
    help = 'Pobla los catálogos de equipos, materiales y crea actividades semanales de prueba.'

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
            obj, _ = Equipo.objects.update_or_create(
                id=eq["id"],
                defaults={"nombre": eq["nombre"], "tipo": eq["tipo"], "activo": True}
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

        # 3. Obtener un operador de prueba del Roster (si existe)
        operador_ejemplo = Operador.objects.first()

        # 4. Creación de Actividades Semanales de Prueba
        actividades_data = [
            {
                "lote_codigo": "LOTE-CHO-2026-01",
                "titulo": "Preparación de Medio 500L",
                "fecha": date(2026, 7, 1),
                "hora_inicio": "08:00:00",
                "hora_fin": "10:30:00",
                "turno_req": "M",
                "equipos": ["EQ-03"],
                "materiales": ["MAT-01", "MAT-05"]
            },
            {
                "lote_codigo": "LOTE-CHO-2026-01",
                "titulo": "Inoculación Biorreactor BR-01",
                "fecha": date(2026, 7, 1),
                "hora_inicio": "11:00:00",
                "hora_fin": "13:00:00",
                "turno_req": "M",
                "equipos": ["EQ-01"],
                "materiales": ["MAT-03"]
            },
            {
                "lote_codigo": "LOTE-ECOUT-2026-04",
                "titulo": "Muestreo Metabolitos Fermentación",
                "fecha": date(2026, 7, 2),
                "hora_inicio": "15:30:00",
                "hora_fin": "18:00:00",
                "turno_req": "T",
                "equipos": ["EQ-06"],
                "materiales": ["MAT-04"]
            }
        ]

        for act in actividades_data:
            actividad_obj, created = ActividadSemanal.objects.update_or_create(
                lote_codigo=act["lote_codigo"],
                titulo=act["titulo"],
                fecha=act["fecha"],
                defaults={
                    "hora_inicio": act["hora_inicio"],
                    "hora_fin": act["hora_fin"],
                    "turno_req": act["turno_req"],
                    "operador_asignado": operador_ejemplo
                }
            )
            # Asignar relaciones ManyToMany
            actividad_obj.equipos.set([equipos_objs[eq_id] for eq_id in act["equipos"]])
            actividad_obj.materiales.set([materiales_objs[mat_id] for mat_id in act["materiales"]])
            
            status = "Creada" if created else "Actualizada"
            self.stdout.write(f"Actividad {status}: {actividad_obj}")

        self.stdout.write(self.style.SUCCESS("¡Datos semilla y actividades de prueba cargados con éxito!"))