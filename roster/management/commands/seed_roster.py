# roster/management/commands/seed_roster.py
from django.core.management.base import BaseCommand
from roster.models import Cuadrilla, Operador, TurnoDia
from datetime import date, timedelta

class Command(BaseCommand):
    """
    Comando personalizado para poblar la base de datos relacional con el Roster inicial de la maqueta (Julio 2026).
    """
    help = 'Puebla la base de datos relacional con el Roster inicial de la maqueta (Julio 2026)'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.WARNING("Limpiando datos previos del Roster..."))
        TurnoDia.objects.all().delete()
        Operador.objects.all().delete()
        Cuadrilla.objects.all().delete()

        # 1. DEFINICIÓN Y CREACIÓN DE CUADRILLAS
        datos_cuadrillas = [
            {'id': 'A', 'nombre': 'Cuadrilla A - Inóculos', 'activa': True, 'offset': 0, 'num_ops': 10},
            {'id': 'B', 'nombre': 'Cuadrilla B - Biorreactores', 'activa': True, 'offset': 7, 'num_ops': 10},
            {'id': 'C', 'nombre': 'Cuadrilla C - Downstream / Cosecha', 'activa': True, 'offset': 14, 'num_ops': 10},
            {'id': 'D', 'nombre': 'Cuadrilla D - Purificación / Lavado', 'activa': False, 'offset': 0, 'num_ops': 8}
        ]

        cuadrillas_db = {}
        for c_data in datos_cuadrillas:
            c = Cuadrilla.objects.create(
                identificador=c_data['id'],
                nombre=c_data['nombre'],
                activa=c_data['activa']
            )
            cuadrillas_db[c_data['id']] = {'obj': c, 'offset': c_data['offset'], 'num_ops': c_data['num_ops']}
            self.stdout.write(self.style.SUCCESS(f"✔ Cuadrilla creada: {c.nombre}"))

        # 2. CREACIÓN DE OPERADORES
        id_counter = 1
        operadores_db = []
        for c_id, data in cuadrillas_db.items():
            for _ in range(data['num_ops']):
                op_nombre = f"Operador {id_counter:02d}"
                op = Operador.objects.create(
                    nombre=op_nombre,
                    cuadrilla=data['obj']
                )
                operadores_db.append({'obj': op, 'cuadrilla_id': c_id, 'op_id': id_counter})
                id_counter += 1
        self.stdout.write(self.style.SUCCESS(f"✔ Se registraron {len(operadores_db)} operadores en total."))

        # 3. GENERACIÓN MATEMÁTICA DE TURNOS (Julio 2026)
        turnos_secuencia = ['M','M','M','M','M','OFF','OFF','T','T','T','T','T','OFF','OFF','N','N','N','N','N','OFF','OFF','TR','TR','TR','TR','TR','OFF','OFF','M','M','M']
        fecha_inicio = date(2026, 7, 1)
        turnos_a_crear = []

        for op_data in operadores_db:
            op = op_data['obj']
            c_info = cuadrillas_db[op_data['cuadrilla_id']]
            offset = c_info['offset']
            activa = c_info['obj'].activa

            for dia in range(31):
                fecha_actual = fecha_inicio + timedelta(days=dia)
                
                # Si la cuadrilla está inactiva (Pendiente), el turno es '--'
                if not activa:
                    turno_codigo = '--'
                else:
                    idx_turno = (dia + offset) % len(turnos_secuencia)
                    turno_codigo = turnos_secuencia[idx_turno]

                # Reproducir excepciones exactas de la maqueta
                if op_data['op_id'] == 2 and dia in [7, 8]:  # Días 8 y 9 del mes (índices 7 y 8)
                    turno_codigo = 'F'
                if op_data['op_id'] == 5 and 14 <= dia <= 18: # Del día 15 al 19 del mes
                    turno_codigo = 'INC'

                # Usamos objetos instanciados para prepararlos en memoria RAM
                turnos_a_crear.append(TurnoDia(
                    operador=op,
                    fecha=fecha_actual,
                    codigo_turno=turno_codigo
                ))

        # 4. INSERCIÓN MASIVA (Performance Optimization)
        # bulk_create ejecuta un solo query SQL para insertar miles de registros, vital para escalabilidad.
        TurnoDia.objects.bulk_create(turnos_a_crear)
        
        self.stdout.write(self.style.SUCCESS(f"✔ Se insertaron {len(turnos_a_crear)} turnos correspondientes al mes de Julio 2026."))
        self.stdout.write(self.style.SUCCESS("🚀 ¡Base de datos sembrada con éxito! Lista para operar."))