# datos_proceso/tests.py

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from auditoria.models import FirmaElectronica, RegistroAuditoria
from procesos.models import AsignacionFaseOperador, EtapaProceso, FaseLote, LoteProduccion, OperacionProceso, ProcesoMaestro
from roster.models import Cuadrilla, Operador, RolOperador
from .formulas import ErrorFormula, evaluar, variables
from .models import ParametroProceso, SeccionCaptura, TomaDatos, ValorParametro
from .services import edades_cero


def usuario_con_rol(nombre, rol):
    usuario = User.objects.create_user(nombre, password='clave-de-prueba')
    usuario.groups.add(Group.objects.get(name=rol))
    return usuario


class FormulasTests(TestCase):

    def test_variables_y_calculo(self):
        self.assertEqual(variables("flujo_total * mezcla_o2 / 100"), ['flujo_total', 'mezcla_o2'])
        self.assertAlmostEqual(evaluar("flujo_total * mezcla_o2 / 100", {'flujo_total': 2, 'mezcla_o2': 25}), 0.5)
        self.assertEqual(evaluar("round(sqrt(x), 1)", {'x': 2}), 1.4)

    def test_falta_un_dato_o_division_entre_cero_da_vacio(self):
        self.assertIsNone(evaluar("a / b", {'a': 1}))
        self.assertIsNone(evaluar("a / b", {'a': 1, 'b': 0}))
        self.assertIsNone(evaluar("log(a)", {'a': -1}))

    def test_rechaza_lo_que_no_es_un_calculo(self):
        for formula in ("__import__('os').system('ls')", "a.b", "lambda: 1", "[1, 2]", "a if b else c", "'texto'", "a == b"):
            with self.subTest(formula=formula), self.assertRaises(ErrorFormula):
                variables(formula)


