# roster/tests.py

import pytest
from datetime import date
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth.models import User
from .models import Cuadrilla, Operador, PatronTurno, TurnoDia

@pytest.mark.django_db
class TestAplicarPatronCuadrilla:
    """
    Suite de pruebas unitarias y de integración para validar la aplicación masiva 
    de patrones de rotación de turnos a nivel de Cuadrilla (Upstream GxP).
    """

    @pytest.fixture(autouse=True)
    def setup_data(self):
        # 1. Crear usuario administrador para autenticación GxP
        self.admin_user = User.objects.create_superuser(username='admin_gxp', password='securepassword123')
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin_user)

        # 2. Crear Cuadrilla de prueba
        self.cuadrilla = Cuadrilla.objects.create(identificador='C1', nombre='Cuadrilla Alpha CHO')

        # 3. Crear Operadores activos asociados a la cuadrilla
        self.op1 = Operador.objects.create(nombre='Erick Sanchez', codigo_empleado='OP-001', cuadrilla=self.cuadrilla, activo=True)
        self.op2 = Operador.objects.create(nombre='Maria Perez', codigo_empleado='OP-002', cuadrilla=self.cuadrilla, activo=True)

        # 4. Crear Patrón de Turno de prueba (Secuencia de 4 días: M, T, OFF, OFF)
        self.patron = PatronTurno.objects.create(codigo='ROT-4D', nombre='Rotación Estándar Upstream', secuencia=['M', 'T', 'OFF', 'OFF'])

    def test_aplicacion_masiva_patron_exitosa(self):
        url = reverse('cuadrilla-aplicar-patron-cuadrilla', kwargs={'pk': self.cuadrilla.id})
        payload = {
            "patron_id": self.patron.id,
            "fecha_inicio": "2026-08-01",
            "mes": 8,
            "anio": 2026
        }

        response = self.client.post(url, payload, format='json')

        # Verificar respuesta HTTP 200 OK
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'success'
        assert data['operadores_actualizados'] == 2
        assert data['turnos_totales_generados'] > 0

        # Verificar persistencia en base de datos para el primer operador en agosto (31 días)
        turnos_op1 = TurnoDia.objects.filter(operador=self.op1, fecha__year=2026, fecha__month=8).order_by('fecha')
        assert turnos_op1.count() == 31

        # Validar ciclo del patrón a partir del 1 de agosto de 2026
        # Día 1 (2026-08-01, diferencia 0): índice 0 -> 'M'
        # Día 2 (2026-08-02, diferencia 1): índice 1 -> 'T'
        # Día 3 (2026-08-03, diferencia 2): índice 2 -> 'OFF'
        # Día 4 (2026-08-04, diferencia 3): índice 3 -> 'OFF'
        # Día 5 (2026-08-05, diferencia 4): índice 0 -> 'M'
        assert turnos_op1[0].codigo_turno == 'M'
        assert turnos_op1[1].codigo_turno == 'T'
        assert turnos_op1[2].codigo_turno == 'OFF'
        assert turnos_op1[3].codigo_turno == 'OFF'
        assert turnos_op1[4].codigo_turno == 'M'