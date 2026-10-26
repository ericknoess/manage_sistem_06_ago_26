# procesos/tests.py

from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from actividades.models import MaterialInsumo
from roster.models import Cuadrilla, Operador, RolOperador
from usuarios.tests import programar_ahora
from .models import (
    ProcesoMaestro, EtapaProceso, OperacionProceso, LoteProduccion, FaseLote, AsignacionFaseOperador,
    MaterialOperacion, MaterialFase, EquipoOperacion, EquipoFase, ReservaEquipo,
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
        t1 = programar_ahora(self.fase(lote, self.t1))
        AsignacionFaseOperador.objects.create(fase_lote=t1, operador=self.operador, rol_ejercido=self.rol)
        for estado in ('EN_PROGRESO', 'COMPLETADA'):
            respuesta = self.client.post(f'/api/fases-lote/{t1.id}/cambiar-estado/', {'estado': estado, 'firma_password': 'clave-de-prueba'}, format='json')
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
        t1 = programar_ahora(self.fase(lote, self.t1))
        asignacion = AsignacionFaseOperador.objects.create(fase_lote=t1, operador=self.operador, rol_ejercido=self.rol)
        self.client.post(f'/api/fases-lote/{t1.id}/cambiar-estado/', {'estado': 'EN_PROGRESO', 'firma_password': 'clave-de-prueba'}, format='json')

        respuesta = self.client.delete(f'/api/asignaciones-operador/{asignacion.id}/')
        self.assertEqual(respuesta.status_code, 403)
        self.assertTrue(AsignacionFaseOperador.objects.filter(id=asignacion.id).exists())

    # --- Restricciones de la API ---------------------------------------------

    def test_fase_no_se_edita_por_patch(self):
        """Estado y horarios solo cambian por cambiar-estado/reprogramar; los equipos, por /api/equipos-fase/."""
        lote = self.crear_lote()
        t1 = self.fase(lote, self.t1)
        respuesta = self.client.patch(f'/api/fases-lote/{t1.id}/', {
            'estado': 'COMPLETADA', 'fecha_inicio_real': '2026-01-01T00:00:00',
            'inicio_programado': '2026-01-01T00:00:00',
        }, format='json')
        self.assertEqual(respuesta.status_code, 405)

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
        self.client.post(f'/api/lotes/{otro.id}/abortar/', {'motivo_aborto': 'Contaminación del inóculo', 'firma_password': 'clave-de-prueba'}, format='json')
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



class InicioEnPlantaTests(TestCase):
    """
    Ventana de tolerancia, dependencias al iniciar, reprogramación desde el inicio real y alertas.
    Receta: T1 (2 h) → T2 incubación (72 h, FS, muestreo cada 24 h) → T3 (3 h, FS); T2 → T4 (1 h, SS +4 h)
    """

    def setUp(self):
        from roster.models import TipoTurno
        self.web = APIClient()
        self.web.force_authenticate(usuario_con_rol('supervisora', 'Jefatura'))
        self.proceso = ProcesoMaestro.objects.create(nombre='Proceso con ventana')
        crear = lambda paso, horas, orden, pred=None, dep='FS', desfase=0, **extra: OperacionProceso.objects.create(
            proceso=self.proceso, identificador_paso=paso, nombre=f'Operación {paso}', orden=orden, duracion_horas=horas,
            predecesora=pred, tipo_dependencia=dep, desfase_horas=desfase, tolerancia_antes_horas=2, tolerancia_despues_horas=1, **extra,
        )
        self.t1 = crear('T1', 2, 1)
        self.t2 = crear('T2', 72, 2, self.t1, tipo_operacion='INCUBACION', frecuencia_muestreo_horas=24, duracion_muestreo_horas=0.5)
        self.t3 = crear('T3', 3, 3, self.t2)
        self.t4 = crear('T4', 1, 4, self.t2, dep='SS', desfase=4)
        self.rol = RolOperador.objects.create(nombre='Operador base')
        self.cuadrilla = Cuadrilla.objects.create(identificador='A', nombre='Cuadrilla A')
        self.operador = Operador.objects.create(cuadrilla=self.cuadrilla, nombre='Ana', codigo_empleado='OP-1', rol=self.rol, pin_acceso='1234')
        self.turno_completo = TipoTurno.objects.create(codigo='D', nombre='Día completo', hora_inicio=None, hora_fin=None)

        inicio = timezone.localtime(timezone.now()).replace(second=0, microsecond=0, tzinfo=None)
        respuesta = self.web.post('/api/lotes/', {'identificador_lote': 'L-V', 'proceso_maestro': self.proceso.id,
                                                  'fecha_inicio_planeada': inicio.isoformat()}, format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.lote = LoteProduccion.objects.get(identificador_lote='L-V')
        AsignacionFaseOperador.objects.create(fase_lote=self.fase(self.t1), operador=self.operador, rol_ejercido=self.rol)

    def fase(self, operacion, muestreo=0):
        return FaseLote.objects.get(lote=self.lote, operacion_maestra=operacion, indice_muestreo=muestreo)

    def mover(self, fase, horas):
        """Programa la fase a `horas` de ahora (negativo = ya debió iniciar)."""
        fase.inicio_programado = timezone.now() + timedelta(hours=horas)
        fase.fin_programado = fase.inicio_programado + fase.duracion_planeada
        fase.save()
        return fase

    def estado_web(self, fase, estado, **extra):
        return self.web.post(f'/api/fases-lote/{fase.id}/cambiar-estado/',
                             {'estado': estado, 'firma_password': 'clave-de-prueba', **extra}, format='json')

    def terminal(self):
        movil = APIClient()
        movil.post('/api/mobile/login/', {'codigo_empleado': 'OP-1', 'pin_acceso': '1234'}, format='json')
        return movil

    # --- Ventana de tolerancia --------------------------------------------------

    def test_dentro_de_la_tolerancia_inicia_sin_motivo(self):
        t1 = self.mover(self.fase(self.t1), 1.5)  # tolerancia de adelanto: 2 h
        movil = self.terminal()
        respuesta = movil.post(f'/api/fases-lote/{t1.id}/cambiar-estado/', {'estado': 'EN_PROGRESO', 'firma_pin': '1234'}, format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)

    def test_terminal_no_adelanta_fuera_de_tolerancia(self):
        t1 = self.mover(self.fase(self.t1), 5)
        movil = self.terminal()
        respuesta = movil.post(f'/api/fases-lote/{t1.id}/cambiar-estado/', {'estado': 'EN_PROGRESO', 'firma_pin': '1234',
                                                                             'motivo_desviacion': 'Quiero adelantarla'}, format='json')
        self.assertEqual((respuesta.status_code, respuesta.data['codigo']), (403, 'FUERA_DE_VENTANA'))
        tareas = movil.get(f'/api/mobile/{self.operador.id}/tareas-pendientes/').data['tareas_pendientes']
        self.assertEqual(tareas[0]['desviacion'], 'ADELANTO')
        self.assertIsNotNone(tareas[0]['disponible_desde'])

    def test_web_adelanta_con_motivo_y_queda_en_bitacora(self):
        from auditoria.models import RegistroAuditoria
        t1 = self.mover(self.fase(self.t1), 5)
        self.assertEqual(self.estado_web(t1, 'EN_PROGRESO').data['codigo'], 'MOTIVO_REQUERIDO')
        respuesta = self.estado_web(t1, 'EN_PROGRESO', motivo_desviacion='Equipo liberado antes de lo previsto')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        registro = RegistroAuditoria.objects.get(accion='FASE_EN_PROGRESO')
        self.assertIn('Equipo liberado', registro.motivo)
        self.assertIn('adelantado', registro.cambios['desviacion_inicio'][1])

    def test_retraso_fuera_de_tolerancia_pide_motivo_tambien_en_terminal(self):
        t1 = self.mover(self.fase(self.t1), -3)  # tolerancia de retraso: 1 h
        movil = self.terminal()
        url = f'/api/fases-lote/{t1.id}/cambiar-estado/'
        self.assertEqual(movil.post(url, {'estado': 'EN_PROGRESO', 'firma_pin': '1234'}, format='json').data['codigo'], 'MOTIVO_REQUERIDO')
        respuesta = movil.post(url, {'estado': 'EN_PROGRESO', 'firma_pin': '1234', 'motivo_desviacion': 'Llegó tarde el insumo'}, format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)

    def test_tolerancia_se_configura_en_la_receta(self):
        disenador = APIClient()
        disenador.force_authenticate(usuario_con_rol('ingeniera', 'Ingeniería de procesos'))
        url = f'/api/operaciones-proceso/{self.t1.id}/'
        self.assertEqual(disenador.patch(url, {'tolerancia_antes_horas': 8, 'tolerancia_despues_horas': 0.5}, format='json').status_code, 200)
        self.assertEqual(disenador.patch(url, {'tolerancia_antes_horas': -1}, format='json').status_code, 400)
        t1 = self.mover(self.fase(self.t1), 5)  # ahora 5 h de adelanto está dentro de las 8 h
        self.assertEqual(self.estado_web(t1, 'EN_PROGRESO').status_code, 200)

    # --- Dependencias -----------------------------------------------------------

    def test_no_inicia_si_la_predecesora_no_termino(self):
        self.mover(self.fase(self.t1), 0)
        t2 = self.mover(self.fase(self.t2), 0)
        self.assertEqual(self.estado_web(t2, 'EN_PROGRESO').data['codigo'], 'DEPENDENCIA_PENDIENTE')
        self.assertEqual(self.estado_web(self.fase(self.t1), 'EN_PROGRESO').status_code, 200)
        self.assertEqual(self.estado_web(self.fase(self.t2), 'EN_PROGRESO').data['codigo'], 'DEPENDENCIA_PENDIENTE')  # FS: debe completarse

    def test_muestreo_espera_a_que_inicie_la_incubacion(self):
        muestreo = self.mover(self.fase(self.t2, muestreo=1), 0)
        self.assertEqual(self.estado_web(muestreo, 'EN_PROGRESO').data['codigo'], 'DEPENDENCIA_PENDIENTE')

    # --- Reprogramación desde el inicio real --------------------------------------

    def test_iniciar_antes_recalcula_sucesoras_y_muestreos(self):
        t1 = self.mover(self.fase(self.t1), 1)
        self.assertEqual(self.estado_web(t1, 'EN_PROGRESO').status_code, 200)
        t1.refresh_from_db()
        # FS: T2 se engancha al inicio real de T1 más su duración planeada (2 h)
        self.assertEqual(self.fase(self.t2).inicio_programado, t1.fecha_inicio_real + timedelta(hours=2))

        t2 = self.mover(self.fase(self.t2), 1.5)
        self.assertEqual(self.estado_web(self.fase(self.t1), 'COMPLETADA').status_code, 200)
        t2 = self.mover(self.fase(self.t2), 1.5)
        r = self.estado_web(t2, "EN_PROGRESO"); self.assertEqual(r.status_code, 200, r.data)
        t2.refresh_from_db()
        self.assertEqual(self.fase(self.t2, muestreo=1).inicio_programado, t2.fecha_inicio_real + timedelta(hours=24))
        self.assertEqual(self.fase(self.t4).inicio_programado, t2.fecha_inicio_real + timedelta(hours=4))  # SS +4 h

    def test_completar_un_muestreo_no_mueve_las_sucesoras_de_la_incubacion(self):
        self.mover(self.fase(self.t1), 0)
        self.estado_web(self.fase(self.t1), 'EN_PROGRESO')
        self.estado_web(self.fase(self.t1), 'COMPLETADA')
        self.mover(self.fase(self.t2), 0)
        self.estado_web(self.fase(self.t2), 'EN_PROGRESO')
        t3_antes = self.fase(self.t3).inicio_programado
        muestreo = self.mover(self.fase(self.t2, muestreo=1), 0)
        AsignacionFaseOperador.objects.create(fase_lote=muestreo, operador=self.operador, rol_ejercido=self.rol)
        r = self.estado_web(muestreo, "EN_PROGRESO"); self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.estado_web(self.fase(self.t2, muestreo=1), 'COMPLETADA').status_code, 200)
        self.assertEqual(self.fase(self.t3).inicio_programado, t3_antes)

    # --- Alertas para Planificación -----------------------------------------------

    def test_alertas_de_cruce_turno_y_material(self):
        from roster.models import TurnoDia
        t3 = self.fase(self.t3)
        t4 = self.fase(self.t4)
        for fase in (t3, t4):
            AsignacionFaseOperador.objects.create(fase_lote=fase, operador=self.operador, rol_ejercido=self.rol)
        # T4 traslapa a T3; Ana no tiene turno ningún día
        t4.inicio_programado, t4.fin_programado = t3.inicio_programado, t3.fin_programado
        t4.save()
        alertas = self.web.get('/api/fases-lote/alertas/').data
        self.assertTrue(any('también está asignado' in m for m in alertas[t3.id]))
        self.assertTrue(any('no tiene turno' in m for m in alertas[t3.id]))

        hoy = timezone.localdate()
        for dias in range(-1, 6):
            TurnoDia.objects.create(operador=self.operador, fecha=hoy + timedelta(days=dias), tipo_turno=self.turno_completo)
        alertas = self.web.get('/api/fases-lote/alertas/').data
        self.assertFalse(any('no tiene turno' in m for m in alertas[t3.id]))

        # Material: la actividad se adelantó y su anticipación ya empezó
        material = MaterialInsumo.objects.create(id='MAT-V', nombre='Medio V', unidad_medida='L')
        t1 = self.mover(self.fase(self.t1), 1)
        MaterialFase.objects.create(fase=t1, material=material, cantidad=1, unidad_medida='L', anticipacion_horas=3)
        t1.inicio_base_cpm = t1.inicio_programado + timedelta(hours=10)
        t1.save()
        alertas = self.web.get('/api/fases-lote/alertas/').data
        self.assertTrue(any('Medio V' in m for m in alertas[t1.id]))


class EquiposTests(TestCase):
    """
    Receta: T1 (2 h, 1 Biorreactor con 2 h de preparación y 1 h de limpieza) → T2 (3 h, FS, sin equipo).
    """

    def setUp(self):
        from actividades.models import Equipo, TipoEquipo
        self.jefa = APIClient()
        self.jefa.force_authenticate(usuario_con_rol('jefa', 'Jefatura'))
        self.biorreactor = TipoEquipo.objects.get_or_create(codigo='BIORREACTOR', defaults={'nombre': 'Biorreactor'})[0]
        self.autoclave = TipoEquipo.objects.get_or_create(codigo='AUTOCLAVE', defaults={'nombre': 'Autoclave'})[0]
        self.br1 = Equipo.objects.create(id='BR-01', nombre='Biorreactor 500 L', tipo=self.biorreactor)
        self.br2 = Equipo.objects.create(id='BR-02', nombre='Biorreactor 200 L', tipo=self.biorreactor)
        self.ac1 = Equipo.objects.create(id='AC-01', nombre='Autoclave', tipo=self.autoclave)

        self.proceso = ProcesoMaestro.objects.create(nombre='Proceso con equipos')
        self.t1 = OperacionProceso.objects.create(proceso=self.proceso, identificador_paso='T1', nombre='Siembra', orden=1, duracion_horas=2)
        self.t2 = OperacionProceso.objects.create(proceso=self.proceso, identificador_paso='T2', nombre='Cosecha', orden=2,
                                                  duracion_horas=3, predecesora=self.t1)
        EquipoOperacion.objects.create(operacion=self.t1, tipo=self.biorreactor, cantidad=1, horas_preparacion=2, horas_limpieza=1)
        self.rol = RolOperador.objects.create(nombre='Operador base')
        cuadrilla = Cuadrilla.objects.create(identificador='A', nombre='Cuadrilla A')
        self.operador = Operador.objects.create(cuadrilla=cuadrilla, nombre='Ana', codigo_empleado='OP-1', rol=self.rol)

    def crear_lote(self, codigo='L-1', inicio=None):
        inicio = inicio or timezone.localtime(timezone.now()).replace(second=0, microsecond=0, tzinfo=None)
        respuesta = self.jefa.post('/api/lotes/', {'identificador_lote': codigo, 'proceso_maestro': self.proceso.id,
                                                   'fecha_inicio_planeada': inicio.isoformat()}, format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        lote = LoteProduccion.objects.get(identificador_lote=codigo)
        AsignacionFaseOperador.objects.create(fase_lote=self.fase(lote, self.t1), operador=self.operador, rol_ejercido=self.rol)
        return lote

    def fase(self, lote, operacion):
        return FaseLote.objects.get(lote=lote, operacion_maestra=operacion, es_subtarea_muestreo=False)

    def requerimiento(self, lote):
        return EquipoFase.objects.get(fase=self.fase(lote, self.t1))

    def reservar(self, ef, equipo, cliente=None):
        return (cliente or self.jefa).post(f'/api/equipos-fase/{ef.id}/reservar/', {'equipo': equipo.id}, format='json')

    def iniciar(self, fase):
        return self.jefa.post(f'/api/fases-lote/{fase.id}/cambiar-estado/',
                              {'estado': 'EN_PROGRESO', 'firma_password': 'clave-de-prueba'}, format='json')

    # --- Receta y lote --------------------------------------------------------------

    def test_el_lote_copia_los_equipos_de_la_receta(self):
        ef = self.requerimiento(self.crear_lote())
        self.assertEqual((ef.tipo, ef.cantidad, ef.cantidad_receta, ef.horas_preparacion, ef.horas_limpieza),
                         (self.biorreactor, 1, 1, 2, 1))
        inicio, fin = ef.ventana_ocupacion()
        self.assertEqual(inicio, ef.fase.inicio_programado - timedelta(hours=2))
        self.assertEqual(fin, ef.fase.fin_programado + timedelta(hours=1))

    def test_la_receta_guarda_equipos_por_tipo(self):
        ingeniera = APIClient()
        ingeniera.force_authenticate(usuario_con_rol('ingeniera', 'Ingeniería de procesos'))
        respuesta = ingeniera.patch(f'/api/operaciones-proceso/{self.t2.id}/', {'equipos': [
            {'tipo': 'AUTOCLAVE', 'cantidad': 2, 'horas_preparacion': 0.5, 'horas_limpieza': 1, 'aplica_a': 'ACTIVIDAD'},
        ]}, format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(respuesta.data['equipos'][0]['tipo_nombre'], 'Autoclave')
        repetido = ingeniera.patch(f'/api/operaciones-proceso/{self.t2.id}/', {'equipos': [
            {'tipo': 'AUTOCLAVE', 'cantidad': 1}, {'tipo': 'AUTOCLAVE', 'cantidad': 1}]}, format='json')
        self.assertEqual(repetido.status_code, 400)

    # --- Reservas ---------------------------------------------------------------------

    def test_reserva_valida_tipo_cantidad_y_estado(self):
        ef = self.requerimiento(self.crear_lote())
        self.assertIn('la fase pide Biorreactor', self.reservar(ef, self.ac1).data['error'])
        self.br1.estado = 'MANTENIMIENTO'
        self.br1.save()
        self.assertIn('mantenimiento', self.reservar(ef, self.br1).data['error'])
        self.br2.calificacion_vence = timezone.localdate() - timedelta(days=1)
        self.br2.save()
        self.assertIn('calificación', self.reservar(ef, self.br2).data['error'])
        self.br2.calificacion_vence = None
        self.br2.save()
        self.assertEqual(self.reservar(ef, self.br2).status_code, 201)
        self.br1.estado = 'DISPONIBLE'
        self.br1.save()
        self.assertIn('ya tiene', self.reservar(ef, self.br1).data['error'])  # pide 1

    def test_no_se_reserva_un_equipo_ocupado_incluida_preparacion_y_limpieza(self):
        inicio = timezone.localtime(timezone.now()).replace(second=0, microsecond=0, tzinfo=None)
        ef_a = self.requerimiento(self.crear_lote('L-A', inicio))
        # L-B empieza 4 h después: su preparación (2 h) toca la limpieza de L-A (fin + 1 h = inicio + 3 h)
        ef_b = self.requerimiento(self.crear_lote('L-B', inicio + timedelta(hours=4)))
        self.assertEqual(self.reservar(ef_a, self.br1).status_code, 201)
        respuesta = self.reservar(ef_b, self.br1)
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('está reservado para', respuesta.data['error'])
        candidatos = self.jefa.get(f'/api/equipos-fase/{ef_b.id}/candidatos/').data
        self.assertEqual({c['id']: c['disponible'] for c in candidatos}, {'BR-01': False, 'BR-02': True})

    def test_ajustes_exigen_motivo_y_no_bajan_de_lo_reservado(self):
        ef = self.requerimiento(self.crear_lote())
        url = f'/api/equipos-fase/{ef.id}/'
        self.assertEqual(self.jefa.post(url + 'ajustar/', {'cantidad': 2}, format='json').status_code, 400)
        self.assertEqual(self.jefa.post(url + 'ajustar/', {'cantidad': 2, 'motivo': 'Escalamiento del lote'}, format='json').status_code, 200)
        self.reservar(ef, self.br1)
        self.reservar(ef, self.br2)
        self.assertIn('libera', self.jefa.post(url + 'ajustar/', {'cantidad': 1, 'motivo': 'Regresa a uno'}, format='json').data['error'])
        respuesta = self.jefa.post(url + 'retirar/', {'motivo': 'No se usará biorreactor'}, format='json')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data['reservados'], 0)
        self.assertFalse(respuesta.data['activo'])

    def test_consulta_no_reserva(self):
        consulta = APIClient()
        consulta.force_authenticate(usuario_con_rol('consulta', 'Consulta'))
        ef = self.requerimiento(self.crear_lote())
        self.assertEqual(self.reservar(ef, self.br1, consulta).status_code, 403)

    # --- Ejecución ----------------------------------------------------------------------

    def test_no_inicia_sin_el_equipo_reservado(self):
        lote = self.crear_lote()
        t1 = self.fase(lote, self.t1)
        respuesta = self.iniciar(t1)
        self.assertEqual(respuesta.data['codigo'], 'EQUIPO_PENDIENTE')
        self.reservar(self.requerimiento(lote), self.br1)
        self.br1.estado = 'FUERA_SERVICIO'
        self.br1.save()
        self.assertIn('fuera de servicio', self.iniciar(t1).data['error'])
        self.br1.estado = 'DISPONIBLE'
        self.br1.save()
        self.assertEqual(self.iniciar(t1).status_code, 200)

    def test_cambiar_equipo_en_ejecucion_con_motivo_y_firma(self):
        from auditoria.models import RegistroAuditoria
        lote = self.crear_lote()
        ef = self.requerimiento(lote)
        reserva_id = self.reservar(ef, self.br1).data['reservas'][0]['id']
        url = f'/api/equipos-fase/{ef.id}/cambiar/'
        # Antes de iniciar no aplica: se libera y se reserva otro
        self.assertIn('ejecución', self.jefa.post(url, {'reserva': reserva_id, 'equipo': 'BR-02', 'motivo': 'Falla',
                                                        'firma_password': 'clave-de-prueba'}, format='json').data['error'])
        self.iniciar(self.fase(lote, self.t1))
        self.assertEqual(self.jefa.post(url, {'reserva': reserva_id, 'equipo': 'BR-02', 'firma_password': 'clave-de-prueba'},
                                        format='json').status_code, 400)  # sin motivo
        self.assertEqual(self.jefa.post(url, {'reserva': reserva_id, 'equipo': 'BR-02', 'motivo': 'Falla del agitador'},
                                        format='json').data['codigo'], 'FIRMA_REQUERIDA')
        respuesta = self.jefa.post(url, {'reserva': reserva_id, 'equipo': 'BR-02', 'motivo': 'Falla del agitador',
                                         'firma_password': 'clave-de-prueba'}, format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        anterior, nueva = ReservaEquipo.objects.filter(equipo_fase=ef).order_by('id')
        self.assertIsNotNone(anterior.hasta)
        self.assertEqual((nueva.equipo_id, nueva.desde), ('BR-02', anterior.hasta))
        self.assertEqual(respuesta.data['reservados'], 1)
        registro = RegistroAuditoria.objects.get(categoria='EQUIPO_LOTE', accion='CAMBIAR')
        self.assertEqual(registro.firma.significado, 'Autorizo el cambio de equipo durante la ejecución')
        self.assertEqual(registro.motivo, 'Falla del agitador')

    # --- Alertas y monitor ------------------------------------------------------------------

    def test_reprogramar_que_cruza_reservas_genera_alerta(self):
        inicio = timezone.localtime(timezone.now()).replace(second=0, microsecond=0, tzinfo=None) + timedelta(days=1)
        lote_a, lote_b = self.crear_lote('L-A', inicio), self.crear_lote('L-B', inicio + timedelta(days=1))
        self.reservar(self.requerimiento(lote_a), self.br1)
        self.reservar(self.requerimiento(lote_b), self.br1)
        t1_b = self.fase(lote_b, self.t1)
        planeador = APIClient()
        planeador.force_authenticate(usuario_con_rol('planeador', 'Planeador'))
        respuesta = planeador.post(f'/api/fases-lote/{t1_b.id}/reprogramar/', {
            'fecha_programada': inicio.date().isoformat(), 'hora_inicio_programada': inicio.strftime('%H:%M'),
            'motivo_reprogramacion': 'OTRO'}, format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        alertas = self.jefa.get('/api/fases-lote/alertas/').data
        self.assertTrue(any('BR-01' in m and 'se cruza' in m for m in alertas[t1_b.id]))

    def test_monitor_muestra_tramos_y_pendientes(self):
        lote_a = self.crear_lote('L-A')
        self.crear_lote('L-B')
        self.reservar(self.requerimiento(lote_a), self.br1)
        hoy = timezone.localdate()
        datos = self.jefa.get(f'/api/equipos-fase/ocupacion/?desde={hoy}&hasta={hoy + timedelta(days=1)}').data
        self.assertEqual([(t['equipo'], t['lote_codigo']) for t in datos['tramos']], [('BR-01', 'L-A')])
        self.assertEqual([(p['tipo'], p['lote_codigo'], p['faltan']) for p in datos['pendientes']], [('BIORREACTOR', 'L-B', 1)])

    def test_clonar_receta_copia_equipos(self):
        ingeniera = APIClient()
        ingeniera.force_authenticate(usuario_con_rol('ingeniera', 'Ingeniería de procesos'))
        respuesta = ingeniera.post(f'/api/procesos-maestros/{self.proceso.id}/clonar/', {'nuevo_nombre': 'Copia'}, format='json')
        self.assertIn(respuesta.status_code, (200, 201), respuesta.data)
        self.assertTrue(EquipoOperacion.objects.filter(operacion__proceso_id=respuesta.data['nuevo_id'], tipo=self.biorreactor).exists())


class EstaticosVersionadosTests(TestCase):
    """Cada {% static %} lleva ?v=<hash del contenido> para que el navegador no use copias viejas."""

    def test_la_url_cambia_solo_si_cambia_el_archivo(self):
        import os, tempfile
        from core.estaticos import version_de
        from django.templatetags.static import static
        self.assertRegex(static('core/js/utils.js'), r'^/static/core/js/utils\.js\?v=[0-9a-f]{8}$')
        self.assertEqual(static('no/existe.js'), '/static/no/existe.js')
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as archivo:
            archivo.write('uno')
        try:
            antes = version_de(archivo.name)
            self.assertEqual(version_de(archivo.name), antes)
            with open(archivo.name, 'w') as f:
                f.write('dos')
            os.utime(archivo.name, (0, os.path.getmtime(archivo.name) + 5))
            self.assertNotEqual(version_de(archivo.name), antes)
        finally:
            os.remove(archivo.name)


class SurtidoMaterialesTests(TestCase):
    """
    Entrega y recepción de materiales con doble firma, regla de cuatro ojos, caducidad y devoluciones.
    Receta: T1 (2 h) usa 2 L de medio con 12 h de anticipación. Ana (OP-1) está asignada a T1.
    """

    def setUp(self):
        from usuarios.models import Perfil
        self.medio = MaterialInsumo.objects.create(id='MAT-01', nombre='Medio CHO', unidad_medida='L', categoria='MEDIO')
        self.proceso = ProcesoMaestro.objects.create(nombre='Receta con surtido')
        self.t1 = OperacionProceso.objects.create(proceso=self.proceso, identificador_paso='T1', nombre='Preparación', orden=1,
                                                  duracion_horas=2, tolerancia_antes_horas=2, tolerancia_despues_horas=2)
        MaterialOperacion.objects.create(operacion=self.t1, material=self.medio, cantidad=Decimal('2'), anticipacion_horas=12)

        self.rol = RolOperador.objects.create(nombre='Operador base')
        cuadrilla = Cuadrilla.objects.create(identificador='A', nombre='Cuadrilla A')
        self.ana = Operador.objects.create(cuadrilla=cuadrilla, nombre='Ana', codigo_empleado='OP-1', rol=self.rol, pin_acceso='1234')
        self.beto = Operador.objects.create(cuadrilla=cuadrilla, nombre='Beto', codigo_empleado='OP-2', rol=self.rol, pin_acceso='2222')
        # Planeadora que también surte desde la tablet: su registro del roster está ligado a su usuario web
        self.pla_operador = Operador.objects.create(cuadrilla=cuadrilla, nombre='Paola', codigo_empleado='PL-1', pin_acceso='5678')
        planeadora = usuario_con_rol('planeadora', 'Planeador')
        Perfil.objects.create(usuario=planeadora, operador=self.pla_operador)

        self.almacen = APIClient()
        self.almacen.force_authenticate(usuario_con_rol('almacenista', 'Almacén'))
        self.jefa = APIClient()
        self.jefa.force_authenticate(usuario_con_rol('jefa', 'Jefatura'))

        inicio = timezone.localtime(timezone.now()).replace(second=0, microsecond=0, tzinfo=None)
        respuesta = self.jefa.post('/api/lotes/', {'identificador_lote': 'L-S', 'proceso_maestro': self.proceso.id,
                                                   'fecha_inicio_planeada': inicio.isoformat()}, format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.lote = LoteProduccion.objects.get(identificador_lote='L-S')
        self.fase = FaseLote.objects.get(lote=self.lote, operacion_maestra=self.t1)
        AsignacionFaseOperador.objects.create(fase_lote=self.fase, operador=self.ana, rol_ejercido=self.rol)
        self.mf = MaterialFase.objects.get(fase=self.fase)
        self.vence = (timezone.localdate() + timedelta(days=30)).isoformat()

    def terminal(self, codigo, pin):
        movil = APIClient()
        respuesta = movil.post('/api/mobile/login/', {'codigo_empleado': codigo, 'pin_acceso': pin}, format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        return movil, respuesta.data

    def entregar(self, cliente=None, cantidad='2', firma=None, **extra):
        cliente = cliente or self.almacen
        datos = {'material_fase': self.mf.id, 'cantidad': cantidad, 'lote_material': 'MC-2026-118', 'caducidad': self.vence, **extra}
        datos.update(firma or {'firma_password': 'clave-de-prueba'})
        return cliente.post('/api/surtido/entregar/', datos, format='json')

    def surtido(self):
        return self.jefa.get(f'/api/materiales-fase/{self.mf.id}/').data['surtido']

    # --- Entrega y recepción ------------------------------------------------------

    def test_almacen_entrega_y_el_operador_recibe_con_su_pin(self):
        from auditoria.models import RegistroAuditoria
        respuesta = self.entregar()
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertEqual(respuesta.data['estado'], 'EN_TRANSITO')
        self.assertEqual(self.surtido()['estado'], 'EN_TRANSITO')

        ana, _ = self.terminal('OP-1', '1234')
        tarea = ana.get(f'/api/mobile/{self.ana.id}/tareas-pendientes/').data['tareas_pendientes'][0]
        self.assertEqual(tarea['materiales'][0]['entregas'][0]['estado'], 'EN_TRANSITO')

        recibida = ana.post(f"/api/surtido/{respuesta.data['id']}/recibir/", {'firma_pin': '1234'}, format='json')
        self.assertEqual(recibida.status_code, 200, recibida.data)
        self.assertEqual(recibida.data['recibido_por_nombre'], 'Ana (OP-1)')
        self.assertEqual(self.surtido()['estado'], 'COMPLETO')

        registros = RegistroAuditoria.objects.filter(categoria='MATERIAL_LOTE', accion__in=['ENTREGAR', 'RECIBIR'])
        self.assertEqual(registros.count(), 2)
        self.assertEqual([r.firma.significado for r in registros.order_by('id')],
                         ['Entrego el material indicado', 'Recibo el material conforme'])

    def test_avisa_si_la_fase_no_tiene_quien_reciba(self):
        AsignacionFaseOperador.objects.filter(fase_lote=self.fase).delete()
        respuesta = self.entregar()
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertIn('no tiene personal asignado', respuesta.data['avisos'][0])

    def test_firma_incorrecta_no_registra_la_entrega(self):
        respuesta = self.entregar(firma={'firma_password': 'equivocada'})
        self.assertEqual(respuesta.data['codigo'], 'FIRMA_INVALIDA')
        self.assertFalse(self.mf.entregas.exists())

    def test_no_se_entrega_material_caducado_o_que_vence_antes_de_usarse(self):
        ayer = (timezone.localdate() - timedelta(days=1)).isoformat()
        self.assertIn('caducó', self.entregar(caducidad=ayer).data['error'])
        self.fase.inicio_programado = timezone.now() + timedelta(days=10)
        self.fase.fin_programado = self.fase.inicio_programado + timedelta(hours=2)
        self.fase.save()
        pronto = (timezone.localdate() + timedelta(days=2)).isoformat()
        self.assertIn('antes de su uso', self.entregar(caducidad=pronto).data['error'])
        self.assertFalse(self.mf.entregas.exists())

    def test_quien_entrega_no_puede_recibir(self):
        entrega = self.entregar(self.jefa).data  # Jefatura puede surtir y ejecutar fases
        respuesta = self.jefa.post(f"/api/surtido/{entrega['id']}/recibir/", {'firma_password': 'clave-de-prueba'}, format='json')
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('cuatro ojos', respuesta.data['error'])

    def dar_turno(self, operador):
        from roster.models import TipoTurno, TurnoDia
        tipo, _ = TipoTurno.objects.get_or_create(codigo='D', defaults={'nombre': 'Día completo', 'hora_inicio': None, 'hora_fin': None})
        TurnoDia.objects.create(operador=operador, fecha=timezone.localdate(), tipo_turno=tipo)

    def test_sin_turno_ni_asignacion_no_recibe(self):
        entrega = self.entregar().data
        beto, _ = self.terminal('OP-2', '2222')
        respuesta = beto.post(f"/api/surtido/{entrega['id']}/recibir/", {'firma_pin': '2222'}, format='json')
        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(beto.get('/api/surtido/por-recibir/').data, {'puede_recibir': False, 'entregas': []})
        # El almacén tampoco recibe como si fuera personal de planta
        self.assertEqual(self.almacen.post(f"/api/surtido/{entrega['id']}/recibir/", {'firma_password': 'clave-de-prueba'},
                                           format='json').status_code, 403)

    def test_operador_en_turno_recibe_aunque_no_ejecute_la_actividad(self):
        entrega = self.entregar().data
        self.dar_turno(self.beto)
        beto, _ = self.terminal('OP-2', '2222')
        pendientes = beto.get('/api/surtido/por-recibir/').data
        self.assertTrue(pendientes['puede_recibir'])
        self.assertEqual([e['id'] for e in pendientes['entregas']], [entrega['id']])
        respuesta = beto.post(f"/api/surtido/{entrega['id']}/recibir/", {'firma_pin': '2222'}, format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(respuesta.data['recibido_por_nombre'], 'Beto (OP-2)')

    def test_supervision_recibe_desde_la_web(self):
        entrega = self.entregar().data
        supervisor = APIClient()
        supervisor.force_authenticate(usuario_con_rol('supervisor', 'Supervisor de turno'))
        respuesta = supervisor.post(f"/api/surtido/{entrega['id']}/recibir/", {'firma_password': 'clave-de-prueba'}, format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)

    def test_planeadora_surte_desde_la_terminal_con_su_pin(self):
        paola, datos = self.terminal('PL-1', '5678')
        self.assertIn('surtir_material', datos['permisos'])
        respuesta = self.entregar(paola, firma={'firma_pin': '5678'})
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertEqual(respuesta.data['entregado_por_nombre'], 'Paola (PL-1)')

        ana, datos_ana = self.terminal('OP-1', '1234')
        self.assertEqual(datos_ana['permisos'], [])
        self.assertEqual(self.entregar(ana, firma={'firma_pin': '1234'}).status_code, 403)

    def test_rechazo_exige_motivo_y_no_cuenta_como_surtido(self):
        entrega = self.entregar().data
        ana, _ = self.terminal('OP-1', '1234')
        url = f"/api/surtido/{entrega['id']}/rechazar/"
        self.assertEqual(ana.post(url, {'firma_pin': '1234', 'motivo': 'mal'}, format='json').status_code, 400)
        respuesta = ana.post(url, {'firma_pin': '1234', 'motivo': 'La bolsa llegó con fuga'}, format='json')
        self.assertEqual(respuesta.data['estado'], 'RECHAZADA')
        self.assertEqual(self.surtido()['estado'], 'SIN_SURTIR')

    def test_devolucion_del_sobrante(self):
        entrega = self.entregar(cantidad='2.5').data
        ana, _ = self.terminal('OP-1', '1234')
        ana.post(f"/api/surtido/{entrega['id']}/recibir/", {'firma_pin': '1234'}, format='json')
        self.assertEqual(Decimal(self.surtido()['excedente']), Decimal('0.5'))

        url = f"/api/surtido/{entrega['id']}/devolver/"
        self.assertIn('hasta 2.5 L', ana.post(url, {'firma_pin': '1234', 'cantidad': '3'}, format='json').data['error'])
        devolucion = ana.post(url, {'firma_pin': '1234', 'cantidad': '0.5'}, format='json')
        self.assertEqual(devolucion.status_code, 201, devolucion.data)
        self.assertEqual((devolucion.data['tipo'], devolucion.data['lote_material']), ('DEVOLUCION', 'MC-2026-118'))

        pendientes = self.almacen.get('/api/surtido/por-surtir/').data['devoluciones']
        self.assertEqual([d['id'] for d in pendientes], [devolucion.data['id']])
        recibida = self.almacen.post(f"/api/surtido/{devolucion.data['id']}/recibir/", {'firma_password': 'clave-de-prueba'}, format='json')
        self.assertEqual(recibida.status_code, 200, recibida.data)
        surtido = self.surtido()
        self.assertEqual((surtido['estado'], Decimal(surtido['recibido'])), ('COMPLETO', Decimal('2')))

    # --- Avisos -------------------------------------------------------------------

    def test_inicia_sin_material_completo_pero_lo_advierte(self):
        programar_ahora(self.fase)
        ana, _ = self.terminal('OP-1', '1234')
        respuesta = ana.post(f'/api/fases-lote/{self.fase.id}/cambiar-estado/', {'estado': 'EN_PROGRESO', 'firma_pin': '1234'}, format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertIn('Medio CHO: sin surtir', respuesta.data['advertencia_materiales'][0])

    def test_planificacion_alerta_material_sin_surtir_a_su_hora(self):
        self.fase.inicio_programado = timezone.now() + timedelta(hours=1)  # requerido 12 h antes: ya pasó
        self.fase.fin_programado = self.fase.inicio_programado + timedelta(hours=2)
        self.fase.save()
        alertas = self.jefa.get('/api/fases-lote/alertas/').data
        self.assertTrue(any('aún no se recibe completo' in m for m in alertas[self.fase.id]))

        entrega = self.entregar().data
        ana, _ = self.terminal('OP-1', '1234')
        ana.post(f"/api/surtido/{entrega['id']}/recibir/", {'firma_pin': '1234'}, format='json')
        restantes = self.jefa.get('/api/fases-lote/alertas/').data.get(self.fase.id, [])
        self.assertFalse(any('📦' in m for m in restantes))


class OperadoresDisponiblesTests(TestCase):
    """Planificación ofrece solo a quien tiene turno a la hora de la actividad y no está ocupado."""

    def setUp(self):
        from roster.models import TipoTurno
        self.web = APIClient()
        self.web.force_authenticate(usuario_con_rol('planeador', 'Planeador'))
        self.proceso = ProcesoMaestro.objects.create(nombre='Proceso turnos')
        self.t1 = OperacionProceso.objects.create(proceso=self.proceso, identificador_paso='T1', nombre='Limpieza', orden=1, duracion_horas=2)
        self.rol = RolOperador.objects.create(nombre='Operador base')
        cuadrilla = Cuadrilla.objects.create(identificador='A', nombre='Cuadrilla A')
        crear = lambda nombre, codigo: Operador.objects.create(cuadrilla=cuadrilla, nombre=nombre, codigo_empleado=codigo, rol=self.rol)
        self.dia, self.noche, self.tarde, self.descanso = crear('Diana', 'D1'), crear('Nora', 'N1'), crear('Tomás', 'T1'), crear('Raúl', 'R1')
        self.matutino = TipoTurno.objects.create(codigo='M', nombre='Matutino', hora_inicio='07:00', hora_fin='15:00')
        self.nocturno = TipoTurno.objects.create(codigo='N', nombre='Nocturno', hora_inicio='23:00', hora_fin='07:00')
        self.vespertino = TipoTurno.objects.create(codigo='V', nombre='Vespertino', hora_inicio='15:00', hora_fin='23:00')
        self.off = TipoTurno.objects.create(codigo='OFF', nombre='Descanso', es_descanso=True)
        respuesta = self.web.post('/api/lotes/', {'identificador_lote': 'L-T', 'proceso_maestro': self.proceso.id,
                                                  'fecha_inicio_planeada': '2026-11-03T01:30:00'}, format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.fase = FaseLote.objects.get(lote__identificador_lote='L-T', operacion_maestra=self.t1)

    def turno(self, operador, tipo, dia):
        from roster.models import TurnoDia
        return TurnoDia.objects.create(operador=operador, fecha=datetime(2026, 11, dia).date(), tipo_turno=tipo)

    def disponibles(self):
        respuesta = self.web.get(f'/api/fases-lote/{self.fase.id}/disponibles/')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        return {d['nombre']: d for d in respuesta.data}

    def test_solo_quien_tiene_turno_a_la_hora_de_la_actividad(self):
        # Actividad 03/11 01:30–03:30: cubre el nocturno que empezó el 02/11; el matutino y vespertino del 03 no
        self.turno(self.noche, self.nocturno, 2)
        self.turno(self.dia, self.matutino, 3)
        self.turno(self.tarde, self.vespertino, 3)
        self.turno(self.descanso, self.off, 3)
        self.assertEqual(set(self.disponibles()), {'Nora'})

    def test_excluye_a_quien_ya_tiene_otra_tarea_a_esa_hora(self):
        self.turno(self.noche, self.nocturno, 2)
        otra = FaseLote.objects.create(lote=self.fase.lote, operacion_maestra=self.t1, es_subtarea_muestreo=True, indice_muestreo=1,
                                       inicio_programado=self.fase.inicio_programado, fin_programado=self.fase.fin_programado)
        AsignacionFaseOperador.objects.create(fase_lote=otra, operador=self.noche, rol_ejercido=self.rol)
        self.assertEqual(self.disponibles(), {})

    def test_salida_anticipada_y_turno_que_termina_antes(self):
        from roster.models import IncidenciaTurno
        turno = self.turno(self.noche, self.nocturno, 2)
        self.assertTrue(self.disponibles()['Nora']['cubre_toda'])
        IncidenciaTurno.objects.create(turno_dia=turno, horas_salida_anticipada=Decimal('4.5'))  # sale 02:30
        self.assertFalse(self.disponibles()['Nora']['cubre_toda'])
        IncidenciaTurno.objects.filter(turno_dia=turno).update(horas_salida_anticipada=Decimal('6'))  # sale 01:00
        self.assertEqual(self.disponibles(), {})

    def test_tarea_completada_libera_al_operador(self):
        """Regresión: un operador seguía "ocupado" por una tarea ya terminada que estaba programada a la misma hora."""
        self.turno(self.noche, self.nocturno, 2)
        otra = FaseLote.objects.create(lote=self.fase.lote, operacion_maestra=self.t1, es_subtarea_muestreo=True, indice_muestreo=1,
                                       inicio_programado=self.fase.inicio_programado, fin_programado=self.fase.fin_programado,
                                       estado='COMPLETADA', fecha_inicio_real=self.fase.inicio_programado - timedelta(hours=3),
                                       fecha_fin_real=self.fase.inicio_programado - timedelta(hours=1))
        AsignacionFaseOperador.objects.create(fase_lote=otra, operador=self.noche, rol_ejercido=self.rol)
        self.assertIn('Nora', self.disponibles())
        respuesta = self.web.post('/api/asignaciones-operador/', {'fase_lote': self.fase.id, 'operador': self.noche.id,
                                                                  'rol_ejercido': self.rol.id}, format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)

    def test_tarea_completada_ocupa_su_horario_real(self):
        self.turno(self.noche, self.nocturno, 2)
        otra = FaseLote.objects.create(lote=self.fase.lote, operacion_maestra=self.t1, es_subtarea_muestreo=True, indice_muestreo=1,
                                       inicio_programado=self.fase.inicio_programado - timedelta(hours=5),
                                       fin_programado=self.fase.inicio_programado - timedelta(hours=4), estado='COMPLETADA',
                                       fecha_inicio_real=self.fase.inicio_programado - timedelta(hours=1),
                                       fecha_fin_real=self.fase.inicio_programado + timedelta(hours=1))
        AsignacionFaseOperador.objects.create(fase_lote=otra, operador=self.noche, rol_ejercido=self.rol)
        self.assertEqual(self.disponibles(), {})


class ListadosEscalablesTests(TestCase):
    """Con cientos de lotes de miles de tareas, las listas no traen todas las tareas."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(usuario_con_rol('consulta', 'Consulta'))
        receta = ProcesoMaestro.objects.create(nombre='Receta listados')
        etapa = EtapaProceso.objects.create(proceso=receta, nombre='Inóculo', orden=1)
        self.op = OperacionProceso.objects.create(proceso=receta, etapa=etapa, identificador_paso='T1', nombre='Siembra',
                                                  duracion_horas=2)
        suelta = OperacionProceso.objects.create(proceso=receta, identificador_paso='T2', nombre='Limpieza', duracion_horas=1)
        self.lote_a = LoteProduccion.objects.create(identificador_lote='A', proceso_maestro=receta, estado='EN_PROGRESO',
                                                    fecha_inicio_planeada=local(2026, 3, 2, 8))
        self.lote_b = LoteProduccion.objects.create(identificador_lote='B', proceso_maestro=receta, estado='COMPLETADO',
                                                    fecha_inicio_planeada=local(2025, 1, 6, 8))
        self.a1 = self.fase(self.lote_a, self.op, local(2026, 3, 2, 8), local(2026, 3, 2, 10), 'COMPLETADA')
        self.a2 = self.fase(self.lote_a, suelta, local(2026, 3, 9, 23), local(2026, 3, 10, 1))   # cruza medianoche
        self.b1 = self.fase(self.lote_b, self.op, local(2025, 1, 6, 8), local(2025, 1, 6, 10), 'COMPLETADA')

    @staticmethod
    def fase(lote, op, inicio, fin, estado='PENDIENTE'):
        return FaseLote.objects.create(lote=lote, operacion_maestra=op, estado=estado, inicio_programado=inicio,
                                       fin_programado=fin, inicio_base_cpm=inicio, fin_base_cpm=fin)

    def ids(self, url):
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200, r.content)
        return sorted(f['id'] for f in r.json())

    def test_tareas_por_lote_y_por_ventana(self):
        self.assertEqual(self.ids(f'/api/fases-lote/?lote={self.lote_a.id}'), sorted([self.a1.id, self.a2.id]))
        # Semana del 2 al 9 de marzo: la siembra; la tarea que empieza el 9 a las 23 h cae en la siguiente
        self.assertEqual(self.ids('/api/fases-lote/?desde=2026-03-02&hasta=2026-03-09'), [self.a1.id])
        # El día 10 ve la tarea que viene cruzando la medianoche
        desde = local(2026, 3, 10, 0).isoformat()
        hasta = local(2026, 3, 11, 0).isoformat()
        self.assertEqual(self.ids(f'/api/fases-lote/?desde={desde}&hasta={hasta}'), [self.a2.id])
        self.assertEqual(self.client.get('/api/fases-lote/?desde=ayer').status_code, 400)

    def test_lista_de_lotes_sin_tareas_y_con_avance(self):
        r = self.client.get('/api/lotes/')
        self.assertEqual(r.status_code, 200)
        a = next(l for l in r.json() if l['id'] == self.lote_a.id)
        self.assertNotIn('fases', a)
        self.assertEqual(a['progreso_porcentual'], 50.0)
        self.assertIn('fases', self.client.get(f'/api/lotes/{self.lote_a.id}/').json())   # el detalle sí las trae

    def test_gantt_agregado_y_terminados_viejos_ocultos(self):
        r = self.client.get('/api/lotes/gantt/').json()
        self.assertEqual(r['ocultos'], 1)  # el lote B terminó hace más de 30 días
        (lote,) = r['lotes']
        self.assertEqual([f['nombre'] for f in lote['filas']], ['Inóculo', 'Sin etapa asignada'])
        self.assertTrue(lote['filas'][0]['prog_inicio'] and lote['filas'][1]['prog_fin'])
        todos = self.client.get('/api/lotes/gantt/?todos=1').json()
        self.assertEqual((len(todos['lotes']), todos['ocultos']), (2, 0))
