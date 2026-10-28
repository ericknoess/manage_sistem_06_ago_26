# datos_proceso/views.py

from datetime import datetime

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from auditoria.mixins import AuditoriaMixin
from auditoria.services import firmar, quien, registrar
from eventos.services import eventos_fuera_especificacion
from procesos.models import AsignacionFaseOperador, FaseLote, LoteProduccion, ProcesoMaestro
from usuarios.firmas import FirmaRechazada, verificar_firma
from usuarios.permisos import PermisoCaptura, SOLO_SESION, operador_de_sesion, tiene_permiso
from .formulas import ErrorFormula, evaluar
from .models import IndicadorProceso, ParametroProceso, TomaDatos
from .serializers import IndicadorProcesoSerializer, ParametroProcesoSerializer
from .services import (
    MAX_LOTES_ANALISIS, MOTIVO_MINIMO, ErrorCaptura, analisis_lotes, datos_informe, filas_lotes_excel, avisos_limites, corregir_valor, detalle_captura, nombre_fase, operacion_admite_adicional,
    plan_de_operacion, preparar_valores, registrar_toma, registrar_toma_adicional, tabla_lote, texto_decimal,
    validar_formula_parametro,
)


class ParametroProcesoViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """
    Catálogo de parámetros de proceso. Filtros: ?q= (código o nombre), ?activo=true|false.
    Sin DELETE: un parámetro se da de baja con `activo=false` (sus datos capturados se conservan).
    """
    auditoria_categoria, auditoria_nombre = 'CATALOGO', 'parámetro de proceso'
    auditoria_excluir = ('usos_en_recetas', 'variables', 'tipo_dato_display', 'es_calculado')
    http_method_names = ['get', 'post', 'put', 'patch', 'head', 'options']
    serializer_class = ParametroProcesoSerializer
    permiso_escritura = 'gestionar_catalogos'
    permisos_por_accion = {'probar_formula': SOLO_SESION}

    def get_queryset(self):
        qs = ParametroProceso.objects.annotate(
            usos_en_recetas=Count('usos_en_secciones__seccion__operacion', distinct=True),
        ).order_by('nombre')
        params = self.request.query_params
        if params.get('q'):
            q = params['q'].strip()
            qs = qs.filter(Q(codigo__icontains=q) | Q(nombre__icontains=q))
        if params.get('activo') in ('true', 'false'):
            qs = qs.filter(activo=params['activo'] == 'true')
        return qs

    @action(detail=False, methods=['get'], url_path='opciones')
    def opciones(self, request):
        from .formulas import FUNCIONES
        return Response({
            'tipos': [{'valor': v, 'etiqueta': e} for v, e in ParametroProceso.TIPO_CHOICES],
            'funciones': list(FUNCIONES),
        })

    @action(detail=False, methods=['post'], url_path='probar-formula')
    def probar_formula(self, request):
        """Valida una fórmula y, si se mandan valores de prueba {codigo: número}, la calcula (no guarda nada)."""
        formula = request.data.get('formula') or ''
        try:
            usadas = validar_formula_parametro(formula, request.data.get('codigo') or '')
        except ErrorFormula as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        valores = {}
        for codigo, valor in (request.data.get('valores') or {}).items():
            try:
                valores[codigo] = float(str(valor).replace(',', '.'))
            except (TypeError, ValueError):
                continue
        resultado = evaluar(formula, valores) if all(c in valores for c in usadas) else None
        return Response({'variables': usadas, 'resultado': resultado})


def _avisos_eventos(eventos):
    """Avisos para quien captura: los eventos GMP que se abrieron por datos fuera de especificación."""
    return [f"📋 Se abrió el evento GMP {e.folio} ({e.titulo}) para que Calidad lo evalúe." for e in eventos]


def _actor(request):
    usuario, operador, nombre, _ = quien(request)
    return {'usuario': usuario, 'operador': operador, 'nombre': nombre}


def _momento(valor):
    """Hora de la toma enviada por el navegador ('2026-10-23T14:05' local o ISO con zona); None = ahora."""
    if not valor:
        return None
    try:
        momento = datetime.fromisoformat(str(valor).replace('Z', '+00:00'))
    except ValueError:
        raise ErrorCaptura("La hora de la toma no tiene un formato válido.")
    return timezone.make_aware(momento) if timezone.is_naive(momento) else momento


