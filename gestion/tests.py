# gestion/tests.py — Proyectos y tareas de oficina: calendario hábil, dependencias, resúmenes, ruta crítica, tablero y acceso.

from datetime import date

from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from . import services
from .models import Columna, Historial, Proyecto, Tarea

LUNES = date(2026, 11, 2)


def usuario(nombre, rol=None):
    u = User.objects.create_user(nombre, password='clave', first_name=nombre.capitalize())
    if rol:
        u.groups.add(Group.objects.get(name=rol))
    return u


class CalendarioTests(TestCase):

    def test_dias_habiles(self):
        viernes, sabado = date(2026, 11, 6), date(2026, 11, 7)
        self.assertEqual(services.dias_habiles(LUNES, viernes), 5)
        self.assertEqual(services.dias_habiles(LUNES, date(2026, 11, 9)), 6)          # el fin de semana no cuenta
        self.assertEqual(services.habil_desde(sabado), date(2026, 11, 9))
        self.assertEqual(services.sumar_habiles(viernes, 1), date(2026, 11, 9))
        self.assertEqual(services.sumar_habiles(date(2026, 11, 9), -1), viernes)
        self.assertEqual(services.fin_por_duracion(date(2026, 11, 5), 3), date(2026, 11, 9))


class ProyectoBase(TestCase):

    def setUp(self):
        self.ana, self.beto, self.ajeno = usuario('ana'), usuario('beto'), usuario('ajeno')
        self.api = APIClient()
        self.api.force_authenticate(self.ana)
        r = self.api.post('/api/gestion/proyectos/', {'nombre': 'Validación de limpieza', 'miembros': [self.beto.pk]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.proyecto = Proyecto.objects.get(pk=r.data['id'])
        self.col = {c.nombre: c for c in self.proyecto.columnas.all()}

    def tarea(self, nombre, inicio=None, fin=None, **extra):
        datos = {'proyecto': self.proyecto.pk, 'nombre': nombre, 'inicio': inicio and inicio.isoformat(),
                 'fin': fin and fin.isoformat(), **extra}
        r = self.api.post('/api/gestion/tareas/', datos, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return Tarea.objects.get(pk=r.data['id'])

    def detalle(self):
        r = self.api.get(f'/api/gestion/proyectos/{self.proyecto.pk}/')
        self.assertEqual(r.status_code, 200, r.data)
        return r.data, {t['nombre']: t for t in r.data['tareas']}


class ProyectoTests(ProyectoBase):

    def test_crea_columnas_y_solo_lo_ven_sus_miembros(self):
        self.assertEqual(list(self.col), ['Por hacer', 'En curso', 'En revisión', 'Hecho'])
        self.assertTrue(self.col['Hecho'].es_final)
        self.assertEqual(set(self.proyecto.miembros.all()), {self.ana, self.beto})

        ajeno = APIClient()
        ajeno.force_authenticate(self.ajeno)
        self.assertEqual(ajeno.get('/api/gestion/proyectos/').data, [])
        self.assertEqual(ajeno.get(f'/api/gestion/proyectos/{self.proyecto.pk}/').status_code, 403)
        r = ajeno.post('/api/gestion/tareas/', {'proyecto': self.proyecto.pk, 'nombre': 'Intrusa'}, format='json')
        self.assertIn('miembro', r.data['error'])

        # Un miembro edita tareas pero no configura el proyecto
        beto = APIClient()
        beto.force_authenticate(self.beto)
        self.assertEqual(beto.post('/api/gestion/tareas/', {'proyecto': self.proyecto.pk, 'nombre': 'Protocolo'}, format='json').status_code, 201)
        self.assertIn('responsable', beto.patch(f'/api/gestion/proyectos/{self.proyecto.pk}/', {'nombre': 'Otro'}, format='json').data['error'])

        admin = APIClient()
        admin.force_authenticate(usuario('jefa', 'Administrador'))
        self.assertEqual(len(admin.get('/api/gestion/proyectos/').data), 1)

    def test_la_terminal_con_pin_no_entra(self):
        self.assertIn(APIClient().get('/api/gestion/proyectos/').status_code, (401, 403))

    def test_dependencias_empujan_sucesoras_y_validan(self):
        a = self.tarea('Redactar protocolo', LUNES, date(2026, 11, 4))                 # lun–mié
        b = self.tarea('Revisión de Calidad', date(2026, 11, 3), date(2026, 11, 4))   # 2 días
        r = self.api.post(f'/api/gestion/tareas/{b.pk}/dependencias/', {'predecesora': a.pk}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        b.refresh_from_db()
        self.assertEqual((b.inicio, b.fin), (date(2026, 11, 5), date(2026, 11, 6)))  # jueves y viernes

        # Alargar la predecesora recorre a la sucesora sobre el fin de semana, conservando su duración
        r = self.api.patch(f'/api/gestion/tareas/{a.pk}/', {'fin': '2026-11-05'}, format='json')
        self.assertEqual(r.data['movidas'], ['Revisión de Calidad'])
        b.refresh_from_db()
        self.assertEqual((b.inicio, b.fin), (date(2026, 11, 6), date(2026, 11, 9)))

        # No se puede adelantar la sucesora antes de lo que permite su predecesora, ni formar ciclos
        self.assertIn('no puede empezar antes', self.api.patch(f'/api/gestion/tareas/{b.pk}/', {'inicio': '2026-11-02'}, format='json').data['error'])
        self.assertIn('ciclo', self.api.post(f'/api/gestion/tareas/{a.pk}/dependencias/', {'predecesora': b.pk}, format='json').data['error'])

    def test_resumen_ruta_critica_y_linea_base(self):
        fase = self.tarea('Fase 1')
        a = self.tarea('A', LUNES, date(2026, 11, 4), padre=fase.pk)          # 3 días
        b = self.tarea('B', LUNES, LUNES, padre=fase.pk)                      # 1 día, con holgura
        c = self.tarea('C', date(2026, 11, 5), date(2026, 11, 6))             # después de A
        self.api.post(f'/api/gestion/tareas/{c.pk}/dependencias/', {'predecesora': a.pk}, format='json')
        self.api.patch(f'/api/gestion/tareas/{a.pk}/', {'avance': 50}, format='json')
        self.api.post(f'/api/gestion/proyectos/{self.proyecto.pk}/linea-base/')

        datos, t = self.detalle()
        self.assertEqual([x['wbs'] for x in datos['tareas']], ['1', '1.1', '1.2', '2'])
        self.assertTrue(t['Fase 1']['resumen'])
        self.assertEqual((t['Fase 1']['inicio'], t['Fase 1']['fin']), (LUNES, date(2026, 11, 4)))
        self.assertEqual(t['Fase 1']['avance'], 38)                       # (3·50 + 1·0) / 4
        self.assertTrue(t['A']['critica'] and t['C']['critica'])
        self.assertEqual(t['B']['holgura'], 4)
        self.assertFalse(t['B']['critica'])
        self.assertIsNone(Tarea.objects.get(pk=fase.pk).columna)        # una tarea resumen no va en el tablero
        self.assertIn('subtareas', self.api.patch(f'/api/gestion/tareas/{fase.pk}/', {'avance': 10}, format='json').data['error'])

        # Retrasar A después de guardar la línea base: C se recorre y el proyecto marca 2 días de atraso
        self.api.patch(f'/api/gestion/tareas/{a.pk}/', {'fin': '2026-11-06'}, format='json')
        datos, t = self.detalle()
        self.assertEqual(t['C']['atraso'], 2)
        self.assertEqual(datos['resumen']['atraso'], 2)

    def test_tablero_mueve_y_marca_terminada(self):
        a = self.tarea('Cotizar equipo')
        b = self.tarea('Orden de compra')
        self.assertEqual(a.columna, self.col['Por hacer'])
        r = self.api.post(f'/api/gestion/tareas/{b.pk}/mover/', {'columna': self.col['Hecho'].pk, 'posicion': 0}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        b.refresh_from_db()
        self.assertEqual((b.avance, b.completada_en is not None), (100, True))
        self.api.post(f'/api/gestion/tareas/{b.pk}/mover/', {'columna': self.col['En curso'].pk}, format='json')
        b.refresh_from_db()
        self.assertEqual((b.avance, b.completada_en), (90, None))

        # Avance al 100 % desde el Gantt la manda a la columna final; límite WIP
        self.api.patch(f'/api/gestion/tareas/{a.pk}/', {'avance': 100}, format='json')
        a.refresh_from_db()
        self.assertEqual(a.columna, self.col['Hecho'])
        Columna.objects.filter(pk=self.col['En revisión'].pk).update(limite=1)
        self.api.post(f'/api/gestion/tareas/{a.pk}/mover/', {'columna': self.col['En revisión'].pk}, format='json')
        r = self.api.post(f'/api/gestion/tareas/{b.pk}/mover/', {'columna': self.col['En revisión'].pk}, format='json')
        self.assertIn('límite', r.data['error'])

        self.assertTrue(Historial.objects.filter(proyecto=self.proyecto, descripcion__contains='Movió').exists())

    def test_mis_tareas_checklist_y_comentarios(self):
        a = self.tarea('Actualizar SOP', LUNES, LUNES, responsable=self.ana.pk)
        self.tarea('De Beto', responsable=self.beto.pk)
        self.assertIn('miembro', self.api.post('/api/gestion/tareas/', {'proyecto': self.proyecto.pk, 'nombre': 'Ajena',
                                                                        'responsable': self.ajeno.pk}, format='json').data['error'])
        self.assertEqual([t['nombre'] for t in self.api.get('/api/gestion/tareas/').data], ['Actualizar SOP'])

        item = self.api.post(f'/api/gestion/tareas/{a.pk}/checklist/', {'texto': 'Enviar a revisión'}, format='json').data['id']
        self.api.patch(f'/api/gestion/checklist/{item}/', {'hecho': True}, format='json')
        self.api.post(f'/api/gestion/tareas/{a.pk}/comentarios/', {'texto': 'Ya lo revisé con Calidad'}, format='json')
        d = self.api.get(f'/api/gestion/tareas/{a.pk}/').data
        self.assertEqual((d['checklist'][0]['hecho'], d['comentarios'][0]['autor']), (True, 'Ana'))
        _, t = self.detalle()
        self.assertEqual((t['Actualizar SOP']['checklist'], t['Actualizar SOP']['comentarios']), ([1, 1], 1))

        # Borrar es libre (no es GMP); el proyecto pasa por la papelera
        self.assertEqual(self.api.delete(f'/api/gestion/tareas/{a.pk}/').status_code, 204)
        self.assertEqual(self.api.delete(f'/api/gestion/proyectos/{self.proyecto.pk}/').status_code, 204)
        self.assertEqual(self.api.get('/api/gestion/proyectos/').data, [])
        self.assertEqual([p['nombre'] for p in self.api.get('/api/gestion/proyectos/?papelera=1').data], ['Validación de limpieza'])
        self.assertIn('papelera', self.api.post('/api/gestion/tareas/', {'proyecto': self.proyecto.pk, 'nombre': 'X'}, format='json').data['error'])
        self.api.post(f'/api/gestion/proyectos/{self.proyecto.pk}/recuperar/')
        self.assertEqual(len(self.api.get('/api/gestion/proyectos/').data), 1)
        self.api.delete(f'/api/gestion/proyectos/{self.proyecto.pk}/')
        self.assertEqual(self.api.post(f'/api/gestion/proyectos/{self.proyecto.pk}/eliminar-definitivo/').status_code, 200)
        self.assertFalse(Proyecto.objects.exists())


class DeshacerYVersionesTests(ProyectoBase):

    def deshacer(self):
        r = self.api.post(f'/api/gestion/proyectos/{self.proyecto.pk}/deshacer/')
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def test_deshacer_paso_a_paso_con_quien_lo_hizo(self):
        a = self.tarea('Redactar protocolo', LUNES, date(2026, 11, 4))
        b = self.tarea('Revisión', date(2026, 11, 5), date(2026, 11, 5))
        self.api.post(f'/api/gestion/tareas/{b.pk}/dependencias/', {'predecesora': a.pk}, format='json')
        self.api.patch(f'/api/gestion/tareas/{a.pk}/', {'fin': '2026-11-06'}, format='json')     # recorre a B
        b.refresh_from_db()
        self.assertEqual(b.inicio, date(2026, 11, 9))

        datos, _ = self.detalle()
        self.assertEqual((datos['ultimo_cambio']['usuario'], datos['ultimo_cambio']['deshacible']), ('Ana', True))
        self.assertIn('Se deshizo', self.deshacer()['mensaje'])      # el cambio de fin, con la sucesora
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual((a.fin, b.inicio), (date(2026, 11, 4), date(2026, 11, 5)))
        self.deshacer()                                              # la dependencia
        self.assertFalse(b.dependencias_predecesoras.exists())

        # Deshacer el borrado recupera la tarea con su checklist y comentarios (mismo id: su historial sigue ligado)
        self.api.post(f'/api/gestion/tareas/{a.pk}/checklist/', {'texto': 'Enviar a revisión'}, format='json')
        self.api.post(f'/api/gestion/tareas/{a.pk}/comentarios/', {'texto': 'Listo para revisión'}, format='json')
        self.api.delete(f'/api/gestion/tareas/{a.pk}/')
        self.assertFalse(Tarea.objects.filter(pk=a.pk).exists())
        self.deshacer()
        a = Tarea.objects.get(pk=a.pk)
        self.assertEqual((a.checklist.count(), a.comentarios.first().texto), (1, 'Listo para revisión'))

        historial = self.api.get(f'/api/gestion/proyectos/{self.proyecto.pk}/historial/').data
        self.assertTrue(all(h['usuario'] == 'Ana' for h in historial))
        self.assertEqual([h['tipo'] for h in historial[:2]], ['DESHACER', 'CAMBIO'])
        self.assertTrue(historial[1]['deshecho'])

    def test_regresar_a_un_punto_y_deshacer_el_regreso(self):
        a = self.tarea('A')
        self.api.patch(f'/api/gestion/tareas/{a.pk}/', {'nombre': 'A2'}, format='json')
        self.api.patch(f'/api/gestion/tareas/{a.pk}/', {'nombre': 'A3'}, format='json')
        punto = next(h for h in self.api.get(f'/api/gestion/proyectos/{self.proyecto.pk}/historial/').data if '«A2»' in h['descripcion'])
        r = self.api.post(f'/api/gestion/proyectos/{self.proyecto.pk}/regresar/', {'historial': punto['id']}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Tarea.objects.get(pk=a.pk).nombre, 'A')
        self.assertTrue(self.proyecto.versiones.filter(nombre__startswith='Antes de regresar').exists())   # nada se pierde
        self.deshacer()                                              # deshacer el regreso
        self.assertEqual(Tarea.objects.get(pk=a.pk).nombre, 'A3')
        self.deshacer()                                              # y seguir hacia atrás
        self.assertEqual(Tarea.objects.get(pk=a.pk).nombre, 'A2')

    def test_versiones_con_nombre_y_respaldo_automatico(self):
        a = self.tarea('Cotizar', LUNES, LUNES)
        r = self.api.post(f'/api/gestion/proyectos/{self.proyecto.pk}/versiones/', {'nombre': 'Plan aprobado'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.api.delete(f'/api/gestion/tareas/{a.pk}/')
        self.tarea('Otra')
        versiones = self.api.get(f'/api/gestion/proyectos/{self.proyecto.pk}/versiones/').data
        plan = next(v for v in versiones if v['nombre'] == 'Plan aprobado')
        self.assertEqual((plan['creado_por'], plan['resumen']['tareas']), ('Ana', 1))
        self.assertTrue(any(v['automatica'] and 'Respaldo automático' in v['nombre'] for v in versiones))

        r = self.api.post(f'/api/gestion/proyectos/{self.proyecto.pk}/restaurar-version/', {'version': plan['id']}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(list(self.proyecto.tareas.values_list('nombre', flat=True)), ['Cotizar'])
        self.assertTrue(self.proyecto.versiones.filter(nombre__startswith='Antes de restaurar').exists())
        self.deshacer()                                              # la restauración también se deshace
        self.assertEqual(list(self.proyecto.tareas.values_list('nombre', flat=True)), ['Otra'])
