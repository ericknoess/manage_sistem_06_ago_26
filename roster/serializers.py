# roster/serializers.py

from rest_framework import serializers
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from .models import TipoTurno, Cuadrilla, RolOperador, Operador, TurnoDia, SecuenciaRol, SecuenciaRolDetalle, IncidenciaTurno


class TipoTurnoSerializer(serializers.ModelSerializer):
    """
    Serializer para el catálogo maestro de Tipos de Turno.
    Expone los códigos, propiedades visuales de color HEX y las franjas horarias operativas.
    """
    class Meta:
        model = TipoTurno
        fields = [
            'codigo', 
            'nombre', 
            'color_fondo', 
            'color_texto', 
            'es_descanso', 
            'activo', 
            'hora_inicio', 
            'hora_fin'
        ]


class IncidenciaTurnoSerializer(serializers.ModelSerializer):
    """
    Serializer exclusivo para el registro y actualización de incidencias operacionales.
    Valida las reglas de negocio antes de tocar la base de datos (HTTP 400).
    """
    class Meta:
        model = IncidenciaTurno
        fields = ['id', 'turno_dia', 'minutos_retardo', 'horas_salida_anticipada', 'notas']

    def validate(self, data):
        retardo = data.get('minutos_retardo')
        salida = data.get('horas_salida_anticipada')
        notas = data.get('notas')

        if retardo is None and salida is None and (not notas or str(notas).strip() == ''):
            raise serializers.ValidationError(
                "Debe especificar al menos un tiempo de retardo, salida anticipada o una nota."
            )
        return data


class TurnoDiaSerializer(serializers.ModelSerializer):
    """
    Serializer para el modelo TurnoDia.
    Gestiona la representación JSON de los turnos operacionales con trazabilidad GxP
    y metadatos de color integrados desde el catálogo maestro.
    """
    codigo_turno = serializers.SerializerMethodField()
    color_fondo = serializers.SerializerMethodField()
    color_texto = serializers.SerializerMethodField()
    tiene_incidencia = serializers.SerializerMethodField()
    incidencia_detalle = serializers.SerializerMethodField()
    
    tipo_turno = serializers.PrimaryKeyRelatedField(
        queryset=TipoTurno.objects.filter(activo=True),
        write_only=True,
        required=False,
        allow_null=True
    )

    class Meta:
        model = TurnoDia
        fields = [
            'id', 'operador', 'fecha', 'codigo_turno', 'color_fondo', 'color_texto', 
            'tipo_turno', 'tiene_incidencia', 'incidencia_detalle'
        ]

    def get_codigo_turno(self, obj):
        try:
            if obj.tipo_turno_id and obj.tipo_turno:
                return obj.tipo_turno.codigo
        except (ObjectDoesNotExist, Exception):
            pass
        return ''

    def get_color_fondo(self, obj):
        try:
            if obj.tipo_turno_id and obj.tipo_turno:
                return obj.tipo_turno.color_fondo
        except (ObjectDoesNotExist, Exception):
            pass
        return '#3b82f6'

    def get_color_texto(self, obj):
        try:
            if obj.tipo_turno_id and obj.tipo_turno:
                return obj.tipo_turno.color_texto
        except (ObjectDoesNotExist, Exception):
            pass
        return '#ffffff'

    def get_tiene_incidencia(self, obj):
        try:
            return hasattr(obj, 'incidencia') and obj.incidencia is not None
        except ObjectDoesNotExist:
            return False

    def get_incidencia_detalle(self, obj):
        try:
            if hasattr(obj, 'incidencia') and obj.incidencia:
                return {
                    'id': obj.incidencia.id,
                    'minutos_retardo': obj.incidencia.minutos_retardo,
                    'horas_salida_anticipada': obj.incidencia.horas_salida_anticipada,
                    'notas': obj.incidencia.notas
                }
        except ObjectDoesNotExist:
            pass
        return None

    def create(self, validated_data):
        if 'tipo_turno' not in validated_data and 'codigo_turno' in self.initial_data:
            codigo = self.initial_data.get('codigo_turno')
            if not codigo:
                validated_data['tipo_turno'] = None
            else:
                try:
                    validated_data['tipo_turno'] = TipoTurno.objects.get(codigo=codigo)
                except TipoTurno.DoesNotExist:
                    validated_data['tipo_turno'] = TipoTurno.objects.get_or_create(codigo=codigo)[0]
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if 'tipo_turno' not in validated_data and 'codigo_turno' in self.initial_data:
            codigo = self.initial_data.get('codigo_turno')
            if not codigo:
                instance.tipo_turno = None
            else:
                try:
                    instance.tipo_turno = TipoTurno.objects.get(codigo=codigo)
                except TipoTurno.DoesNotExist:
                    instance.tipo_turno = TipoTurno.objects.get_or_create(codigo=codigo)[0]
        return super().update(instance, validated_data)


