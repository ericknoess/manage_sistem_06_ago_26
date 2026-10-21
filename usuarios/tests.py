# usuarios/tests.py — Login, sesión y permisos por rol.

import os

from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from auditoria.models import RegistroAuditoria
from procesos.models import AsignacionFaseOperador, FaseLote, LoteProduccion, OperacionProceso, ProcesoMaestro
from roster.models import Cuadrilla, Operador, RolOperador


def usuario_con_rol(nombre, *roles):
    usuario = User.objects.create_user(nombre, password='clave-de-prueba')
    for rol in roles:
        usuario.groups.add(Group.objects.get(name=rol))
    return usuario


class BaseRoles(TestCase):
    def setUp(self):
        self.proceso = ProcesoMaestro.objects.create(nombre='Receta de prueba')
        self.t1 = OperacionProceso.objects.create(
            proceso=self.proceso, identificador_paso='T1', nombre='Limpieza', orden=1, duracion_horas=2,
        )
        self.rol = RolOperador.objects.create(nombre='Operador base')
        cuadrilla = Cuadrilla.objects.create(identificador='A', nombre='Cuadrilla A')
        self.operador = Operador.objects.create(
            cuadrilla=cuadrilla, nombre='Ana', codigo_empleado='OP-1', rol=self.rol, pin_acceso='1234',
        )
        self.otro_operador = Operador.objects.create(
            cuadrilla=cuadrilla, nombre='Beto', codigo_empleado='OP-2', rol=self.rol, pin_acceso='5678',
        )

    def cliente(self, *roles):
        cliente = APIClient()
        cliente.force_authenticate(usuario_con_rol('-'.join(roles) or 'sin-rol', *roles))
        return cliente

    def crear_lote(self, codigo='L-1'):
        admin, _ = User.objects.get_or_create(username='admin-lotes', defaults={'is_superuser': True})
        cliente = APIClient()
        cliente.force_authenticate(admin)
        respuesta = cliente.post('/api/lotes/', {
            'identificador_lote': codigo, 'proceso_maestro': self.proceso.id, 'fecha_inicio_planeada': '2026-11-02T08:00:00',
        }, format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        lote = LoteProduccion.objects.get(identificador_lote=codigo)
        return lote, FaseLote.objects.get(lote=lote, operacion_maestra=self.t1)


class AccesoSinSesionTests(BaseRoles):
    def test_api_sin_sesion_responde_401(self):
        self.assertEqual(APIClient().get('/api/lotes/').status_code, 401)

    def test_pantallas_piden_login(self):
        respuesta = self.client.get('/planificacion/')
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(respuesta['Location'].startswith('/login/?next=/planificacion/'))

    def test_login_y_terminal_movil_no_piden_sesion(self):
        self.assertEqual(self.client.get('/login/').status_code, 200)
        self.assertEqual(self.client.get('/mobile/').status_code, 200)

    def test_login_entra_y_logout_sale(self):
        usuario_con_rol('planeador', 'Planeador')
        respuesta = self.client.post('/login/', {'username': 'planeador', 'password': 'clave-de-prueba'})
        self.assertRedirects(respuesta, '/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/planificacion/').status_code, 200)
        self.client.post('/logout/')
        self.assertEqual(self.client.get('/planificacion/').status_code, 302)

    def test_sesion_expone_roles_y_permisos(self):
        datos = self.cliente('Planeador').get('/api/sesion/').data
        self.assertEqual(datos['roles'], ['Planeador'])
        self.assertEqual(set(datos['permisos']), {'instanciar_lote', 'reprogramar_fase', 'asignar_personal', 'ajustar_material_lote'})


