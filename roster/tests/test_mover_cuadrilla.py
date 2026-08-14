# roster/tests/test_mover_cuadrilla.py

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth.models import User
from apps.roster.models import Cuadrilla, Operador


@pytest.mark.django_db
class TestMoverColaboradoresAPI:
    """
    Suite de pruebas automatizadas para el endpoint de reasignación atómica de cuadrillas.
    Garantiza trazabilidad y cumplimiento de reglas GxP.
    """

    @pytest.fixture(autouse=True)
    def setup_data(self):
        # Configuración inicial de datos de prueba
        self.client = APIClient()
        self.user = User.objects.create_user(username='operador_gmp', password='securepassword123')
        self.client.force_authenticate(user=self.user)

        self.cuadrilla_a = Cuadrilla.objects.create(identificador='A', nombre='Cuadrilla Alpha', activa=True)
        self.cuadrilla_b = Cuadrilla.objects.create(identificador='B', nombre='Cuadrilla Bravo', activa=True)
        self.cuadrilla_inactiva = Cuadrilla.objects.create(identificador='X', nombre='Cuadrilla Inactiva', activa=False)

        self.op1 = Operador.objects.create(nombre='Juan Pérez', codigo_empleado='OP001', cuadrilla=self.cuadrilla_a, activo=True)
        self.op2 = Operador.objects.create(nombre='María Gómez', codigo_empleado='OP002', cuadrilla=self.cuadrilla_a, activo=True)
        self.op_otra = Operador.objects.create(nombre='Carlos Ruiz', codigo_empleado='OP003', cuadrilla=self.cuadrilla_b, activo=True)

        self.url = reverse('api-mover-cuadrilla')

    def test_mover_colaboradores_exitoso(self):
        """
        Verifica que se puedan reasignar operadores de forma atómica a una cuadrilla activa válida.
        """
        payload = {
            "operador_ids": [self.op1.id, self.op2.id],
            "cuadrilla_destino_id": self.cuadrilla_b.id
        }

        response = self.client.post(self.url, payload, format='json')

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['success'] is True
        assert data['moved_count'] == 2
        assert data['destination_group_id'] == self.cuadrilla_b.id

        # Verificar en base de datos
        self.op1.refresh_from_db()
        self.op2.refresh_from_db()
        assert self.op1.cuadrilla == self.cuadrilla_b
        assert self.op2.cuadrilla == self.cuadrilla_b

    def test_mover_a_cuadrilla_inactiva_falla(self):
        """
        Verifica que el sistema rechace el movimiento si la cuadrilla destino está inactiva (Control GxP).
        """
        payload = {
            "operador_ids": [self.op1.id],
            "cuadrilla_destino_id": self.cuadrilla_inactiva.id
        }

        response = self.client.post(self.url, payload, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert data['success'] is False

    def test_mover_operadores_de_diferentes_cuadrillas_falla(self):
        """
        Verifica que no se puedan mezclar operadores de distintas cuadrillas en una sola operación masiva.
        """
        payload = {
            "operador_ids": [self.op1.id, self.op_otra.id],
            "cuadrilla_destino_id": self.cuadrilla_b.id
        }

        response = self.client.post(self.url, payload, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert data['success'] is False

    def test_mover_a_misma_cuadrilla_falla(self):
        """
        Verifica que se rechace el movimiento si la cuadrilla destino es igual a la origen.
        """
        payload = {
            "operador_ids": [self.op1.id],
            "cuadrilla_destino_id": self.cuadrilla_a.id
        }

        response = self.client.post(self.url, payload, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert data['success'] is False
        