class CatalogoParametrosTests(TestCase):

    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(usuario_con_rol('ingeniera', 'Ingeniería de procesos'))

    def crear(self, **datos):
        return self.api.post('/api/parametros-proceso/', {'tipo_dato': 'NUMERO', 'decimales': 2, **datos}, format='json')

    def test_alta_de_parametro_y_calculado(self):
        self.assertEqual(self.crear(codigo='rot_l', nombre='Rotámetro L', unidad='mm').status_code, 201)
        r = self.crear(codigo='flujo_total', nombre='Flujo total', unidad='L/min', formula='0.0139 * rot_l + 0.059')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['variables'], ['rot_l'])
        self.assertTrue(RegistroAuditoria.objects.filter(categoria='CATALOGO', accion='CREAR').exists())

    def test_codigo_invalido_o_inmutable(self):
        self.assertEqual(self.crear(codigo='pH Externo', nombre='pH').status_code, 400)
        self.assertEqual(self.crear(codigo='round', nombre='Redondeo').status_code, 400)
        r = self.crear(codigo='ph', nombre='pH')
        cambio = self.api.patch(f"/api/parametros-proceso/{r.data['id']}/", {'codigo': 'ph2'}, format='json')
        self.assertEqual(cambio.status_code, 400)

    def test_formula_con_parametro_inexistente_no_numerico_o_circular(self):
        self.crear(codigo='a', nombre='A')
        self.crear(codigo='aspecto', nombre='Aspecto', tipo_dato='OPCION', opciones=['Normal', 'Turbio'])
        self.assertIn('No existe', str(self.crear(codigo='b', nombre='B', formula='a + zz').data))
        self.assertIn('no es numérico', str(self.crear(codigo='c', nombre='C', formula='aspecto * 2').data))
        b = self.crear(codigo='b', nombre='B', formula='a * 2')
        self.assertEqual(b.status_code, 201)
        self.crear(codigo='c', nombre='C', formula='b + 1')
        # a no puede pasar a depender de c (c → b → a)
        a = ParametroProceso.objects.get(codigo='a')
        r = self.api.patch(f'/api/parametros-proceso/{a.id}/', {'formula': 'c / 2'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('circular', str(r.data))

    def test_opciones_requieren_al_menos_dos(self):
        r = self.crear(codigo='aspecto', nombre='Aspecto', tipo_dato='OPCION', opciones=['Normal'])
        self.assertEqual(r.status_code, 400)

    def test_rol_sin_permiso_no_modifica_el_catalogo(self):
        consulta = APIClient()
        consulta.force_authenticate(usuario_con_rol('consulta', 'Consulta'))
        r = consulta.post('/api/parametros-proceso/', {'codigo': 'ph', 'nombre': 'pH'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(consulta.get('/api/parametros-proceso/').status_code, 200)


class CapturaBase(TestCase):
    """
    Receta (etapa PO4):  T1 Inoculación (1 h, define la edad 0 de PO4 y del lote al completar)
                         → T2 Incubación (24 h, muestreo cada 6 h con muestreo inicial, captura en muestreos)
                         → T3 Cuenta final (1 h, captura al completar)
    Secciones de T2: Reactor (todos), Metabolitos (cada 12 h, muestra PO41-M{n}), Cuenta (a las 0 y 24 h).
    """

    def setUp(self):
        self.admin = APIClient()
        self.admin.force_authenticate(usuario_con_rol('admin', 'Administrador'))
        crear = lambda codigo, nombre, **extra: ParametroProceso.objects.create(codigo=codigo, nombre=nombre, **extra)
        self.temp = crear('temp', 'Temperatura', unidad='°C', decimales=1)
        self.rot_l = crear('rot_l', 'Rotámetro L', decimales=1)
        self.mezcla_o2 = crear('mezcla_o2', 'Mezcla O2', unidad='%', decimales=1)
        self.flujo_total = crear('flujo_total', 'Flujo total', unidad='L/min', decimales=3, formula='0.0139 * rot_l + 0.059')
        self.flujo_o2 = crear('flujo_o2', 'Flujo O2', unidad='L/min', decimales=3, formula='flujo_total * mezcla_o2 / 100')
        self.aspecto = crear('aspecto', 'Aspecto', tipo_dato='OPCION', opciones=['Normal', 'Espuma'])
        self.glucosa = crear('glucosa', 'Glucosa', unidad='g/L')
        self.celulas = crear('celulas', 'Células', unidad='MCel/mL')
        self.viabilidad = crear('viabilidad', 'Viabilidad', unidad='%', decimales=1)

        self.proceso = ProcesoMaestro.objects.create(nombre='EPO prueba')
        self.etapa = EtapaProceso.objects.create(proceso=self.proceso, nombre='PO4', orden=1)
        self.t1 = self.crear_operacion({
            'identificador_paso': 'T1', 'nombre': 'Inoculación', 'tipo_operacion': 'ACTIVA', 'duracion_horas': 1,
            'edad_cero': 'FIN', 'edad_cero_lote': True,
        })
        self.t2 = self.crear_operacion({
            'identificador_paso': 'T2', 'nombre': 'Incubación', 'tipo_operacion': 'INCUBACION', 'duracion_horas': 24,
            'frecuencia_muestreo_horas': 6, 'duracion_muestreo_horas': 0.5, 'ops_muestreo': 1, 'muestreo_inicial': True,
            'predecesora': self.t1.id, 'captura_datos': 'MUESTREOS', 'secciones_captura': [
                {'nombre': 'Reactor', 'frecuencia': 'TODOS', 'parametros': [
                    self.p(self.temp, especificacion_min='36', especificacion_max='38', alerta_min='36.5', alerta_max='37.5'),
                    self.p(self.rot_l), self.p(self.mezcla_o2), self.p(self.flujo_total), self.p(self.flujo_o2),
                    self.p(self.aspecto, obligatorio=False)]},
                {'nombre': 'Metabolitos', 'frecuencia': 'CADA_N', 'cada_horas': 12, 'muestra_fisica': True,
                 'patron_codigo_muestra': 'PO41-M{n}', 'parametros': [self.p(self.glucosa)]},
                {'nombre': 'Cuenta', 'frecuencia': 'HORAS', 'horas': [0, 24], 'parametros': [self.p(self.celulas), self.p(self.viabilidad)]},
            ],
        })
        self.t3 = self.crear_operacion({
            'identificador_paso': 'T3', 'nombre': 'Cuenta final', 'tipo_operacion': 'ACTIVA', 'duracion_horas': 1,
            'predecesora': self.t2.id, 'captura_datos': 'COMPLETAR', 'secciones_captura': [
                {'nombre': 'Cuenta', 'parametros': [self.p(self.celulas)]},
            ],
        })

        self.rol = RolOperador.objects.create(nombre='Operador base')
        cuadrilla = Cuadrilla.objects.create(identificador='A', nombre='Cuadrilla A')
        self.operador = Operador.objects.create(cuadrilla=cuadrilla, nombre='Ana', codigo_empleado='OP-1', rol=self.rol, pin_acceso='1234')

        inicio = timezone.localtime(timezone.now()).replace(second=0, microsecond=0, tzinfo=None)
        r = self.admin.post('/api/lotes/', {'identificador_lote': 'L-1', 'proceso_maestro': self.proceso.id,
                                            'fecha_inicio_planeada': inicio.isoformat()}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.lote = LoteProduccion.objects.get(identificador_lote='L-1')

    @staticmethod
    def p(parametro, **extra):
        return {'parametro': parametro.id, 'obligatorio': True, **extra}

    def crear_operacion(self, datos, esperado=201):
        r = self.admin.post('/api/operaciones-proceso/', {'proceso': self.proceso.id, 'etapa': self.etapa.id, **datos}, format='json')
        self.assertEqual(r.status_code, esperado, r.data)
        return OperacionProceso.objects.get(pk=r.data['id']) if esperado == 201 else r

    def muestreo(self, indice):
        return FaseLote.objects.get(lote=self.lote, operacion_maestra=self.t2, es_subtarea_muestreo=True, indice_muestreo=indice)

    def actividad(self, operacion):
        return FaseLote.objects.get(lote=self.lote, operacion_maestra=operacion, es_subtarea_muestreo=False)

    def forzar(self, fase, estado, momento=None):
        """Cambia el estado sin pasar por la API (para preparar escenarios)."""
        momento = momento or timezone.now()
        fase.estado = estado
        if estado in ('EN_PROGRESO', 'COMPLETADA') and not fase.fecha_inicio_real:
            fase.fecha_inicio_real = momento
        if estado == 'COMPLETADA':
            fase.fecha_fin_real = momento
        fase.save()
        return fase

    def valores_reactor(self, temp='37.0'):
        return {self.temp.id: temp, self.rot_l.id: '100', self.mezcla_o2.id: '20'}

    def registrar(self, cliente, fase, valores, **extra):
        return cliente.post(f'/api/captura/{fase.id}/registrar/', {'valores': valores, **extra}, format='json')


class RecetaYPlanTests(CapturaBase):

    def test_plan_de_cada_muestreo_segun_sus_secciones(self):
        horas = {m.indice_muestreo * 6: m for m in FaseLote.objects.filter(lote=self.lote, operacion_maestra=self.t2, es_subtarea_muestreo=True)}
        self.assertEqual(sorted(horas), [0, 6, 12, 18, 24])  # incluye el muestreo inicial M-0h
        secciones = lambda h: [s['nombre'] for s in horas[h].plan_captura['secciones']]
        self.assertEqual(secciones(0), ['Reactor', 'Metabolitos', 'Cuenta'])
        self.assertEqual(secciones(6), ['Reactor'])
        self.assertEqual(secciones(12), ['Reactor', 'Metabolitos'])
        self.assertEqual(secciones(24), ['Reactor', 'Metabolitos', 'Cuenta'])
        codigos = [next(s['codigo_muestra'] for s in horas[h].plan_captura['secciones'] if s['nombre'] == 'Metabolitos') for h in (0, 12, 24)]
        self.assertEqual(codigos, ['PO41-M01', 'PO41-M02', 'PO41-M03'])
        # La incubación misma no captura (lo hacen sus muestreos); la cuenta final sí, al completar
        self.assertEqual(self.actividad(self.t2).plan_captura, {})
        self.assertEqual([s['nombre'] for s in self.actividad(self.t3).plan_captura['secciones']], ['Cuenta'])

    def test_editar_la_receta_no_cambia_un_lote_en_curso(self):
        SeccionCaptura.objects.filter(operacion=self.t2, nombre='Metabolitos').delete()
        self.assertIn('Metabolitos', [s['nombre'] for s in self.muestreo(2).plan_captura['secciones']])

    def test_reglas_del_disenador(self):
        base = {'identificador_paso': 'T9', 'nombre': 'Otra', 'tipo_operacion': 'INCUBACION', 'duracion_horas': 24,
                'frecuencia_muestreo_horas': 6, 'captura_datos': 'MUESTREOS'}
        seccion = lambda **extra: [{'nombre': 'S', 'parametros': [self.p(self.glucosa)], **extra}]
        casos = [
            ({**base, 'secciones_captura': seccion(frecuencia='CADA_N', cada_horas=8)}, 'múltiplo'),
            ({**base, 'secciones_captura': seccion(frecuencia='HORAS', horas=[0, 7])}, 'no hay muestreo'),
            ({**base, 'tipo_operacion': 'ACTIVA', 'frecuencia_muestreo_horas': 0, 'secciones_captura': seccion()}, 'incubación'),
            ({**base, 'secciones_captura': []}, 'al menos una sección'),
            ({**base, 'secciones_captura': [{'nombre': 'A', 'parametros': [self.p(self.glucosa)]},
                                            {'nombre': 'B', 'parametros': [self.p(self.glucosa)]}]}, 'déjalo solo en una'),
            ({**base, 'captura_datos': 'NINGUNA', 'edad_cero': 'INICIO'}, 'ya la define'),
            ({**base, 'captura_datos': 'NINGUNA', 'edad_cero_lote': True}, 'debe definir la edad 0'),
        ]
        for datos, mensaje in casos:
            with self.subTest(mensaje=mensaje):
                r = self.crear_operacion(datos, esperado=400)
                self.assertIn(mensaje, str(r.data))

    def test_clonar_receta_copia_captura_y_edad_cero(self):
        r = self.admin.post(f'/api/procesos-maestros/{self.proceso.id}/clonar/', {'nuevo_nombre': 'EPO copia'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        copia = OperacionProceso.objects.get(proceso_id=r.data['nuevo_id'], identificador_paso='T2')
        self.assertEqual(copia.captura_datos, 'MUESTREOS')
        self.assertTrue(copia.muestreo_inicial)
        self.assertEqual([s.nombre for s in copia.secciones_captura.all()], ['Reactor', 'Metabolitos', 'Cuenta'])
        self.assertEqual(copia.secciones_captura.get(nombre='Reactor').parametros.count(), 6)
        self.assertEqual(OperacionProceso.objects.get(proceso_id=r.data['nuevo_id'], identificador_paso='T1').edad_cero, 'FIN')

    def test_valor_esperado_y_curva_de_la_tendencia(self):
        from .services import plan_de_operacion
        base = {'identificador_paso': 'T4', 'nombre': 'Lavado', 'tipo_operacion': 'ACTIVA', 'duracion_horas': 1,
                'captura_datos': 'COMPLETAR'}
        seccion = lambda **extra: [{'nombre': 'Metabolitos', 'parametros': [self.p(self.glucosa, **extra)]}]
        op = self.crear_operacion({**base, 'secciones_captura': seccion(
            objetivo='0.8', eje_edad='ETAPA', curva_referencia=[[24, 2.1], [0, 3.5], ['12', '2,8'.replace(',', '.')]])})
        ps = op.secciones_captura.get().parametros.get()
        self.assertEqual(ps.curva_referencia, [[0.0, 3.5], [12.0, 2.8], [24.0, 2.1]])  # se ordena por edad
        ref = plan_de_operacion(op)['secciones'][0]['parametros'][0]['referencia']
        self.assertEqual(ref, {'objetivo': '0.8', 'curva': [[0.0, 3.5], [12.0, 2.8], [24.0, 2.1]], 'eje_edad': 'ETAPA'})
        casos = [
            (seccion(curva_referencia=[[0, 1], [0, 2]]), 'repetidas'),
            (seccion(curva_referencia=[[-1, 1]]), 'negativas'),
            (seccion(curva_referencia=[[1, 'x']]), 'dos números'),
            ([{'nombre': 'S', 'parametros': [self.p(self.aspecto, objetivo='1')]}], 'no es numérico'),
        ]
        for i, (secciones, mensaje) in enumerate(casos):
            with self.subTest(mensaje=mensaje):
                r = self.crear_operacion({**base, 'identificador_paso': f'T{5 + i}', 'secciones_captura': secciones}, esperado=400)
                self.assertIn(mensaje, str(r.data))


class CapturaEnPlantaTests(CapturaBase):

    def setUp(self):
        super().setUp()
        self.web = APIClient()
        self.web.force_authenticate(usuario_con_rol('supervisora', 'Jefatura'))
        self.hito = timezone.now() - timedelta(hours=12, minutes=30)
        self.forzar(self.actividad(self.t1), 'COMPLETADA', self.hito)
        self.forzar(self.actividad(self.t2), 'EN_PROGRESO', self.hito)
        self.m12 = self.forzar(self.muestreo(2), 'EN_PROGRESO')

    def test_registra_calcula_y_marca_limites(self):
        r = self.registrar(self.web, self.m12, {**self.valores_reactor(temp='38.4'), self.glucosa.id: '4.5', self.aspecto.id: 'Espuma'})
        self.assertEqual(r.status_code, 201, r.data)
        valores = {v.parametro.codigo: v for v in ValorParametro.objects.filter(toma__fase=self.m12)}
        self.assertEqual(valores['flujo_total'].valor_numero, Decimal('1.449'))   # 0.0139 × 100 + 0.059
        self.assertEqual(valores['flujo_o2'].valor_numero, Decimal('0.290'))      # calculado a partir de otro calculado
        self.assertTrue(valores['flujo_o2'].calculado)
        self.assertTrue(valores['temp'].fuera_especificacion)
        self.assertEqual(valores['aspecto'].valor_texto, 'Espuma')
        self.assertEqual(TomaDatos.objects.get(fase=self.m12).codigos_muestra, {'Metabolitos': 'PO41-M02'})
        self.assertTrue(any('fuera de especificación' in a for a in r.data['avisos']))
        self.assertEqual(r.data['toma']['edad_etapa_h'], r.data['toma']['edad_lote_h'])
        self.assertAlmostEqual(r.data['toma']['edad_etapa_h'], 12.5, delta=0.05)  # edad real desde el fin de la inoculación
        self.assertTrue(RegistroAuditoria.objects.filter(categoria='DATOS_PROCESO', accion='REGISTRAR_DATOS', fase=self.m12).exists())

    def test_obligatorios_y_una_sola_toma(self):
        r = self.registrar(self.web, self.m12, self.valores_reactor())
        self.assertEqual(r.status_code, 400)
        self.assertIn('Glucosa', r.data['error'])
        self.assertEqual(self.registrar(self.web, self.m12, {**self.valores_reactor(), self.glucosa.id: '4'}).status_code, 201)
        self.assertEqual(self.registrar(self.web, self.m12, {**self.valores_reactor(), self.glucosa.id: '4'}).status_code, 400)

    def test_valores_no_validos(self):
        r = self.registrar(self.web, self.m12, {**self.valores_reactor(), self.glucosa.id: 'cuatro', self.aspecto.id: 'Rara'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('Glucosa', r.data['error'])
        self.assertIn('Aspecto', r.data['error'])

    def test_no_se_captura_si_la_tarea_no_esta_en_curso(self):
        m18 = self.muestreo(3)
        r = self.registrar(self.web, m18, self.valores_reactor())
        self.assertEqual(r.status_code, 400)
        self.assertIn('iníciala', r.data['error'])

    def test_no_se_completa_sin_los_datos(self):
        cuerpo = {'estado': 'COMPLETADA', 'firma_password': 'clave-de-prueba'}
        AsignacionFaseOperador.objects.create(fase_lote=self.m12, operador=self.operador, rol_ejercido=self.rol)
        r = self.web.post(f'/api/fases-lote/{self.m12.id}/cambiar-estado/', cuerpo, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['codigo'], 'DATOS_PENDIENTES')
        self.registrar(self.web, self.m12, {**self.valores_reactor(), self.glucosa.id: '4'})
        r = self.web.post(f'/api/fases-lote/{self.m12.id}/cambiar-estado/', cuerpo, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_vista_previa_calcula_sin_guardar(self):
        r = self.web.post(f'/api/captura/{self.m12.id}/vista-previa/', {'valores': self.valores_reactor()}, format='json')
        self.assertEqual(r.status_code, 200)
        calculado = next(v for v in r.data['valores'] if v['parametro'] == self.flujo_total.id)
        self.assertEqual(calculado['valor'], '1.449')
        self.assertEqual(r.data['faltantes'], ['Glucosa'])
        self.assertFalse(TomaDatos.objects.exists())

    def test_correccion_con_motivo_y_firma_recalcula(self):
        self.registrar(self.web, self.m12, {**self.valores_reactor(), self.glucosa.id: '4'})
        toma = TomaDatos.objects.get(fase=self.m12)
        url = f'/api/captura/{self.m12.id}/corregir/'
        cuerpo = {'toma': toma.id, 'parametro': self.rot_l.id, 'valor': '120'}
        sin_motivo = self.web.post(url, {**cuerpo, 'firma_password': 'clave-de-prueba'}, format='json')
        self.assertEqual(sin_motivo.data['codigo'], 'MOTIVO_REQUERIDO')
        mala_firma = self.web.post(url, {**cuerpo, 'motivo': 'Lectura mal transcrita', 'firma_password': 'otra'}, format='json')
        self.assertEqual(mala_firma.data['codigo'], 'FIRMA_INVALIDA')

        r = self.web.post(url, {**cuerpo, 'motivo': 'Lectura mal transcrita', 'firma_password': 'clave-de-prueba'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        rot = ValorParametro.objects.filter(toma=toma, parametro=self.rot_l)
        self.assertEqual(rot.count(), 2)
        self.assertEqual(rot.get(vigente=True).valor_numero, Decimal('120.0'))
        self.assertEqual(rot.get(vigente=True).reemplaza, rot.get(vigente=False))
        flujo = ValorParametro.objects.get(toma=toma, parametro=self.flujo_total, vigente=True)
        self.assertEqual(flujo.valor_numero, Decimal('1.727'))  # recalculado: 0.0139 × 120 + 0.059
        registro = RegistroAuditoria.objects.get(accion='CORREGIR_DATO')
        self.assertEqual(registro.cambios['rot_l'], ['100', '120'])
        self.assertIn('flujo_total', registro.cambios)
        self.assertTrue(FirmaElectronica.objects.filter(registro=registro).exists())

    def test_no_se_corrige_un_calculado_ni_se_borra_un_dato(self):
        self.registrar(self.web, self.m12, {**self.valores_reactor(), self.glucosa.id: '4'})
        toma = TomaDatos.objects.get(fase=self.m12)
        r = self.web.post(f'/api/captura/{self.m12.id}/corregir/', {
            'toma': toma.id, 'parametro': self.flujo_total.id, 'valor': '2', 'motivo': 'Prueba de corrección', 'firma_password': 'clave-de-prueba',
        }, format='json')
        self.assertEqual(r.status_code, 400)
        with self.assertRaises(PermissionError):
            toma.delete()

    def test_operador_con_pin_solo_en_sus_tareas(self):
        movil = APIClient()
        movil.post('/api/mobile/login/', {'codigo_empleado': 'OP-1', 'pin_acceso': '1234'}, format='json')
        valores = {**self.valores_reactor(), self.glucosa.id: '4'}
        self.assertEqual(self.registrar(movil, self.m12, valores).status_code, 403)
        AsignacionFaseOperador.objects.create(fase_lote=self.m12, operador=self.operador, rol_ejercido=self.rol)
        r = self.registrar(movil, self.m12, valores)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(TomaDatos.objects.get(fase=self.m12).registrado_por_operador, self.operador)

    def test_rol_sin_ejecutar_fase_no_captura(self):
        consulta = APIClient()
        consulta.force_authenticate(usuario_con_rol('consulta', 'Consulta'))
        self.assertEqual(self.registrar(consulta, self.m12, self.valores_reactor()).status_code, 403)
        self.assertEqual(consulta.get(f'/api/captura/{self.m12.id}/').status_code, 200)

    def test_muestra_adicional_con_motivo(self):
        incubacion = self.actividad(self.t2)
        url = f'/api/captura/{incubacion.id}/adicional/'
        r = self.web.post(url, {'valores': {self.glucosa.id: '3.1'}, 'motivo': 'corto'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.web.post(url, {'valores': {self.glucosa.id: '3.1'}, 'motivo': 'Revisión de consumo de glucosa', 'codigo_muestra': 'ADIC-1'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        toma = TomaDatos.objects.get(fase=incubacion)
        self.assertTrue(toma.adicional)
        self.assertEqual(toma.codigos_muestra, {'Muestra adicional': 'ADIC-1'})
        self.assertEqual(len(r.data['adicionales']), 1)
        self.assertEqual(self.web.post(f'/api/captura/{self.m12.id}/adicional/', {'valores': {self.glucosa.id: '3'}, 'motivo': 'Desde un muestreo no aplica'},
                                       format='json').status_code, 400)

    def test_tendencia_con_los_datos_anteriores_de_la_etapa(self):
        m0 = self.forzar(self.muestreo(0), 'EN_PROGRESO', self.hito)
        r = self.registrar(self.web, m0, {**self.valores_reactor(), self.glucosa.id: '4.2', self.celulas.id: '0.3', self.viabilidad.id: '98'},
                           momento=(self.hito + timedelta(minutes=30)).isoformat())
        self.assertEqual(r.status_code, 201, r.data)
        detalle = self.web.get(f'/api/captura/{self.m12.id}/').data
        glucosa = detalle['tendencias'][str(self.glucosa.id)]
        self.assertEqual([p['valor'] for p in glucosa], [4.2])
        self.assertAlmostEqual(glucosa[0]['edad_lote_h'], 0.5, delta=0.05)
        self.assertEqual(len(detalle['tendencias'][str(self.temp.id)]), 1)
        self.assertNotIn(str(self.aspecto.id), detalle['tendencias'])  # solo numéricos
        self.assertIn('referencia', detalle['plan']['secciones'][0]['parametros'][0])

    def test_tabla_del_lote_con_edades(self):
        self.registrar(self.web, self.m12, {**self.valores_reactor(), self.glucosa.id: '4'})
        r = self.web.get(f'/api/captura/lote/?lote={self.lote.id}')
        self.assertEqual(r.status_code, 200)
        fila = r.data['filas'][0]
        self.assertEqual(fila['valores']['glucosa']['valor'], '4')
        self.assertEqual(fila['etapa'], 'PO4')
        self.assertIn('glucosa', [p['codigo'] for p in r.data['parametros']])

    def test_resumen_en_la_fase_y_en_la_tablet(self):
        AsignacionFaseOperador.objects.create(fase_lote=self.m12, operador=self.operador, rol_ejercido=self.rol)
        fase = self.web.get(f'/api/fases-lote/{self.m12.id}/').data
        self.assertEqual(fase['captura']['secciones'], ['Reactor', 'Metabolitos'])
        self.assertFalse(fase['captura']['capturada'])
        movil = APIClient()
        movil.post('/api/mobile/login/', {'codigo_empleado': 'OP-1', 'pin_acceso': '1234'}, format='json')
        tareas = movil.get(f'/api/mobile/{self.operador.id}/tareas-pendientes/').data['tareas_pendientes']
        self.assertTrue(tareas[0]['captura']['requerida'])


class EdadCeroTests(CapturaBase):

    def test_estimada_antes_del_hito_y_real_despues(self):
        ceros = edades_cero(self.lote)
        self.assertTrue(ceros[self.etapa.id]['estimada'])
        self.assertEqual(ceros[self.etapa.id]['momento'], self.actividad(self.t1).fin_programado)
        fin_real = timezone.now() - timedelta(hours=3)
        self.forzar(self.actividad(self.t1), 'COMPLETADA', fin_real)
        ceros = edades_cero(self.lote)
        self.assertFalse(ceros[self.etapa.id]['estimada'])
        self.assertEqual(ceros[self.etapa.id]['momento'], fin_real)
        self.assertEqual(ceros['lote']['momento'], fin_real)

    def test_sin_actividad_de_edad_cero_usa_el_primer_inicio(self):
        OperacionProceso.objects.filter(pk=self.t1.pk).update(edad_cero='', edad_cero_lote=False)
        ceros = edades_cero(self.lote)
        self.assertIn('no hay actividad de edad 0', ceros[self.etapa.id]['origen'])
        self.assertEqual(ceros[self.etapa.id]['momento'], self.actividad(self.t1).inicio_programado)
