# procesos/tests.py

from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from actividades.models import MaterialInsumo
from roster.models import Cuadrilla, Operador, RolOperador
from .models import (
    ProcesoMaestro, EtapaProceso, OperacionProceso, LoteProduccion, FaseLote, AsignacionFaseOperador,
    MaterialOperacion, MaterialFase,
)


def usuario_con_rol(nombre, rol):
    usuario = User.objects.create_user(nombre, password='clave-de-prueba')
    usuario.groups.add(Group.objects.get(name=rol))
    return usuario


def local(*args):
    return timezone.make_aware(datetime(*args))


class ProgramacionFasesTests(TestCase):
    """
    Receta de prueba:  T1 (2 h) → T2 (72 h, FS) → T3 (3 h, FS)
                                  T2 → T4 (1 h, SS +4 h)
    """

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(usuario_con_rol('admin-pruebas', 'Administrador'))
        self.proceso = ProcesoMaestro.objects.create(nombre='Proceso de prueba')
        crear = lambda paso, horas, orden, pred=None, dep='FS', desfase=0: OperacionProceso.objects.create(
            proceso=self.proceso, identificador_paso=paso, nombre=f'Operación {paso}', orden=orden,
            duracion_horas=horas, predecesora=pred, tipo_dependencia=dep, desfase_horas=desfase,
        )
        self.t1 = crear('T1', 2, 1)
        self.t2 = crear('T2', 72, 2, self.t1)
        self.t3 = crear('T3', 3, 3, self.t2)
        self.t4 = crear('T4', 1, 4, self.t2, dep='SS', desfase=4)

        rol = RolOperador.objects.create(nombre='Operador base')
        cuadrilla = Cuadrilla.objects.create(identificador='A', nombre='Cuadrilla A')
        self.operador = Operador.objects.create(cuadrilla=cuadrilla, nombre='Ana', codigo_empleado='OP-1', rol=rol)
        self.rol = rol

    def crear_lote(self, codigo='L-1', inicio='2026-11-02T08:00:00'):
        respuesta = self.client.post('/api/lotes/', {
            'identificador_lote': codigo, 'proceso_maestro': self.proceso.id, 'fecha_inicio_planeada': inicio,
        }, format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        return LoteProduccion.objects.get(identificador_lote=codigo)

    def fase(self, lote, operacion):
        return FaseLote.objects.get(lote=lote, operacion_maestra=operacion, es_subtarea_muestreo=False)

    # --- Programación inicial -------------------------------------------------

    def test_fase_de_varios_dias_conserva_su_fecha_de_fin(self):
        lote = self.crear_lote()
        t2 = self.fase(lote, self.t2)
        self.assertEqual(t2.inicio_programado, local(2026, 11, 2, 10, 0))
        self.assertEqual(t2.fin_programado, local(2026, 11, 5, 10, 0))
        self.assertEqual(t2.inicio_base_cpm, t2.inicio_programado)
        self.assertEqual(t2.fin_base_cpm, t2.fin_programado)
        self.assertEqual(self.fase(lote, self.t3).inicio_programado, local(2026, 11, 5, 10, 0))

    # --- Reprogramación -------------------------------------------------------

    def test_reprogramar_no_adelanta_sucesoras_de_fases_largas(self):
        """Regresión: retrasar T1 un día adelantaba T3 dos días (encimándola con la fase de 72 h)."""
        lote = self.crear_lote()
        t1 = self.fase(lote, self.t1)
        respuesta = self.client.post(f'/api/fases-lote/{t1.id}/reprogramar/', {
            'fecha_programada': '2026-11-03', 'hora_inicio_programada': '08:00', 'motivo_reprogramacion': 'OTRO',
        }, format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)

        t2, t3, t4 = self.fase(lote, self.t2), self.fase(lote, self.t3), self.fase(lote, self.t4)
        self.assertEqual(t2.inicio_programado, local(2026, 11, 3, 10, 0))
        self.assertEqual(t2.fin_programado, local(2026, 11, 6, 10, 0))
        self.assertEqual(t3.inicio_programado, t2.fin_programado)
        self.assertEqual(t4.inicio_programado, t2.inicio_programado + timedelta(hours=4))
        self.assertEqual(t3.motivo_reprogramacion, 'PRODUCCION')
        # La línea base no se toca
        self.assertEqual(t3.inicio_base_cpm, local(2026, 11, 5, 10, 0))

    def test_reprogramar_antes_del_fin_de_la_predecesora_se_rechaza(self):
        lote = self.crear_lote()
        t3 = self.fase(lote, self.t3)
        respuesta = self.client.post(f'/api/fases-lote/{t3.id}/reprogramar/', {
            'fecha_programada': '2026-11-04', 'hora_inicio_programada': '10:00', 'motivo_reprogramacion': 'OTRO',
        }, format='json')
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('2026-11-05 10:00', respuesta.data['error'])

    # --- Ejecución ------------------------------------------------------------

    def test_completar_fase_engancha_sucesoras_al_fin_real(self):
        lote = self.crear_lote()
        t1 = self.fase(lote, self.t1)
        AsignacionFaseOperador.objects.create(fase_lote=t1, operador=self.operador, rol_ejercido=self.rol)
        for estado in ('EN_PROGRESO', 'COMPLETADA'):
            respuesta = self.client.post(f'/api/fases-lote/{t1.id}/cambiar-estado/', {'estado': estado}, format='json')
            self.assertEqual(respuesta.status_code, 200, respuesta.data)

        t1.refresh_from_db()
        t2, t3 = self.fase(lote, self.t2), self.fase(lote, self.t3)
        self.assertEqual(t2.inicio_programado, t1.fecha_fin_real)
        self.assertEqual(t2.fin_programado, t1.fecha_fin_real + timedelta(hours=72))
        self.assertEqual(t3.inicio_programado, t2.fin_programado)

    # --- Asignaciones ---------------------------------------------------------

    def test_conflicto_de_operador_entre_lotes_en_dias_distintos(self):
        """El operador asignado a la fase de 72 h no puede tomar otra tarea dentro de esa ventana, aunque sea otro día."""
        lote_a = self.crear_lote('L-A')
        lote_b = self.crear_lote('L-B', inicio='2026-11-03T08:00:00')
        AsignacionFaseOperador.objects.create(fase_lote=self.fase(lote_a, self.t2), operador=self.operador, rol_ejercido=self.rol)

        respuesta = self.client.post('/api/asignaciones-operador/', {
            'fase_lote': self.fase(lote_b, self.t1).id, 'operador': self.operador.id, 'rol_ejercido': self.rol.id,
        }, format='json')
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('Conflicto', respuesta.data['error'])

    def test_no_se_retira_operador_de_fase_iniciada(self):
        lote = self.crear_lote()
        t1 = self.fase(lote, self.t1)
        asignacion = AsignacionFaseOperador.objects.create(fase_lote=t1, operador=self.operador, rol_ejercido=self.rol)
        self.client.post(f'/api/fases-lote/{t1.id}/cambiar-estado/', {'estado': 'EN_PROGRESO'}, format='json')

        respuesta = self.client.delete(f'/api/asignaciones-operador/{asignacion.id}/')
        self.assertEqual(respuesta.status_code, 403)
        self.assertTrue(AsignacionFaseOperador.objects.filter(id=asignacion.id).exists())

    # --- Restricciones de la API ---------------------------------------------

    def test_patch_de_fase_ignora_estado_y_horarios(self):
        lote = self.crear_lote()
        t1 = self.fase(lote, self.t1)
        respuesta = self.client.patch(f'/api/fases-lote/{t1.id}/', {
            'estado': 'COMPLETADA', 'fecha_inicio_real': '2026-01-01T00:00:00',
            'inicio_programado': '2026-01-01T00:00:00',
        }, format='json')
        self.assertEqual(respuesta.status_code, 200)

        t1.refresh_from_db()
        self.assertEqual(t1.estado, 'PENDIENTE')
        self.assertIsNone(t1.fecha_inicio_real)
        self.assertEqual(t1.inicio_programado, local(2026, 11, 2, 8, 0))

    def test_fases_no_se_crean_ni_borran_por_api(self):
        lote = self.crear_lote()
        t1 = self.fase(lote, self.t1)
        self.assertEqual(self.client.delete(f'/api/fases-lote/{t1.id}/').status_code, 405)
        self.assertEqual(self.client.post('/api/fases-lote/', {}, format='json').status_code, 405)

    def test_lote_no_se_edita_y_nace_planeado(self):
        respuesta = self.client.post('/api/lotes/', {
            'identificador_lote': 'L-X', 'proceso_maestro': self.proceso.id,
            'fecha_inicio_planeada': '2026-11-02T08:00:00', 'estado': 'COMPLETADO',
        }, format='json')
        self.assertEqual(respuesta.data['estado'], 'PLANEADO')
        lote_id = respuesta.data['id']
        self.assertEqual(self.client.patch(f'/api/lotes/{lote_id}/', {'estado': 'COMPLETADO'}, format='json').status_code, 405)

    def test_api_expone_campos_derivados_en_hora_local(self):
        lote = self.crear_lote()
        datos = self.client.get(f'/api/fases-lote/{self.fase(lote, self.t2).id}/').data
        self.assertEqual(datos['fecha_programada'], '2026-11-02')
        self.assertEqual(datos['hora_inicio_programada'], '10:00:00')
        self.assertEqual(datos['hora_fin_programada'], '10:00:00')
        self.assertEqual(datos['duracion_estimada'], 72.0)


    def test_api_expone_etapa_id_para_agrupar_en_gantt(self):
        etapa = EtapaProceso.objects.create(proceso=self.proceso, nombre='PO1', orden=1)
        OperacionProceso.objects.filter(pk=self.t2.pk).update(etapa=etapa)
        lote = self.crear_lote()
        con_etapa = self.client.get(f'/api/fases-lote/{self.fase(lote, self.t2).id}/').data
        sin_etapa = self.client.get(f'/api/fases-lote/{self.fase(lote, self.t1).id}/').data
        self.assertEqual((con_etapa['etapa_id'], con_etapa['etapa_nombre']), (etapa.id, 'PO1'))
        self.assertIsNone(sin_etapa['etapa_id'])


class MaterialesTests(TestCase):
    """
    Receta:  T1 (2 h, ACTIVA) → T2 (24 h, INCUBACION, muestreo c/12 h)
    T1 usa 2 L de medio con 12 h de anticipación; cada muestreo de T2 usa 1 kit.
    """

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(usuario_con_rol('admin-pruebas', 'Administrador'))
        self.medio = MaterialInsumo.objects.create(id='MAT-01', nombre='Medio CHO', unidad_medida='L', categoria='MEDIO', condicion_almacenamiento='REFRIGERADO')
        self.kit = MaterialInsumo.objects.create(id='MAT-02', nombre='Kit de muestreo', unidad_medida='kit', categoria='CONSUMIBLE')
        self.proceso = ProcesoMaestro.objects.create(nombre='Receta con materiales')
        self.t1 = OperacionProceso.objects.create(proceso=self.proceso, identificador_paso='T1', nombre='Preparación', orden=1, duracion_horas=2)
        self.t2 = OperacionProceso.objects.create(
            proceso=self.proceso, identificador_paso='T2', nombre='Incubación', orden=2, duracion_horas=24,
            tipo_operacion='INCUBACION', frecuencia_muestreo_horas=12, duracion_muestreo_horas=0.5, predecesora=self.t1,
        )
        MaterialOperacion.objects.create(operacion=self.t1, material=self.medio, cantidad=Decimal('2'), anticipacion_horas=12)
        MaterialOperacion.objects.create(operacion=self.t2, material=self.kit, cantidad=Decimal('1'), aplica_a='MUESTREO')

    def crear_lote(self, codigo='L-M1', inicio='2026-11-02T08:00:00'):
        respuesta = self.client.post('/api/lotes/', {
            'identificador_lote': codigo, 'proceso_maestro': self.proceso.id, 'fecha_inicio_planeada': inicio,
        }, format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        return LoteProduccion.objects.get(identificador_lote=codigo)

    def material_t1(self, lote):
        return MaterialFase.objects.get(fase__lote=lote, fase__operacion_maestra=self.t1, material=self.medio)

    def requerimientos(self, desde, hasta):
        respuesta = self.client.get(f'/api/materiales-fase/requerimientos/?desde={desde}&hasta={hasta}')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        return respuesta.data

    # --- Copia al instanciar el lote ------------------------------------------

    def test_lote_copia_materiales_de_actividad_y_de_cada_muestreo(self):
        lote = self.crear_lote()
        mf = self.material_t1(lote)
        self.assertEqual(mf.cantidad, Decimal('2'))
        self.assertEqual(mf.cantidad_receta, Decimal('2'))
        self.assertEqual(mf.anticipacion_horas, 12)

        kits = MaterialFase.objects.filter(fase__lote=lote, material=self.kit)
        self.assertEqual(kits.count(), 2)
        self.assertTrue(all(k.fase.es_subtarea_muestreo for k in kits))
        self.assertFalse(MaterialFase.objects.filter(fase__lote=lote, fase__operacion_maestra=self.t2, fase__es_subtarea_muestreo=False).exists())

    def test_editar_la_receta_no_altera_lotes_existentes(self):
        lote = self.crear_lote()
        MaterialOperacion.objects.filter(operacion=self.t1).update(cantidad=Decimal('50'))
        self.assertEqual(self.material_t1(lote).cantidad, Decimal('2'))

    def test_cambiar_unidad_en_catalogo_no_altera_lotes_existentes(self):
        lote = self.crear_lote()
        self.client.patch('/api/materiales/MAT-01/', {'unidad_medida': 'mL'}, format='json')
        mf = self.material_t1(lote)
        self.assertEqual(mf.unidad_medida, 'L')
        self.assertEqual(self.client.get(f'/api/materiales-fase/{mf.id}/').data['unidad_medida'], 'L')

        nuevo = self.crear_lote('L-M2')
        self.assertEqual(self.material_t1(nuevo).unidad_medida, 'mL')

    # --- Monitor por día y hora -----------------------------------------------

    def test_requerimiento_se_adelanta_por_la_anticipacion(self):
        self.crear_lote()
        filas = self.requerimientos('2026-11-01', '2026-11-01')
        self.assertEqual([f['material'] for f in filas], ['MAT-01'])
        self.assertEqual(timezone.localtime(datetime.fromisoformat(filas[0]['momento_requerido'])), local(2026, 11, 1, 20, 0))
        self.assertEqual(filas[0]['lote_codigo'], 'L-M1')
        self.assertEqual(filas[0]['paso'], 'T1')

        kits = self.requerimientos('2026-11-02', '2026-11-03')
        self.assertEqual(len(kits), 2)
        self.assertTrue(all(f['material'] == 'MAT-02' for f in kits))

    def test_requerimiento_sigue_a_la_reprogramacion(self):
        lote = self.crear_lote()
        t1 = FaseLote.objects.get(lote=lote, operacion_maestra=self.t1)
        respuesta = self.client.post(f'/api/fases-lote/{t1.id}/reprogramar/', {
            'fecha_programada': '2026-11-04', 'hora_inicio_programada': '08:00', 'motivo_reprogramacion': 'INSUMOS',
        }, format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(self.requerimientos('2026-11-01', '2026-11-01'), [])
        self.assertEqual([f['material'] for f in self.requerimientos('2026-11-03', '2026-11-03')], ['MAT-01'])

    def test_monitor_excluye_retirados_y_lotes_abortados(self):
        lote = self.crear_lote()
        self.client.post(f'/api/materiales-fase/{self.material_t1(lote).id}/retirar/', {'motivo': 'Se usará medio de otro lote'}, format='json')
        self.assertEqual(self.requerimientos('2026-11-01', '2026-11-01'), [])

        otro = self.crear_lote('L-M2')
        self.client.post(f'/api/lotes/{otro.id}/abortar/', {'motivo_aborto': 'Contaminación del inóculo'}, format='json')
        lotes = {f['lote_codigo'] for f in self.requerimientos('2026-11-01', '2026-11-03')}
        self.assertEqual(lotes, {'L-M1'})

    # --- Ajustes por lote (GxP) -----------------------------------------------

    def test_ajuste_por_lote_exige_motivo_y_conserva_cantidad_de_receta(self):
        lote = self.crear_lote()
        mf = self.material_t1(lote)
        url = f'/api/materiales-fase/{mf.id}/ajustar/'
        self.assertEqual(self.client.post(url, {'cantidad': '3.5'}, format='json').status_code, 400)

        respuesta = self.client.post(url, {'cantidad': '3.5', 'motivo': 'Volumen de trabajo mayor'}, format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        mf.refresh_from_db()
        self.assertEqual(mf.cantidad, Decimal('3.5'))
        self.assertEqual(mf.cantidad_receta, Decimal('2'))
        self.assertIsNotNone(mf.ajustado_en)

    def test_no_se_ajusta_material_de_fase_completada(self):
        lote = self.crear_lote()
        mf = self.material_t1(lote)
        FaseLote.objects.filter(id=mf.fase_id).update(estado='COMPLETADA')
        respuesta = self.client.post(f'/api/materiales-fase/{mf.id}/ajustar/', {'cantidad': '5', 'motivo': 'Corrección'}, format='json')
        self.assertEqual(respuesta.status_code, 400)

    def test_agregar_material_extra_y_reactivar_retirado(self):
        lote = self.crear_lote()
        t1 = FaseLote.objects.get(lote=lote, operacion_maestra=self.t1)
        respuesta = self.client.post('/api/materiales-fase/agregar/', {
            'fase': t1.id, 'material': 'MAT-02', 'cantidad': '2', 'motivo': 'Muestra adicional de control',
        }, format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertIsNone(respuesta.data['cantidad_receta'])

        mf = self.material_t1(lote)
        self.client.post(f'/api/materiales-fase/{mf.id}/retirar/', {'motivo': 'No se requiere'}, format='json')
        respuesta = self.client.post('/api/materiales-fase/agregar/', {
            'fase': t1.id, 'material': 'MAT-01', 'cantidad': '1', 'motivo': 'Se vuelve a requerir',
        }, format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertEqual(MaterialFase.objects.filter(fase=t1, material=self.medio).count(), 1)

    # --- Receta y catálogo ----------------------------------------------------

    def test_operacion_guarda_materiales_con_cantidad(self):
        respuesta = self.client.patch(f'/api/operaciones-proceso/{self.t1.id}/', {
            'materiales': [{'material': 'MAT-02', 'cantidad': '4', 'anticipacion_horas': 2}],
        }, format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(list(self.t1.materiales.values_list('material_id', 'cantidad')), [('MAT-02', Decimal('4'))])

    def test_materiales_por_muestreo_solo_en_incubaciones_con_muestreo(self):
        respuesta = self.client.patch(f'/api/operaciones-proceso/{self.t1.id}/', {
            'materiales': [{'material': 'MAT-02', 'cantidad': '1', 'aplica_a': 'MUESTREO'}],
        }, format='json')
        self.assertEqual(respuesta.status_code, 400)

    def test_clonar_receta_copia_materiales(self):
        respuesta = self.client.post(f'/api/procesos-maestros/{self.proceso.id}/clonar/', {'nuevo_nombre': 'Copia'}, format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        copia = MaterialOperacion.objects.filter(operacion__proceso_id=respuesta.data['nuevo_id'])
        self.assertEqual(sorted(copia.values_list('material_id', 'aplica_a')), [('MAT-01', 'ACTIVIDAD'), ('MAT-02', 'MUESTREO')])

    def test_catalogo_busca_y_no_permite_borrar(self):
        datos = self.client.get('/api/materiales/?q=cho').data
        self.assertEqual([m['id'] for m in datos], ['MAT-01'])
        self.assertEqual(datos[0]['usos_en_recetas'], 1)
        self.assertEqual(self.client.delete('/api/materiales/MAT-01/').status_code, 405)
        respuesta = self.client.patch('/api/materiales/MAT-01/', {'id': 'MAT-99'}, format='json')
        self.assertEqual(respuesta.status_code, 400)

