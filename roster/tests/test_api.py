# roster/tests/test_api.py

import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from django.contrib.auth.models import User
from roster.models import TipoTurno, Cuadrilla, Operador, SecuenciaRol, SecuenciaRolDetalle


@pytest.mark.django_db
class SecuenciaRolAPITests:
    """
    Suite de pruebas de integración para los Endpoints REST del módulo Roster y Secuencias,
    asegurando cumplimiento con GxP y estabilidad de contratos JSON.
    """

    def setup_method(self):
        self.client = APIClient()
        self.user = User.objects.create_superuser(username='admin', password='password123')
        self.tipo_turno_m = TipoTurno.objects.create(
            codigo='M',
            nombre='Matutino',
            color_fondo='#3b82f6',
            color_texto='#ffffff',
            es_descanso=False,
            activo=True
        )
        self.url = reverse('secuencia-list')

    def test_get_cuadrillas_endpoint(self):
        """Valida la obtención de cuadrillas con operadores y turnos enriquecidos con HEX."""
        cuadrilla = Cuadrilla.objects.create(identificador='A', nombre='Equipo 1')
        operador = Operador.objects.create(
            nombre='Carlos Pérez',
            codigo_empleado='OP-001',
            cuadrilla=cuadrilla,
            nivel_expertiz='SENIOR'
        )
        
        url = reverse('cuadrilla-list')
        response = self.client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]['identificador'] == 'A'
        assert len(data[0]['operadores']) == 1
        assert data[0]['operadores'][0]['nombre'] == 'Carlos Pérez'

    def test_get_lista_secuencias(self):
        """
        Verifica que el endpoint GET retorne las secuencias existentes
        incluyendo sus detalles anidados (acceso público de lectura).
        """
        secuencia = SecuenciaRol.objects.create(nombre="Test Rotación", activa=True)
        SecuenciaRolDetalle.objects.create(
            secuencia=secuencia,
            orden=1,
            tipo_turno=self.tipo_turno_m,
            dias=5
        )

        response = self.client.get(self.url)
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]['nombre'] == "Test Rotación"
        assert len(data[0]['detalles']) == 1
        assert data[0]['detalles'][0]['codigo_turno'] == 'M'

    def test_create_secuencia_con_detalles(self):
        """
        Verifica que al crear una secuencia vía POST con autenticación,
        se creen correctamente los registros en SecuenciaRol y SecuenciaRolDetalle
        utilizando la relación con el catálogo maestro TipoTurno.
        """
        self.client.force_authenticate(user=self.user)
        
        valid_payload = {
            "nombre": "Secuencia Planta Upstream",
            "descripcion": "Rotación de turnos estandarizada GxP",
            "activa": True,
            "detalles": [
                {
                    "orden": 1,
                    "tipo_turno": self.tipo_turno_m.codigo,
                    "dias": 3
                }
            ]
        }

        response = self.client.post(self.url, valid_payload, format='json')
        assert response.status_code == 201
        data = response.json()
        assert data['nombre'] == "Secuencia Planta Upstream"
        assert len(data['detalles']) == 1
        assert data['detalles'][0]['codigo_turno'] == 'M'