class RolOperadorSerializer(serializers.ModelSerializer):
    """
    Serializer para exponer el catálogo de competencias operacionales.
    """
    class Meta:
        model = RolOperador
        fields = ['id', 'nombre', 'descripcion', 'activo']


class OperadorSerializer(serializers.ModelSerializer):
    """
    Serializer para Operadores. Integra metadatos fotográficos, el rol/expertiz dinámico,
    código de empleado y filtrado dinámico de turnos por mes/año según query params.
    """
    turnos = serializers.SerializerMethodField()
    cuadrilla_nombre = serializers.CharField(source='cuadrilla.nombre', read_only=True)
    cuadrilla_identificador = serializers.CharField(source='cuadrilla.identificador', read_only=True)
    foto = serializers.ImageField(required=False, allow_null=True)
    
    # CAMPOS DE ROL SEGUROS PARA EL FRONTEND (Soluciona el problema de undefined)
    rol_nombre = serializers.SerializerMethodField()
    rol_detalle = RolOperadorSerializer(source='rol', read_only=True)

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
            'rol',               # Permite POST/PATCH enviando el ID del rol
            'rol_nombre',        # Para display rápido en frontend sin undefined
            'rol_detalle',       # Para obtener todos los datos del rol asociado
            'activo',
            'turnos'
        ]

    def get_rol_nombre(self, obj):
        """Retorna de manera segura el nombre del rol o 'Sin Rol' si es nulo."""
        if obj.rol:
            return obj.rol.nombre
        return 'Sin Rol'

    def get_turnos(self, obj):
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
    operador_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
        help_text="Lista de IDs de los colaboradores a mover"
    )
    cuadrilla_destino_id = serializers.IntegerField(
        help_text="ID de la cuadrilla destino"
    )

    def validate(self, data):
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

        operador_ids = data['operador_ids']
        operadores = Operador.objects.filter(id__in=operador_ids)

        if operadores.count() != len(operador_ids):
            raise serializers.ValidationError({
                "operador_ids": "Uno o más colaboradores seleccionados no existen en el sistema."
            })

        operadores_inactivos = operadores.filter(activo=False)
        if operadores_inactivos.exists():
            nombres_inactivos = ", ".join([op.nombre for op in operadores_inactivos])
            raise serializers.ValidationError({
                "operador_ids": f"Los siguientes colaboradores están inactivos y no pueden ser movidos: {nombres_inactivos}."
            })

        cuadrillas_origen = set(operadores.values_list('cuadrilla_id', flat=True))
        if len(cuadrillas_origen) > 1:
            nombres_cuadrillas = list(Cuadrilla.objects.filter(id__in=cuadrillas_origen).values_list('nombre', flat=True))
            raise serializers.ValidationError({
                "operador_ids": f"Los colaboradores seleccionados pertenecen a diferentes cuadrillas origen: {', '.join(str(n) for n in nombres_cuadrillas)}."
            })
        
        cuadrilla_origen_id = list(cuadrillas_origen)[0]
        if cuadrilla_origen_id == data['cuadrilla_destino_id']:
            raise serializers.ValidationError({
                "cuadrilla_destino_id": "La cuadrilla destino debe ser diferente a la cuadrilla actual de los colaboradores."
            })

        return data


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    password_confirm = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    operador_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password', 'password_confirm', 'operador_id', 'is_active']

    def validate(self, data):
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({"password_confirm": "Las contraseñas no coinciden."})
        return data

    def create(self, validated_data):
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
        return {
            'id': instance.id,
            'username': instance.username,
            'email': instance.email,
            'is_active': instance.is_active
        }


class SecuenciaRolDetalleSerializer(serializers.ModelSerializer):
    codigo_turno = serializers.CharField(source='tipo_turno.codigo', read_only=True)
    tipo_turno = serializers.PrimaryKeyRelatedField(
        queryset=TipoTurno.objects.filter(activo=True),
        write_only=True,
        required=False
    )

    class Meta:
        model = SecuenciaRolDetalle
        fields = ['id', 'orden', 'codigo_turno', 'tipo_turno', 'dias']

    def create(self, validated_data):
        if 'tipo_turno' not in validated_data and 'codigo_turno' in self.initial_data:
            codigo = self.initial_data.get('codigo_turno')
            try:
                validated_data['tipo_turno'] = TipoTurno.objects.get(codigo=codigo)
            except TipoTurno.DoesNotExist:
                validated_data['tipo_turno'] = TipoTurno.objects.get_or_create(codigo=codigo)[0]
        return super().create(validated_data)


class SecuenciaRolSerializer(serializers.ModelSerializer):
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