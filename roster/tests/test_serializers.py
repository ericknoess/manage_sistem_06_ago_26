# roster/tests/test_serializers.py

import pytest
from django.contrib.auth.models import User
from roster.models import Cuadrilla, Operador
from roster.serializers import MoverColaboradoresSerializer


@pytest.mark.django_db
class TestMoverColaboradoresSerializer:
    """
    Suite de pruebas unitarias para validar la lógica de negocio y consistencia GxP
    en la reasignación de colaboradores entre cuadrillas.
    """

    def setup_method(self):
        """
        Configuración inicial de datos de prueba (Fixtures).
        Creamos cuadrillas y operadores activos/inactivos para simular escenarios reales de planta.
        """
        self.cuadrilla_origen = Cuadrilla.objects.create(
            identificador="Q-01",
            nombre="Cuadrilla Origen A",
            activa=True
        )
        self.cuadrilla_destino = Cuadrilla.objects.create(
            identificador="Q-02",
            nombre="Cuadrilla Destino B",
            activa=True
        )
        self.cuadrilla_inactiva = Cuadrilla.objects.create(
            identificador="Q-03",
            nombre="Cuadrilla Inactiva C",
            activa=False
        )

        self.op1 = Operador.objects.create(
            nombre="Operador Alfa",
            codigo_empleado="OP-001",
            cuadrilla=self.cuadrilla_origen,
            activo=True,
            nivel_expertiz="senior"
        )
        self.op2 = Operador.objects.create(
            nombre="Operador Beta",
            codigo_empleado="OP-002",
            cuadrilla=self.cuadrilla_origen,
            activo=True,
            nivel_expertiz="junior"
        )
        self.op_inactivo = Operador.objects.create(
            nombre="Operador Inactivo",
            codigo_empleado="OP-999",
            cuadrilla=self.cuadrilla_origen,
            activo=False,
            nivel_expertiz="junior"
        )
        
        # Operador en otra cuadrilla para probar validación de consistencia
        self.otra_cuadrilla = Cuadrilla.objects.create(
            identificador="Q-04",
            nombre="Cuadrilla Externa D",
            activa=True
        )
        self.op_externo = Operador.objects.create(
            nombre="Operador Externo",
            codigo_empleado="OP-003",
            cuadrilla=self.otra_cuadrilla,
            activo=True,
            nivel_expertiz="senior"
        )

    def test_movimiento_exitoso(self):
        """
        Valida que un conjunto de operadores activos de la misma cuadrilla
        puedan ser movidos exitosamente a una cuadrilla destino activa.
        """
        data = {
            "operador_ids": [self.op1.id, self.op2.id],
            "cuadrilla_destino_id": self.cuadrilla_destino.id
        }
        serializer = MoverColaboradoresSerializer(data=data)
        assert serializer.is_valid() is True

    def test_error_cuadrilla_destino_inactiva(self):
        """
        Valida que el sistema rechace el movimiento si la cuadrilla destino está inactiva.
        """
        data = {
            "operador_ids": [self.op1.id],
            "cuadrilla_destino_id": self.cuadrilla_inactiva.id
        }
        serializer = MoverColaboradoresSerializer(data=data)
        assert serializer.is_valid() is False
        assert "cuadrilla_destino_id" in serializer.errors

    def test_error_operador_inactivo(self):
        """
        Valida que el sistema rechace el movimiento si se incluye algún operador inactivo.
        """
        data = {
            "operador_ids": [self.op1.id, self.op_inactivo.id],
            "cuadrilla_destino_id": self.cuadrilla_destino.id
        }
        serializer = MoverColaboradoresSerializer(data=data)
        assert serializer.is_valid() is False
        assert "operador_ids" in serializer.errors

    def test_error_cuadrillas_origen_distintas(self):
        """
        Valida que el sistema rechace el movimiento si los operadores pertenecen a cuadrillas origen distintas.
        """
        data = {
            "operador_ids": [self.op1.id, self.op_externo.id],
            "cuadrilla_destino_id": self.cuadrilla_destino.id
        }
        serializer = MoverColaboradoresSerializer(data=data)
        assert serializer.is_valid() is False
        assert "operador_ids" in serializer.errors

    def test_error_misma_cuadrilla_destino(self):
        """
        Valida que la cuadrilla destino no sea la misma que la cuadrilla actual de los operadores.
        """
        data = {
            "operador_ids": [self.op1.id],
            "cuadrilla_destino_id": self.cuadrilla_origen.id
        }
        serializer = MoverColaboradoresSerializer(data=data)
        assert serializer.is_valid() is False
        assert "cuadrilla_destino_id" in serializer.errors