class PermisosPorRolTests(BaseRoles):
    def nuevo_lote(self, cliente, codigo):
        return cliente.post('/api/lotes/', {
            'identificador_lote': codigo, 'proceso_maestro': self.proceso.id, 'fecha_inicio_planeada': '2026-11-02T08:00:00',
        }, format='json')

    def test_solo_planeador_jefatura_y_admin_crean_lotes(self):
        self.assertEqual(self.nuevo_lote(self.cliente('Planeador'), 'L-P').status_code, 201)
        self.assertEqual(self.nuevo_lote(self.cliente('Jefatura'), 'L-J').status_code, 201)
        for rol in ('Supervisor de turno', 'Ingeniería de procesos', 'Operador', 'Consulta'):
            respuesta = self.nuevo_lote(self.cliente(rol), f'L-{rol}')
            self.assertEqual(respuesta.status_code, 403, rol)
            self.assertIn('crear lotes', respuesta.data['detail'])
        self.assertFalse(LoteProduccion.objects.filter(identificador_lote__startswith='L-S').exists())

    def test_jefatura_planeador_y_supervisor_asignan_tareas(self):
        lote, fase = self.crear_lote()
        for i, rol in enumerate(('Jefatura', 'Planeador', 'Supervisor de turno')):
            AsignacionFaseOperador.objects.all().delete()
            respuesta = self.cliente(rol).post('/api/asignaciones-operador/', {
                'fase_lote': fase.id, 'operador': self.operador.id, 'rol_ejercido': self.rol.id,
            }, format='json')
            self.assertEqual(respuesta.status_code, 201, (rol, respuesta.data))
        respuesta = self.cliente('Consulta').post('/api/asignaciones-operador/', {
            'fase_lote': fase.id, 'operador': self.otro_operador.id, 'rol_ejercido': self.rol.id,
        }, format='json')
        self.assertEqual(respuesta.status_code, 403)

    def test_solo_jefatura_aborta_lotes(self):
        lote, _ = self.crear_lote()
        cuerpo = {'motivo_aborto': 'Contaminación detectada en el inóculo', 'firma_password': 'clave-de-prueba'}
        self.assertEqual(self.cliente('Planeador').post(f'/api/lotes/{lote.id}/abortar/', cuerpo, format='json').status_code, 403)
        self.assertEqual(self.cliente('Jefatura').post(f'/api/lotes/{lote.id}/abortar/', cuerpo, format='json').status_code, 200)

    def test_supervisor_no_reprograma(self):
        _, fase = self.crear_lote()
        cuerpo = {'fecha_programada': '2026-11-03', 'hora_inicio_programada': '09:00', 'motivo_reprogramacion': 'PERSONAL'}
        self.assertEqual(self.cliente('Supervisor de turno').post(f'/api/fases-lote/{fase.id}/reprogramar/', cuerpo, format='json').status_code, 403)
        self.assertEqual(self.cliente('Planeador').post(f'/api/fases-lote/{fase.id}/reprogramar/', cuerpo, format='json').status_code, 200)

    def test_recetas_solo_ingenieria(self):
        cuerpo = {'nombre': 'Receta nueva'}
        self.assertEqual(self.cliente('Planeador').post('/api/procesos-maestros/', cuerpo, format='json').status_code, 403)
        self.assertEqual(self.cliente('Ingeniería de procesos').post('/api/procesos-maestros/', cuerpo, format='json').status_code, 201)
        # Jefatura puede archivar pero no editar
        jefatura = self.cliente('Jefatura')
        self.assertEqual(jefatura.patch(f'/api/procesos-maestros/{self.proceso.id}/', {'nombre': 'X'}, format='json').status_code, 403)
        self.assertEqual(jefatura.post(f'/api/procesos-maestros/{self.proceso.id}/archivar/').status_code, 200)

    def test_catalogo_de_materiales_solo_ingenieria(self):
        cuerpo = {'id': 'MAT-T1', 'nombre': 'Material de prueba', 'unidad_medida': 'L'}
        self.assertEqual(self.cliente('Planeador').post('/api/materiales/', cuerpo, format='json').status_code, 403)
        self.assertEqual(self.cliente('Ingeniería de procesos').post('/api/materiales/', cuerpo, format='json').status_code, 201)

    def test_consulta_lee_pero_no_modifica(self):
        consulta = self.cliente('Consulta')
        self.assertEqual(consulta.get('/api/lotes/').status_code, 200)
        self.assertEqual(consulta.get('/api/cuadrillas/').status_code, 200)
        self.assertEqual(consulta.post('/api/cuadrillas/', {'identificador': 'Z', 'nombre': 'Z'}, format='json').status_code, 403)
        # Validar disponibilidad es un POST de solo consulta
        respuesta = consulta.post(f'/api/operaciones-proceso/{self.t1.id}/validar-disponibilidad/', {'fecha': '2026-11-02'}, format='json')
        self.assertEqual(respuesta.status_code, 200)

    def test_roles_se_combinan(self):
        cliente = self.cliente('Supervisor de turno', 'Planeador')
        self.assertEqual(self.nuevo_lote(cliente, 'L-COMBO').status_code, 201)


