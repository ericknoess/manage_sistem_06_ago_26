# roster/tests/test_mover_cuadrilla.py

import pytest
from django.urls import reverse
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from roster.models import Cuadrilla, Operador

@pytest.mark.django_db
class TestMoverCuadrillaAPIView:
    """
    Pruebas de integración para el endpoint de reasignación de cuadrilla.
    """

    def setup_method(self):
        self.client = APIClient()
        self.url = reverse('mover-cuadrilla')

        # Creamos un usuario para autenticar la petición
        self.user = User.objects.create_user(username='test_user', password='password')
        self.client.force_authenticate(user=self.user)

        self.cuadrilla_origen = Cuadrilla.objects.create(
            identificador="Q-A",
            nombre="Línea Upstream CHO 1",
            activa=True
        )
        self.cuadrilla_destino = Cuadrilla.objects.create(
            identificador="Q-B",
            nombre="Línea Upstream CHO 2",
            activa=True
        )

        self.operador_1 = Operador.objects.create(
            nombre="Técnico Bioproceso 1",
            codigo_empleado="BIO-101",
            cuadrilla=self.cuadrilla_origen,
            activo=True,
            nivel_expertiz="senior"
        )

    def test_mover_cuadrilla_exito(self):
        payload = {
            "operador_ids": [self.operador_1.id],
            "cuadrilla_destino_id": self.cuadrilla_destino.id
        }
        response = self.client.post(self.url, payload, format='json')
        assert response.status_code == 200
        
        self.operador_1.refresh_from_db()
        assert self.operador_1.cuadrilla_id == self.cuadrilla_destino.id