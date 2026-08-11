# roster/tests/test_models.py

import pytest
from roster.models import Cuadrilla, Operador

@pytest.mark.django_db
class TestRosterModels:
    """
    Suite de pruebas unitarias para verificar la integridad de los modelos 
    del módulo de Roster (Cuadrillas y Operadores Upstream).
    """

    def test_creacion_cuadrilla(self):
        """
        Verifica que una cuadrilla operativa pueda ser creada correctamente
        con sus atributos esenciales para procesos Upstream (ej. Cultivo CHO).
        """
        cuadrilla = Cuadrilla.objects.create(
            identificador="CHO-UP-01",
            nombre="Línea Principal Cultivo Celular CHO",
            activa=True
        )
        
        assert cuadrilla.identificador == "CHO-UP-01"
        assert cuadrilla.nombre == "Línea Principal Cultivo Celular CHO"
        assert cuadrilla.activa is True
        assert cuadrilla.creado_en is not None

    def test_creacion_operador(self):
        """
        Verifica la correcta asociación entre un operador y su cuadrilla operativa,
        garantizando la trazabilidad GxP requerida en planta.
        """
        cuadrilla = Cuadrilla.objects.create(
            identificador="ECOLI-UP-02",
            nombre="Fermentación Bacteriana E. coli",
            activa=True
        )
        
        operador = Operador.objects.create(
            codigo_empleado="BIO-2026-001",
            nombre="Erick Sánchez",
            cuadrilla=cuadrilla,
            activo=True
        )

        assert operador.codigo_empleado == "BIO-2026-001"
        assert operador.nombre == "Erick Sánchez"
        assert operador.cuadrilla == cuadrilla
        assert operador.cuadrilla.identificador == "ECOLI-UP-02"
        assert operador.activo is True