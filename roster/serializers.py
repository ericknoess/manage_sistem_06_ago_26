# roster/serializers.py

from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Cuadrilla, Operador, TurnoDia, SecuenciaRol, SecuenciaRolDetalle


class TurnoDiaSerializer(serializers.ModelSerializer):
    """
    Serializer para el modelo TurnoDia.
    Gestiona la representación JSON de los turnos operacionales con trazabilidad GxP.
    """
    class Meta:
        model = TurnoDia
        fields = ['id', 'operador', 'fecha', 'codigo_turno']


class OperadorSerializer(serializers.ModelSerializer):
    """
    Serializer para Operadores. Integra metadatos fotográficos, nivel de expertiz,
    código de empleado y filtrado dinámico de turnos por mes/año según query params.
    Declara explícitamente 'foto' como ImageField para soportar subidas multipart/form-data.
    """
    turnos = serializers.SerializerMethodField()
    cuadrilla_nombre = serializers.CharField(source='cuadrilla.nombre', read_only=True)
    cuadrilla_identificador = serializers.CharField(source='cuadrilla.identificador', read_only=True)
    nivel_expertiz_display = serializers.CharField(source='get_nivel_expertiz_display', read_only=True)
    foto = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Operador
        fields = [
            'id',
            'nombre',
            'codigo_empleado',
            'cuadrilla',
            'cuadrilla_nombre',
            'cuadrilla_identificador',
            'foto',
            'nivel_expertiz',
            'nivel_expertiz_display',
            'activo',
            'turnos'
        ]

    def get_turnos(self, obj):
        """
        Filtra los turnos del operador basándose en el mes y año 
        enviados en la URL (?month=X&year=YYYY).
        """
        request = self.context.get('request')
        if request:
            month = request.query_params.get('month')
            year = request.query_params.get('year')
            turnos_qs = obj.turnos.all()
            if month and year:
                turnos_qs = turnos_qs.filter(fecha__month=month, fecha__year=year)
            return TurnoDiaSerializer(turnos_qs, many=True, context=self.context).data
        return []


class CuadrillaSerializer(serializers.ModelSerializer):
    """
    Serializer para Cuadrillas, anidando sus operadores enriquecidos y turnos correspondientes.
    """
    operadores = OperadorSerializer(many=True, read_only=True)

    class Meta:
        model = Cuadrilla
        fields = [
            'id', 
            'identificador', 
            'nombre', 
            'activa', 
            'descripcion', 
            'creado_en', 
            'operadores'
        ]


class MoverColaboradoresSerializer(serializers.Serializer):
    """
    Serializer encargado de validar y procesar la reasignación masiva o individual 
    de operadores entre cuadrillas, validando estados activos y consistencia GxP.
    """
    operador_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
        help_text="Lista de IDs de los colaboradores a mover"
    )
    cuadrilla_destino_id = serializers.IntegerField(
        help_text="ID de la cuadrilla destino"
    )

    def validate(self, data):
        """
        Validaciones de negocio robustas en backend con trazas de diagnóstico GxP.
        """
        # 1. Validar Cuadrilla Destino
        try:
            cuadrilla_destino = Cuadrilla.objects.get(id=data['cuadrilla_destino_id'])
            if not cuadrilla_destino.activa:
                raise serializers.ValidationError({
                    "cuadrilla_destino_id": "La cuadrilla destino no se encuentra activa."
                })
        except Cuadrilla.DoesNotExist:
            raise serializers.ValidationError({
                "cuadrilla_destino_id": "La cuadrilla destino especificada no existe."
            })

        # 2. Validar Operadores y depurar estado en Base de Datos
        operador_ids = data['operador_ids']
        operadores = Operador.objects.filter(id__in=operador_ids)
        
        print(f"\n--- [DIAGNÓSTICO GxP MOVER COLABORADORES] ---")
        print(f"IDs recibidos en payload: {operador_ids}")
        for op in operadores:
            print(f" -> Operador ID: {op.id} | Nombre: {op.nombre} | Cuadrilla ID en BD: {op.cuadrilla_id}")

        if operadores.count() != len(operador_ids):
            raise serializers.ValidationError({
                "operador_ids": "Uno o más colaboradores seleccionados no existen en el sistema."
            })

        # Verificar que todos los operadores estén activos
        operadores_inactivos = operadores.filter(activo=False)
        if operadores_inactivos.exists():
            nombres_inactivos = ", ".join([op.nombre for op in operadores_inactivos])
            raise serializers.ValidationError({
                "operador_ids": f"Los siguientes colaboradores están inactivos y no pueden ser movidos: {nombres_inactivos}."
            })

        # 3. Validar Cuadrilla Origen (Consistencia para operaciones múltiples)
        cuadrillas_origen = set(operadores.values_list('cuadrilla_id', flat=True))
        print(f"Cuadrillas origen únicas detectadas en BD: {cuadrillas_origen}")
        print(f"-----------------------------------------------\n")

        if len(cuadrillas_origen) > 1:
            nombres_cuadrillas = list(Cuadrilla.objects.filter(id__in=cuadrillas_origen).values_list('nombre', flat=True))
            raise serializers.ValidationError({
                "operador_ids": f"Los colaboradores seleccionados pertenecen a diferentes cuadrillas origen: {', '.join(str(n) for n in nombres_cuadrillas)}."
            })
        
        cuadrilla_origen_id = list(cuadrillas_origen)[0]
        
        # 4. Validar que la cuadrilla destino sea distinta a la origen
        if cuadrilla_origen_id == data['cuadrilla_destino_id']:
            raise serializers.ValidationError({
                "cuadrilla_destino_id": "La cuadrilla destino debe ser diferente a la cuadrilla actual de los colaboradores."
            })

        return data