class CapturaViewSet(viewsets.ViewSet):
    """
    Captura de datos de proceso por fase de lote (la ruta usa el id de la fase):
      GET  /api/captura/<fase>/                 formulario: plan, edades, toma registrada y adicionales
      POST /api/captura/<fase>/vista-previa/    calcula y marca límites sin guardar
      POST /api/captura/<fase>/registrar/       toma del calendario (la fase debe estar en curso)
      POST /api/captura/<fase>/adicional/       muestra adicional en una incubación en curso (con motivo)
      POST /api/captura/<fase>/corregir/        corrige un valor (motivo + firma CORREGIR_DATO)
      GET  /api/captura/lote/?lote=<id>         datos vigentes del lote (tabla para gráficas)
    Capturan los roles con `ejecutar_fase` y el operador con PIN asignado a la tarea.
    """
    permission_classes = [PermisoCaptura]

    def _fase(self, pk):
        try:
            return FaseLote.objects.select_related('lote', 'operacion_maestra__etapa').get(pk=pk)
        except (FaseLote.DoesNotExist, ValueError):
            raise NotFound("La tarea no existe.")

    def _validar_quien_captura(self, request, fase):
        if request.user.is_authenticated:
            if not tiene_permiso(request.user, 'ejecutar_fase'):
                raise PermissionDenied("Tu rol no permite capturar datos de proceso.")
            return
        operador = operador_de_sesion(request)
        asignaciones = AsignacionFaseOperador.objects.filter(operador=operador, fase_lote__lote=fase.lote)
        if fase.es_subtarea_muestreo or not operacion_admite_adicional(fase):
            asignado = asignaciones.filter(fase_lote=fase).exists()
        else:
            # La incubación es pasiva (sin personal): basta con estar asignado a alguno de sus muestreos
            asignado = asignaciones.filter(fase_lote__operacion_maestra=fase.operacion_maestra).exists()
        if not asignado:
            raise PermissionDenied("Solo puedes capturar datos de tareas que tienes asignadas.")

    @staticmethod
    def _error(mensaje, estado=status.HTTP_400_BAD_REQUEST, **extra):
        return Response({'error': mensaje, **extra}, status=estado)

    @staticmethod
    def _cambios(filas):
        return {f['param']['codigo']: [None, texto_decimal(f['valor_numero']) if f['valor_numero'] is not None else f['valor_texto']]
                for f in filas if f['valor_numero'] is not None or f['valor_texto']}

    def retrieve(self, request, pk=None):
        return Response(detalle_captura(self._fase(pk)))

    @action(detail=True, methods=['post'], url_path='vista-previa')
    def vista_previa(self, request, pk=None):
        fase = self._fase(pk)
        if request.data.get('adicional'):
            plan = plan_de_operacion(fase.operacion_maestra, None) if operacion_admite_adicional(fase) else {}
            for s in plan.get('secciones', []):
                for p in s['parametros']:
                    p['obligatorio'] = False
        else:
            plan = fase.plan_captura or {}
        try:
            filas, faltantes = preparar_valores(plan, request.data.get('valores') or {})
        except ErrorCaptura as e:
            return self._error(str(e))
        return Response({
            'valores': [{'parametro': f['param']['parametro'], 'calculado': f['calculado'],
                         'valor': texto_decimal(f['valor_numero']) if f['valor_numero'] is not None else (f['valor_texto'] or None),
                         'fuera_especificacion': f['fuera_especificacion'], 'fuera_alerta': f['fuera_alerta']} for f in filas],
            'faltantes': faltantes, 'avisos': avisos_limites(filas),
        })

    @action(detail=True, methods=['post'], url_path='registrar')
    def registrar(self, request, pk=None):
        fase = self._fase(pk)
        self._validar_quien_captura(request, fase)
        try:
            toma, filas = registrar_toma(fase, request.data.get('valores') or {}, _actor(request), _momento(request.data.get('momento')))
        except ErrorCaptura as e:
            return self._error(str(e))
        avisos = avisos_limites(filas)
        cambios = self._cambios(filas)
        if avisos:
            cambios['fuera_de_limites'] = [None, avisos]
        registrar(request, 'DATOS_PROCESO', 'REGISTRAR_DATOS', f"Datos de proceso capturados: {nombre_fase(fase)} · lote {fase.lote.identificador_lote}",
                  objeto=toma, fase=fase, cambios=cambios)
        avisos += _avisos_eventos(eventos_fuera_especificacion(request, toma))
        return Response({**detalle_captura(fase), 'avisos': avisos}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='adicional')
    def adicional(self, request, pk=None):
        fase = self._fase(pk)
        self._validar_quien_captura(request, fase)
        try:
            toma, filas = registrar_toma_adicional(
                fase, request.data.get('valores') or {}, _actor(request), request.data.get('motivo'),
                _momento(request.data.get('momento')), request.data.get('codigo_muestra') or '')
        except ErrorCaptura as e:
            return self._error(str(e))
        avisos = avisos_limites(filas)
        cambios = self._cambios(filas)
        if avisos:
            cambios['fuera_de_limites'] = [None, avisos]
        registrar(request, 'DATOS_PROCESO', 'MUESTRA_ADICIONAL', f"Muestra adicional: {nombre_fase(fase)} · lote {fase.lote.identificador_lote}",
                  objeto=toma, fase=fase, cambios=cambios, motivo=toma.motivo)
        avisos += _avisos_eventos(eventos_fuera_especificacion(request, toma))
        return Response({**detalle_captura(fase), 'avisos': avisos}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='corregir')
    def corregir(self, request, pk=None):
        fase = self._fase(pk)
        self._validar_quien_captura(request, fase)
        try:
            toma = TomaDatos.objects.get(pk=request.data.get('toma'), fase=fase)
        except (TomaDatos.DoesNotExist, ValueError, TypeError):
            return self._error("La toma no pertenece a esta tarea.")
        motivo = (request.data.get('motivo') or '').strip()
        if len(motivo) < MOTIVO_MINIMO:
            # Antes de la firma, para no pedir la contraseña por algo que no es de ella
            return self._error(f"Escribe el motivo de la corrección (mínimo {MOTIVO_MINIMO} caracteres).", codigo='MOTIVO_REQUERIDO')
        try:
            firmante = verificar_firma(request, 'CORREGIR_DATO')
        except FirmaRechazada as e:
            return Response(e.como_respuesta(), status=e.estado_http)
        try:
            with transaction.atomic():
                cambios = corregir_valor(toma, request.data.get('parametro'), request.data.get('valor'), motivo, _actor(request))
                registro = registrar(request, 'DATOS_PROCESO', 'CORREGIR_DATO',
                                     f"Corrección de datos de proceso: {nombre_fase(fase)} · lote {fase.lote.identificador_lote}",
                                     objeto=toma, fase=fase, cambios=cambios, motivo=motivo)
                firmar(registro, firmante)
                # Si el valor corregido sigue (o queda) fuera de especificación, se abre su evento GMP
                creados = eventos_fuera_especificacion(request, toma)
        except (ErrorCaptura, ValueError, TypeError) as e:
            return self._error(str(e) or "Datos de corrección no válidos.")
        return Response({**detalle_captura(fase), 'avisos': _avisos_eventos(creados)})

    @action(detail=False, methods=['get'], url_path='lote')
    def lote(self, request):
        try:
            lote = LoteProduccion.objects.select_related('proceso_maestro').get(pk=request.query_params.get('lote'))
        except (LoteProduccion.DoesNotExist, ValueError, TypeError):
            raise NotFound("El lote no existe.")
        return Response(tabla_lote(lote))