class TerminalOperadorTests(BaseRoles):
    def setUp(self):
        super().setUp()
        self.lote, self.fase = self.crear_lote()
        AsignacionFaseOperador.objects.create(fase_lote=self.fase, operador=self.operador, rol_ejercido=self.rol)
        self.movil = APIClient()

    def entrar(self, codigo='OP-1', pin='1234'):
        return self.movil.post('/api/mobile/login/', {'codigo_empleado': codigo, 'pin_acceso': pin}, format='json')

    def test_operador_completa_su_tarea_con_su_pin(self):
        self.assertEqual(self.entrar().status_code, 200)
        self.assertEqual(self.movil.get(f'/api/mobile/{self.operador.id}/tareas-pendientes/').status_code, 200)
        respuesta = self.movil.post(f'/api/fases-lote/{self.fase.id}/cambiar-estado/', {'estado': 'EN_PROGRESO', 'firma_pin': '1234'}, format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)

    def test_operador_no_toca_tareas_ajenas_ni_ve_las_de_otro(self):
        self.entrar('OP-2', '5678')
        respuesta = self.movil.post(f'/api/fases-lote/{self.fase.id}/cambiar-estado/', {'estado': 'EN_PROGRESO', 'firma_pin': '1234'}, format='json')
        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(self.movil.get(f'/api/mobile/{self.operador.id}/tareas-pendientes/').status_code, 403)

    def test_sin_pin_no_hay_cambio_de_estado(self):
        respuesta = self.movil.post(f'/api/fases-lote/{self.fase.id}/cambiar-estado/', {'estado': 'EN_PROGRESO', 'firma_pin': '1234'}, format='json')
        self.assertIn(respuesta.status_code, (401, 403))
        self.fase.refresh_from_db()
        self.assertEqual(self.fase.estado, 'PENDIENTE')

    def test_pin_incorrecto_y_logout(self):
        self.assertEqual(self.entrar(pin='0000').status_code, 401)
        self.entrar()
        self.movil.post('/api/mobile/logout/')
        self.assertEqual(self.movil.get(f'/api/mobile/{self.operador.id}/tareas-pendientes/').status_code, 403)


