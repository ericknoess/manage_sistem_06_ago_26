# roster/tests/test_views.py

import pytest
from django.urls import reverse
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from roster.models import Cuadrilla, Operador


@pytest.mark.django_db
class TestMoverCuadrillaAPIView:
    """
    Suite de pruebas de integración para el endpoint REST de reasignación masiva de operadores.
    Valida contratos de API, códigos de estado HTTP y respuestas de error GxP.
    """

    def setup_method(self):
        """
        Configuración de cliente HTTP, autenticación de usuario y fixtures iniciales de prueba.
        """
        self.client = APIClient()
        self.url = reverse('mover-cuadrilla')

        # Creamos y autenticamos un usuario para cumplir con las políticas de seguridad
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
        self.operador_2 = Operador.objects.create(
            nombre="Técnico Bioproceso 2",
            codigo_empleado="BIO-102",
            cuadrilla=self.cuadrilla_origen,
            activo=True,
            nivel_expertiz="junior"
        )

    def test_api_mover_colaboradores_exito(self):
        """
        Valida que una petición POST válida reasigne correctamente a los operadores 
        y responda con código HTTP 200 OK.
        """
        payload = {
            "operador_ids": [self.operador_1.id, self.operador_2.id],
            "cuadrilla_destino_id": self.cuadrilla_destino.id
        }
        
        response = self.client.post(self.url, payload, format='json')
        
        assert response.status_code == 200
        
        # Verificar en base de datos que la reasignación se aplicó correctamente
        self.operador_1.refresh_from_db()
        self.operador_2.refresh_from_db()
        
        assert self.operador_1.cuadrilla_id == self.cuadrilla_destino.id
        assert self.operador_2.cuadrilla_id == self.cuadrilla_destino.id

    def test_api_mover_colaboradores_bad_request(self):
        """
        Valida que el endpoint rechace con HTTP 400 Bad Request cuando se intenta 
        mover operadores a su misma cuadrilla actual.
        """
        payload = {
            "operador_ids": [self.operador_1.id],
            "cuadrilla_destino_id": self.cuadrilla_origen.id
        }
        
        response = self.client.post(self.url, payload, format='json')
        
        assert response.status_code == 400
        # Validamos contra la estructura de errores GxP de la respuesta
        errors = response.data.get("errors", response.data)
        assert "cuadrilla_destino_id" in errors