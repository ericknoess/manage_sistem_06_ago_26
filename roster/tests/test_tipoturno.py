# roster/tests/test_tipoturno.py

import pytest
from roster.models import TipoTurno, Cuadrilla, Operador, TurnoDia


@pytest.mark.django_db
class TestTipoTurnoDomain:
    """
    Suite de pruebas unitarias para el catálogo maestro de Tipos de Turno (GxP Ready).
    """

    def test_creacion_tipo_turno(self):
        """Valida que se pueda crear un tipo de turno con propiedades HEX válidas."""
        turno = TipoTurno.objects.create(
            codigo='PERF',
            nombre='Perfusión Especial',
            color_fondo='#06b6d4',
            color_texto='#082f49',
            es_descanso=False,
            activo=True
        )
        assert turno.codigo == 'PERF'
        assert turno.color_fondo == '#06b6d4'
        assert str(turno) == "[PERF] Perfusión Especial"

    def test_integridad_turno_dia_fk(self):
        """Valida la relación de llave foránea entre TurnoDia y TipoTurno."""
        cuadrilla = Cuadrilla.objects.create(identificador='A', nombre='Equipo 1')
        operador = Operador.objects.create(
            nombre='Ana Gómez',
            codigo_empleado='OP-9999',
            cuadrilla=cuadrilla,
            nivel_expertiz='SENIOR'
        )
        tipo_turno = TipoTurno.objects.create(
            codigo='N',
            nombre='Nocturno',
            color_fondo='#92400e',
            color_texto='#ffffff'
        )

        turno_dia = TurnoDia.objects.create(
            operador=operador,
            fecha='2026-08-17',
            tipo_turno=tipo_turno
        )

        assert turno_dia.tipo_turno.codigo == 'N'
        assert turno_dia.operador.nombre == 'Ana Gómez'


@pytest.mark.django_db
class TestTipoTurnoAPI:
    """
    Suite de pruebas de integración para la API REST del catálogo de turnos.
    """

    def setup_method(self):
        from rest_framework.test import APIClient
        from django.urls import reverse
        self.client = APIClient()
        self.url = reverse('tipoturno-list')

    def test_listar_tipos_turno_api(self):
        """Valida que el endpoint GET /api/tipos-turno/ retorne los turnos registrados."""
        TipoTurno.objects.get_or_create(
            codigo='M',
            defaults={
                'nombre': 'Matutino',
                'color_fondo': '#3b82f6',
                'color_texto': '#ffffff'
            }
        )

        response = self.client.get(self.url)
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        # Verificamos que al menos uno de los elementos devueltos sea el turno 'M'
        codigos = [item['codigo'] for item in data]
        assert 'M' in codigos