class FirmaElectronicaTests(BaseRoles):
    """21 CFR Part 11: acciones críticas firmadas con contraseña o PIN, y bloqueo tras intentos fallidos."""

    def setUp(self):
        super().setUp()
        self.lote, self.fase = self.crear_lote()
        self.jefa_usuario = usuario_con_rol('laura', 'Jefatura')
        self.jefa_usuario.first_name = 'Laura'
        self.jefa_usuario.save()
        self.jefa = APIClient()
        self.jefa.force_authenticate(self.jefa_usuario)

    def abortar(self, **firma):
        return self.jefa.post(f'/api/lotes/{self.lote.id}/abortar/', {'motivo_aborto': 'Contaminación detectada en el inóculo', **firma}, format='json')

    def test_sin_firma_no_se_aborta(self):
        respuesta = self.abortar()
        self.assertEqual((respuesta.status_code, respuesta.data['codigo']), (400, 'FIRMA_REQUERIDA'))
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.estado, 'PLANEADO')

    def test_contrasena_incorrecta_no_aborta_y_avisa_intentos(self):
        respuesta = self.abortar(firma_password='mala')
        self.assertEqual(respuesta.data['codigo'], 'FIRMA_INVALIDA')
        self.assertIn('4 intento', respuesta.data['error'])
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.estado, 'PLANEADO')
        self.assertTrue(RegistroAuditoria.objects.filter(accion='FIRMA_FALLIDA').exists())

    def test_firma_valida_queda_ligada_al_registro(self):
        respuesta = self.abortar(firma_password='clave-de-prueba', firma_comentario='Visto con QA')
        self.assertEqual(respuesta.status_code, 200)
        registro = RegistroAuditoria.objects.get(accion='ABORTAR')
        firma = registro.firma
        self.assertEqual((firma.nombre_firmante, firma.significado, firma.metodo, firma.comentario),
                         ('Laura', 'Autorizo el aborto del lote', 'CONTRASENA', 'Visto con QA'))
        self.assertEqual(firma.usuario, self.jefa_usuario)
        # La firma se ve en la bitácora
        datos = self.jefa.get(f'/api/auditoria/?lote={self.lote.id}&accion=ABORTAR').data['resultados'][0]
        self.assertEqual(datos['firma']['significado'], 'Autorizo el aborto del lote')

    def test_cinco_firmas_fallidas_bloquean_la_cuenta(self):
        for _ in range(4):
            self.assertEqual(self.abortar(firma_password='mala').data['codigo'], 'FIRMA_INVALIDA')
        respuesta = self.abortar(firma_password='mala')
        self.assertEqual((respuesta.status_code, respuesta.data['codigo']), (403, 'CUENTA_BLOQUEADA'))
        self.jefa_usuario.refresh_from_db()
        self.assertFalse(self.jefa_usuario.is_active)
        self.assertTrue(self.jefa_usuario.perfil.bloqueado)
        self.assertTrue(RegistroAuditoria.objects.filter(accion='CUENTA_BLOQUEADA').exists())
        # Bloqueada no puede entrar aunque sepa su contraseña
        respuesta = self.client.post('/login/', {'username': 'laura', 'password': 'clave-de-prueba'})
        self.assertContains(respuesta, 'bloqueada')

    def test_firma_correcta_reinicia_el_contador(self):
        self.abortar(firma_password='mala')
        self.abortar(firma_password='clave-de-prueba')
        self.jefa_usuario.perfil.refresh_from_db()
        self.assertEqual(self.jefa_usuario.perfil.intentos_fallidos, 0)

    def test_login_fallido_bloquea_y_comando_desbloquea(self):
        from django.core.management import call_command
        for _ in range(5):
            self.client.post('/login/', {'username': 'laura', 'password': 'mala'})
        self.jefa_usuario.refresh_from_db()
        self.assertTrue(self.jefa_usuario.perfil.bloqueado)
        call_command('desbloquear_usuario', 'laura', stdout=open(os.devnull, 'w'))
        respuesta = self.client.post('/login/', {'username': 'laura', 'password': 'clave-de-prueba'})
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(RegistroAuditoria.objects.filter(accion='CUENTA_DESBLOQUEADA').exists())

    def test_completar_fase_desde_web_pide_firma(self):
        AsignacionFaseOperador.objects.create(fase_lote=self.fase, operador=self.operador, rol_ejercido=self.rol)
        url = f'/api/fases-lote/{self.fase.id}/cambiar-estado/'
        self.assertEqual(self.jefa.post(url, {'estado': 'EN_PROGRESO'}, format='json').data['codigo'], 'FIRMA_REQUERIDA')
        self.assertEqual(self.jefa.post(url, {'estado': 'EN_PROGRESO', 'firma_password': 'clave-de-prueba'}, format='json').status_code, 200)
        self.assertEqual(RegistroAuditoria.objects.get(accion='FASE_EN_PROGRESO').firma.significado, 'Inicio la ejecución de la fase')


