# auditoria/tests.py — La bitácora registra quién, qué, cuándo y por qué, y no se puede alterar.

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from rest_framework.test import APIClient

from actividades.models import MaterialInsumo
from procesos.models import FaseLote, LoteProduccion, MaterialOperacion, OperacionProceso, ProcesoMaestro
from roster.models import Cuadrilla, Operador, RolOperador

from auditoria.models import RegistroAuditoria


def usuario(nombre, rol, completo=''):
    u = User.objects.create_user(nombre, password='clave-de-prueba', first_name=completo)
    u.groups.add(Group.objects.get(name=rol))
    return u


class BitacoraTests(TestCase):
    def setUp(self):
        self.proceso = ProcesoMaestro.objects.create(nombre='Receta A')
        self.t1 = OperacionProceso.objects.create(proceso=self.proceso, identificador_paso='T1', nombre='Limpieza', orden=1, duracion_horas=2)
        self.t2 = OperacionProceso.objects.create(proceso=self.proceso, identificador_paso='T2', nombre='Siembra', orden=2,
                                                  duracion_horas=3, predecesora=self.t1)
        self.material = MaterialInsumo.objects.create(id='MAT-A', nombre='Medio A', unidad_medida='L')
        MaterialOperacion.objects.create(operacion=self.t1, material=self.material, cantidad=2)
        self.rol = RolOperador.objects.create(nombre='Operador base')
        cuadrilla = Cuadrilla.objects.create(identificador='A', nombre='Cuadrilla A')
        self.operador = Operador.objects.create(cuadrilla=cuadrilla, nombre='Ana', codigo_empleado='OP-1', rol=self.rol, pin_acceso='1234')

        self.planeador = APIClient()
        self.planeador.force_authenticate(usuario('carlos', 'Planeador', 'Carlos'))
        self.jefa = APIClient()
        self.jefa.force_authenticate(usuario('laura', 'Jefatura', 'Laura'))

    def crear_lote(self):
        respuesta = self.planeador.post('/api/lotes/', {
            'identificador_lote': 'L-1', 'proceso_maestro': self.proceso.id, 'fecha_inicio_planeada': '2026-11-02T08:00:00',
        }, format='json')
        self.assertEqual(respuesta.status_code, 201)
        lote = LoteProduccion.objects.get(identificador_lote='L-1')
        return lote, FaseLote.objects.get(lote=lote, operacion_maestra=self.t1)

    def ultimo(self, **filtro):
        return RegistroAuditoria.objects.filter(**filtro).latest('id')

    def test_crear_lote_registra_quien_y_rol(self):
        lote, _ = self.crear_lote()
        registro = self.ultimo(categoria='LOTE', accion='CREAR')
        self.assertEqual(registro.actor, 'Carlos')
        self.assertEqual(registro.roles, 'Planeador')
        self.assertEqual(registro.lote, lote)
        self.assertEqual(registro.cambios['receta'], [None, 'Receta A'])

    def test_abortar_guarda_motivo_y_estado(self):
        lote, _ = self.crear_lote()
        self.jefa.post(f'/api/lotes/{lote.id}/abortar/', {'motivo_aborto': 'Contaminación en el inóculo', 'firma_password': 'clave-de-prueba'}, format='json')
        registro = self.ultimo(accion='ABORTAR')
        self.assertEqual((registro.actor, registro.motivo), ('Laura', 'Contaminación en el inóculo'))
        self.assertEqual(registro.cambios['estado'], ['PLANEADO', 'ABORTADO'])

    def test_reprogramar_guarda_antes_despues_y_motivo(self):
        _, fase = self.crear_lote()
        self.planeador.post(f'/api/fases-lote/{fase.id}/reprogramar/', {
            'fecha_programada': '2026-11-02', 'hora_inicio_programada': '10:00',
            'motivo_reprogramacion': 'PERSONAL', 'notas_reprogramacion': 'Falta un operador',
        }, format='json')
        registro = self.ultimo(accion='REPROGRAMAR')
        self.assertEqual(registro.fase, fase)
        self.assertEqual(registro.cambios['inicio_programado'], ['2026-11-02 08:00', '2026-11-02 10:00'])
        self.assertIn('Falta un operador', registro.motivo)

    def test_asignar_y_retirar_operador(self):
        _, fase = self.crear_lote()
        respuesta = self.jefa.post('/api/asignaciones-operador/', {
            'fase_lote': fase.id, 'operador': self.operador.id, 'rol_ejercido': self.rol.id,
        }, format='json')
        self.jefa.delete(f"/api/asignaciones-operador/{respuesta.data['id']}/")
        acciones = list(RegistroAuditoria.objects.filter(categoria='ASIGNACION', fase=fase).order_by('id').values_list('accion', flat=True))
        self.assertEqual(acciones, ['CREAR', 'ELIMINAR'])
        self.assertEqual(self.ultimo(categoria='ASIGNACION').cambios['operador'], ['Ana', None])

    def test_operador_con_pin_queda_como_actor(self):
        _, fase = self.crear_lote()
        self.jefa.post('/api/asignaciones-operador/', {'fase_lote': fase.id, 'operador': self.operador.id, 'rol_ejercido': self.rol.id}, format='json')
        movil = APIClient()
        movil.post('/api/mobile/login/', {'codigo_empleado': 'OP-1', 'pin_acceso': '1234'}, format='json')
        movil.post(f'/api/fases-lote/{fase.id}/cambiar-estado/', {'estado': 'EN_PROGRESO', 'firma_pin': '1234'}, format='json')
        registro = self.ultimo(accion='FASE_EN_PROGRESO')
        self.assertEqual((registro.operador, registro.usuario), (self.operador, None))
        self.assertEqual(registro.actor, 'Ana (OP-1)')
        # El lote pasa a EN_PROGRESO y también queda registrado
        self.assertTrue(RegistroAuditoria.objects.filter(accion='LOTE_EN_PROGRESO').exists())
        self.assertTrue(RegistroAuditoria.objects.filter(accion='PIN_LOGIN', operador=self.operador).exists())

    def test_ajuste_de_material_guarda_cantidades(self):
        _, fase = self.crear_lote()
        mf = fase.materiales.get()
        self.planeador.post(f'/api/materiales-fase/{mf.id}/ajustar/', {'cantidad': '3.5', 'motivo': 'Lote más grande'}, format='json')
        registro = self.ultimo(categoria='MATERIAL_LOTE')
        self.assertEqual(registro.cambios['cantidad'], ['2 L', '3.5 L'])
        self.assertEqual(registro.motivo, 'Lote más grande')

    def test_editar_receta_guarda_solo_lo_que_cambio(self):
        ingeniero = APIClient()
        ingeniero.force_authenticate(usuario('ivan', 'Ingeniería de procesos'))
        ingeniero.patch(f'/api/procesos-maestros/{self.proceso.id}/', {'nombre': 'Receta B'}, format='json')
        registro = self.ultimo(categoria='RECETA', accion='EDITAR')
        self.assertEqual(registro.cambios, {'nombre': ['Receta A', 'Receta B']})

    def test_login_logout_y_fallido(self):
        usuario('sara', 'Supervisor de turno')
        self.client.post('/login/', {'username': 'sara', 'password': 'mala'})
        self.client.post('/login/', {'username': 'sara', 'password': 'clave-de-prueba'})
        self.client.post('/logout/')
        acciones = list(RegistroAuditoria.objects.filter(categoria='SESION').order_by('id').values_list('accion', flat=True))
        self.assertEqual(acciones, ['LOGIN_FALLIDO', 'LOGIN', 'LOGOUT'])

    def test_no_guarda_pin_ni_contrasenas(self):
        admin = APIClient()
        admin.force_authenticate(User.objects.create_superuser('root', password='x'))
        admin.patch(f'/api/operadores/{self.operador.id}/', {'pin_acceso': '9999', 'nombre': 'Ana María'}, format='json')
        for registro in RegistroAuditoria.objects.all():
            self.assertNotIn('pin', str(registro.cambios).lower())

    def test_bitacora_no_se_edita_ni_borra(self):
        self.crear_lote()
        registro = RegistroAuditoria.objects.latest('id')
        registro.descripcion = 'alterado'
        with self.assertRaises(PermissionDenied):
            registro.save()
        with self.assertRaises(PermissionDenied):
            registro.delete()
        # La API es de solo lectura
        self.assertEqual(self.jefa.delete(f'/api/auditoria/{registro.id}/').status_code, 405)

    def test_api_filtra_por_lote(self):
        lote, fase = self.crear_lote()
        self.planeador.post(f'/api/fases-lote/{fase.id}/reprogramar/', {
            'fecha_programada': '2026-11-02', 'hora_inicio_programada': '11:00', 'motivo_reprogramacion': 'OTRO',
        }, format='json')
        datos = self.jefa.get(f'/api/auditoria/?lote={lote.id}').data
        self.assertEqual(datos['total'], 2)
        self.assertEqual({r['accion'] for r in datos['resultados']}, {'CREAR', 'REPROGRAMAR'})
        self.assertEqual(self.jefa.get(f'/api/auditoria/?fase={fase.id}').data['total'], 1)
