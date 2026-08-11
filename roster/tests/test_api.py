# roster/tests/test_api.py

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from roster.models import SecuenciaRol, SecuenciaRolDetalle

class SecuenciaRolAPITests(APITestCase):
    """
    Suite de pruebas para validar la API de Secuencias de Rol.
    Verifica la creación y persistencia de secuencias con sus detalles anidados.
    """

    def setUp(self):
        self.url = reverse('secuencia-list')
        # Creamos un usuario de prueba para cumplir con la política IsAuthenticatedOrReadOnly
        self.user = User.objects.create_user(username='operador_test', password='password123')
        self.valid_payload = {
            "nombre": "Rotación 4x2",
            "descripcion": "Ciclo estándar 4 días trabajo, 2 descanso",
            "activa": True,
            "detalles": [
                {"orden": 1, "codigo_turno": "M", "dias": 4},
                {"orden": 2, "codigo_turno": "OFF", "dias": 2}
            ]
        }

    def test_create_secuencia_con_detalles(self):
        """
        Verifica que al crear una secuencia vía POST con autenticación, 
        se creen correctamente los registros en SecuenciaRol y SecuenciaRolDetalle.
        """
        # Autenticamos al cliente para permitir la operación de escritura POST
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.url, self.valid_payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SecuenciaRol.objects.count(), 1)
        self.assertEqual(SecuenciaRolDetalle.objects.count(), 2)
        
        # Validar relación
        secuencia = SecuenciaRol.objects.first()
        self.assertEqual(secuencia.detalles.count(), 2)
        self.assertEqual(secuencia.nombre, "Rotación 4x2")

    def test_get_lista_secuencias(self):
        """
        Verifica que el endpoint GET retorne las secuencias existentes 
        incluyendo sus detalles anidados (acceso público de lectura).
        """
        # Creamos una secuencia base
        secuencia = SecuenciaRol.objects.create(nombre="Test", activa=True)
        SecuenciaRolDetalle.objects.create(secuencia=secuencia, orden=1, codigo_turno="T", dias=5)
        
        response = self.client.get(self.url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(len(response.data[0]['detalles']), 1)
        self.assertEqual(response.data[0]['detalles'][0]['codigo_turno'], "T")