class FirmaConPinTests(BaseRoles):
    def setUp(self):
        super().setUp()
        self.lote, self.fase = self.crear_lote()
        AsignacionFaseOperador.objects.create(fase_lote=self.fase, operador=self.operador, rol_ejercido=self.rol)
        self.movil = APIClient()
        self.movil.post('/api/mobile/login/', {'codigo_empleado': 'OP-1', 'pin_acceso': '1234'}, format='json')

    def iniciar(self, pin=None):
        cuerpo = {'estado': 'EN_PROGRESO'}
        if pin is not None:
            cuerpo['firma_pin'] = pin
        return self.movil.post(f'/api/fases-lote/{self.fase.id}/cambiar-estado/', cuerpo, format='json')

    def test_pin_correcto_firma_la_tarea(self):
        self.assertEqual(self.iniciar('1234').status_code, 200)
        firma = RegistroAuditoria.objects.get(accion='FASE_EN_PROGRESO').firma
        self.assertEqual((firma.metodo, firma.operador, firma.nombre_firmante), ('PIN', self.operador, 'Ana (OP-1)'))

    def test_sin_pin_o_pin_incorrecto_no_firma(self):
        self.assertEqual(self.iniciar().data['codigo'], 'FIRMA_REQUERIDA')
        self.assertEqual(self.iniciar('0000').data['codigo'], 'FIRMA_INVALIDA')
        self.fase.refresh_from_db()
        self.assertEqual(self.fase.estado, 'PENDIENTE')

    def test_cinco_pines_fallidos_bloquean_y_cierran_la_terminal(self):
        for _ in range(4):
            self.iniciar('0000')
        respuesta = self.iniciar('0000')
        self.assertEqual(respuesta.data['codigo'], 'CUENTA_BLOQUEADA')
        self.operador.refresh_from_db()
        self.assertTrue(self.operador.pin_bloqueado)
        # La sesión de la terminal se cerró y el PIN bloqueado no deja volver a entrar
        self.assertEqual(self.movil.get(f'/api/mobile/{self.operador.id}/tareas-pendientes/').status_code, 403)
        self.assertEqual(self.movil.post('/api/mobile/login/', {'codigo_empleado': 'OP-1', 'pin_acceso': '1234'}, format='json').status_code, 403)

    def test_ingreso_fallido_tambien_cuenta(self):
        otro = APIClient()
        for _ in range(5):
            respuesta = otro.post('/api/mobile/login/', {'codigo_empleado': 'OP-2', 'pin_acceso': '0000'}, format='json')
        self.assertEqual(respuesta.status_code, 403)
        self.otro_operador.refresh_from_db()
        self.assertTrue(self.otro_operador.pin_bloqueado)
        from usuarios.firmas import desbloquear_pin
        desbloquear_pin(self.otro_operador)
        self.assertEqual(otro.post('/api/mobile/login/', {'codigo_empleado': 'OP-2', 'pin_acceso': '5678'}, format='json').status_code, 200)

    def test_firma_no_se_modifica(self):
        from django.core.exceptions import PermissionDenied
        self.iniciar('1234')
        firma = RegistroAuditoria.objects.get(accion='FASE_EN_PROGRESO').firma
        firma.significado = 'otro'
        with self.assertRaises(PermissionDenied):
            firma.save()


class TerminalCompartidaTests(BaseRoles):
    """Tablet donde alguien dejó abierta una sesión web: la terminal debe quedar solo con el operador."""

    def setUp(self):
        super().setUp()
        self.lote, self.fase = self.crear_lote()
        AsignacionFaseOperador.objects.create(fase_lote=self.fase, operador=self.operador, rol_ejercido=self.rol)
        usuario_con_rol('supervisor', 'Supervisor de turno')
        self.tablet = APIClient(enforce_csrf_checks=False)
        self.assertTrue(self.tablet.login(username='supervisor', password='clave-de-prueba'))

    def test_operador_firma_con_pin_aunque_hubiera_sesion_web(self):
        self.tablet.post('/api/mobile/login/', {'codigo_empleado': 'OP-1', 'pin_acceso': '1234'}, format='json')
        respuesta = self.tablet.post(f'/api/fases-lote/{self.fase.id}/cambiar-estado/',
                                     {'estado': 'EN_PROGRESO', 'firma_pin': '1234'}, format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        registro = RegistroAuditoria.objects.get(accion='FASE_EN_PROGRESO')
        # La acción y la firma son del operador, no del supervisor que había dejado la sesión abierta
        self.assertEqual((registro.operador, registro.usuario), (self.operador, None))
        self.assertEqual(registro.firma.metodo, 'PIN')
        ingreso = RegistroAuditoria.objects.get(accion='PIN_LOGIN')
        self.assertEqual((ingreso.operador, ingreso.usuario), (self.operador, None))

    def test_login_web_cierra_la_terminal_del_operador(self):
        self.tablet.logout()
        self.tablet.post('/api/mobile/login/', {'codigo_empleado': 'OP-1', 'pin_acceso': '1234'}, format='json')
        self.assertTrue(self.tablet.login(username='supervisor', password='clave-de-prueba'))
        self.assertNotIn('operador_id', self.tablet.session)