class IndicadorProcesoViewSet(AuditoriaMixin, viewsets.ModelViewSet):
    """
    Indicadores de una receta (?proceso=<id>). Sin DELETE: se desactivan (`activo=false`).
    Se calculan por lote en /api/analisis-proceso/.
    """
    auditoria_categoria, auditoria_nombre = 'RECETA', 'indicador de proceso'
    auditoria_excluir = ('tipo_display', 'parametro_nombre', 'parametro_unidad', 'etapa_nombre')
    http_method_names = ['get', 'post', 'put', 'patch', 'head', 'options']
    serializer_class = IndicadorProcesoSerializer
    permiso_escritura = 'editar_receta'

    def get_queryset(self):
        qs = IndicadorProceso.objects.select_related('parametro', 'etapa', 'proceso')
        proceso = self.request.query_params.get('proceso')
        if proceso:
            qs = qs.filter(proceso_id=proceso)
        return qs


class AnalisisProcesoViewSet(viewsets.ViewSet):
    """
    Gráficas de proceso (solo lectura):
      GET /api/analisis-proceso/?proceso=<id>&lotes=1,2,3[&etapa=<id>][&completos=1,2]
          series por parámetro, curvas e indicadores; con muchos lotes, los que no están en `completos` van reducidos
      GET /api/analisis-proceso/lotes/?proceso=<id>                       lotes de la receta con cuántas tomas tienen
      GET /api/analisis-proceso/recetas/                                  plantillas con etapas, actividades y lotes
    """

    def _proceso(self, request):
        try:
            return ProcesoMaestro.objects.get(pk=int(request.query_params.get('proceso', '')))
        except (ValueError, ProcesoMaestro.DoesNotExist):
            raise NotFound("Elige una receta.")

    def list(self, request):
        proceso = self._proceso(request)
        try:
            ids = [int(x) for x in request.query_params.get('lotes', '').split(',') if x.strip()]
            etapa = int(request.query_params['etapa']) if request.query_params.get('etapa') else None
            completos = [int(x) for x in request.query_params.get('completos', '').split(',') if x.strip()]
        except ValueError:
            return Response({'error': "Lotes o etapa no válidos."}, status=status.HTTP_400_BAD_REQUEST)
        ids = list(dict.fromkeys(ids))
        if len(ids) > MAX_LOTES_ANALISIS:
            return Response({'error': f"Elige hasta {MAX_LOTES_ANALISIS} lotes a la vez."}, status=status.HTTP_400_BAD_REQUEST)
        if etapa and not proceso.etapas.filter(pk=etapa).exists():
            return Response({'error': "La etapa no es de esta receta."}, status=status.HTTP_400_BAD_REQUEST)
        lotes = {l.id: l for l in LoteProduccion.objects.filter(proceso_maestro=proceso, pk__in=ids)}
        return Response(analisis_lotes(proceso, [lotes[i] for i in ids if i in lotes], etapa, completos))

    @action(detail=False, methods=['get'])
    def recetas(self, request):
        """Plantillas (recetas) para la barra lateral: etapas, actividades y lotes con datos de cada una."""
        qs = (ProcesoMaestro.objects.annotate(
                  n_etapas=Count('etapas', distinct=True), n_actividades=Count('operaciones', distinct=True),
                  n_lotes=Count('lotes_instanciados', distinct=True),
                  n_con_datos=Count('lotes_instanciados', filter=Q(lotes_instanciados__fases__tomas_datos__isnull=False), distinct=True))
              .order_by('-activo', 'nombre'))
        return Response([{'id': p.id, 'nombre': p.nombre, 'activo': p.activo, 'etapas': p.n_etapas, 'actividades': p.n_actividades,
                          'lotes': p.n_lotes, 'lotes_con_datos': p.n_con_datos} for p in qs])

    @action(detail=False, methods=['get'])
    def lotes(self, request):
        proceso = self._proceso(request)
        qs = (LoteProduccion.objects.filter(proceso_maestro=proceso)
              .annotate(tomas=Count('fases__tomas_datos', distinct=True)).order_by('-id'))
        return Response({
            'proceso': {'id': proceso.id, 'nombre': proceso.nombre},
            'etapas': [{'id': e.id, 'nombre': e.nombre} for e in proceso.etapas.order_by('orden', 'id')],
            'max_lotes': MAX_LOTES_ANALISIS,
            'lotes': [{'id': l.id, 'identificador': l.identificador_lote, 'estado': l.estado,
                       'estado_display': l.get_estado_display(), 'archivado': l.archivado, 'tomas': l.tomas,
                       'inicio': l.fecha_inicio_planeada} for l in qs],
        })


