# procesos/tests.py

from datetime import datetime, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from roster.models import Cuadrilla, Operador, RolOperador
from .models import ProcesoMaestro, OperacionProceso, LoteProduccion, FaseLote, AsignacionFaseOperador


def local(*args):
    return timezone.make_aware(datetime(*args))


class ProgramacionFasesTests(TestCase):
    """
    Receta de prueba:  T1 (2 h) → T2 (72 h, FS) → T3 (3 h, FS)
                                  T2 → T4 (1 h, SS +4 h)
    """

    def setUp(self):
        self.client = APIClient()
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