class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Serializer dedicado a la creación y registro seguro de usuarios del sistema (Django Auth)
    con soporte para vinculación opcional a operadores de planta.
    """
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    password_confirm = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    operador_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password', 'password_confirm', 'operador_id', 'is_active']

    def validate(self, data):
        """
        Valida que la contraseña y su confirmación coincidan exactamente.
        """
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({"password_confirm": "Las contraseñas no coinciden."})
        return data

    def create(self, validated_data):
        """
        Crea un nuevo usuario de manera segura utilizando los métodos nativos de Django
        para el cifrado de contraseñas.
        """
        validated_data.pop('password_confirm')
        operador_id = validated_data.pop('operador_id', None)
        
        password = validated_data.pop('password')
        user = User.objects.create_user(**validated_data)
        user.set_password(password)
        user.save()

        if operador_id:
            try:
                operador = Operador.objects.get(id=operador_id)
            except Operador.DoesNotExist:
                pass

        return user

    def to_representation(self, instance):
        """
        Personaliza la respuesta JSON devuelta tras la creación del usuario,
        evitando exponer campos internos o sensibles.
        """
        return {
            'id': instance.id,
            'username': instance.username,
            'email': instance.email,
            'is_active': instance.is_active
        }


class SecuenciaRolDetalleSerializer(serializers.ModelSerializer):
    """
    Serializer para los pasos individuales de una secuencia.
    """
    class Meta:
        model = SecuenciaRolDetalle
        fields = ['id', 'orden', 'codigo_turno', 'dias']


class SecuenciaRolSerializer(serializers.ModelSerializer):
    """
    Serializer para SecuenciaRol con soporte de escritura anidada (detalles).
    Permite crear/editar la secuencia y sus pasos en una sola petición.
    """
    detalles = SecuenciaRolDetalleSerializer(many=True)

    class Meta:
        model = SecuenciaRol
        fields = ['id', 'nombre', 'descripcion', 'activa', 'creado_en', 'detalles']

    def create(self, validated_data):
        detalles_data = validated_data.pop('detalles')
        secuencia = SecuenciaRol.objects.create(**validated_data)
        for detalle_data in detalles_data:
            SecuenciaRolDetalle.objects.create(secuencia=secuencia, **detalle_data)
        return secuencia

    def update(self, instance, validated_data):
        detalles_data = validated_data.pop('detalles', None)
        instance.nombre = validated_data.get('nombre', instance.nombre)
        instance.descripcion = validated_data.get('descripcion', instance.descripcion)
        instance.activa = validated_data.get('activa', instance.activa)
        instance.save()

        if detalles_data is not None:
            instance.detalles.all().delete()
            for detalle_data in detalles_data:
                SecuenciaRolDetalle.objects.create(secuencia=instance, **detalle_data)
        
        return instance