def _descarga(contenido, tipo, nombre):
    from django.http import HttpResponse
    respuesta = HttpResponse(contenido, content_type=tipo)
    respuesta['Content-Disposition'] = f'attachment; filename="{nombre}"'
    return respuesta


def _nombre_archivo(*partes):
    import re
    texto = '_'.join(str(p) for p in partes if p)
    return re.sub(r'[^A-Za-z0-9._-]+', '-', texto)


TIPO_PDF = 'application/pdf'
TIPO_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class InformeProcesoViewSet(viewsets.ViewSet):
    """
    Informes de datos de proceso (solo lectura; cada emisión queda en la bitácora):
      GET /api/informes-proceso/<lote>/pdf/[?etapa=<id>]     informe del lote o de una etapa en PDF
          &combinar=<etapa>-<parámetro>,…&vista=apiladas|superpuestas   sección de gráficas combinadas (opcional)
      GET /api/informes-proceso/<lote>/excel/[?etapa=<id>]   el mismo informe en Excel
      GET /api/informes-proceso/lotes/?proceso=&lotes=1,2[&etapa=]   Excel de varios lotes (hasta 200)
    """

    def _lote_y_etapa(self, request, pk):
        try:
            lote = LoteProduccion.objects.select_related('proceso_maestro').get(pk=pk)
        except (LoteProduccion.DoesNotExist, ValueError):
            raise NotFound("El lote no existe.")
        etapa = request.query_params.get('etapa') or None
        if etapa:
            try:
                etapa = int(etapa)
            except ValueError:
                raise NotFound("Etapa no válida.")
            if not lote.proceso_maestro.etapas.filter(pk=etapa).exists():
                raise NotFound("La etapa no es de la receta del lote.")
        return lote, etapa

    def _emitir(self, request, pk, formato):
        from . import informes
        lote, etapa = self._lote_y_etapa(request, pk)
        combinar = [c for c in (request.query_params.get('combinar') or '').split(',') if c.strip()]
        datos = datos_informe(lote, etapa, combinar=combinar, vista=request.query_params.get('vista') or 'apiladas')
        emisor = quien(request)[2]
        if formato == 'PDF':
            contenido, tipo, extension = informes.pdf_lote(datos, emisor), TIPO_PDF, 'pdf'
        else:
            contenido, tipo, extension = informes.excel_lote(datos, emisor), TIPO_XLSX, 'xlsx'
        registrar(request, 'DATOS_PROCESO', 'GENERAR_INFORME',
                  f"Informe de datos de proceso ({formato}) del lote {lote.identificador_lote}"
                  + (f", etapa {datos['etapa']}" if datos['etapa'] else ''),
                  objeto=lote, lote=lote, cambios={'formato': [None, formato], 'huella': [None, datos['huella']],
                                                   'tomas': [None, len(datos['tomas'])],
                                                   'combinadas': [None, ', '.join(c['columna']['codigo'] for c in datos['combinadas'])]})
        nombre = _nombre_archivo('Informe', lote.identificador_lote, datos['etapa'],
                                 timezone.localtime(datos['generado']).strftime('%Y%m%d-%H%M')) + f'.{extension}'
        return _descarga(contenido, tipo, nombre)

    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        return self._emitir(request, pk, 'PDF')

    @action(detail=True, methods=['get'])
    def excel(self, request, pk=None):
        return self._emitir(request, pk, 'EXCEL')

    @action(detail=False, methods=['get'])
    def lotes(self, request):
        from . import informes
        try:
            proceso = ProcesoMaestro.objects.get(pk=int(request.query_params.get('proceso', '')))
            ids = list(dict.fromkeys(int(x) for x in request.query_params.get('lotes', '').split(',') if x.strip()))
            etapa = int(request.query_params['etapa']) if request.query_params.get('etapa') else None
            completos = [int(x) for x in request.query_params.get('completos', '').split(',') if x.strip()]
        except (ValueError, ProcesoMaestro.DoesNotExist):
            return Response({'error': "Receta, lotes o etapa no válidos."}, status=status.HTTP_400_BAD_REQUEST)
        if not ids or len(ids) > MAX_LOTES_ANALISIS:
            return Response({'error': f"Elige entre 1 y {MAX_LOTES_ANALISIS} lotes."}, status=status.HTTP_400_BAD_REQUEST)
        etapa_obj = proceso.etapas.filter(pk=etapa).first() if etapa else None
        if etapa and not etapa_obj:
            return Response({'error': "La etapa no es de esta receta."}, status=status.HTTP_400_BAD_REQUEST)
        por_id = {l.id: l for l in LoteProduccion.objects.filter(proceso_maestro=proceso, pk__in=ids).select_related('proceso_maestro')}
        lotes = [por_id[i] for i in ids if i in por_id]
        filas, indicadores_por_lote, indicadores = filas_lotes_excel(lotes, etapa)
        emisor = quien(request)[2]
        contenido = informes.excel_lotes(proceso, etapa_obj.nombre if etapa_obj else None, filas, indicadores_por_lote,
                                         indicadores, lotes, emisor)
        registrar(request, 'DATOS_PROCESO', 'GENERAR_INFORME',
                  f"Excel de datos de proceso de {len(lotes)} lotes de la receta {proceso.nombre}"
                  + (f", etapa {etapa_obj.nombre}" if etapa_obj else ''),
                  objeto=proceso, cambios={'formato': [None, 'EXCEL'], 'lotes': [None, ', '.join(l.identificador_lote for l in lotes)[:2000]]})
        nombre = _nombre_archivo('Datos', proceso.nombre, etapa_obj.nombre if etapa_obj else None, f'{len(lotes)}-lotes',
                                 timezone.localtime().strftime('%Y%m%d-%H%M')) + '.xlsx'
        return _descarga(contenido, TIPO_XLSX, nombre)
