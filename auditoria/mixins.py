# auditoria/mixins.py

from .services import diferencias, registrar


class AuditoriaMixin:
    """
    Para ModelViewSets: registra en la bitácora cada alta, cambio y baja hecha por la API,
    con los valores antes y después tomados del serializer.

        class EquipoViewSet(AuditoriaMixin, viewsets.ModelViewSet):
            auditoria_categoria = 'CATALOGO'
            auditoria_nombre = 'equipo'          # cómo se nombra en la descripción
    """
    auditoria_categoria = 'CATALOGO'
    auditoria_nombre = 'registro'
    auditoria_campos = None      # si se indica, solo estos campos del serializer se comparan
    auditoria_excluir = ()       # campos del serializer que no se guardan (ej. listas anidadas grandes)

    def _auditoria_contexto(self, instancia):
        """Lote y fase relacionados (para el historial del lote). Las vistas lo pueden sobrescribir."""
        return {}

    def _auditoria_datos(self, instancia):
        datos = dict(self.get_serializer(instancia).data)
        if self.auditoria_campos is not None:
            datos = {k: v for k, v in datos.items() if k in self.auditoria_campos}
        return {k: v for k, v in datos.items() if k not in self.auditoria_excluir}

    def perform_create(self, serializer):
        super().perform_create(serializer)
        instancia = serializer.instance
        registrar(
            self.request, self.auditoria_categoria, 'CREAR', f"Alta de {self.auditoria_nombre}: {instancia}",
            objeto=instancia, cambios=diferencias(None, self._auditoria_datos(instancia)),
            **self._auditoria_contexto(instancia),
        )

    def perform_update(self, serializer):
        antes = self._auditoria_datos(serializer.instance)
        super().perform_update(serializer)
        instancia = serializer.instance
        cambios = diferencias(antes, self._auditoria_datos(instancia))
        if cambios:
            registrar(
                self.request, self.auditoria_categoria, 'EDITAR', f"Cambio en {self.auditoria_nombre}: {instancia}",
                objeto=instancia, cambios=cambios, **self._auditoria_contexto(instancia),
            )

    def perform_destroy(self, instancia):
        antes = self._auditoria_datos(instancia)
        descripcion = f"Baja de {self.auditoria_nombre}: {instancia}"
        contexto = self._auditoria_contexto(instancia)
        objeto_tipo, objeto_id = instancia._meta.model_name, str(instancia.pk)
        super().perform_destroy(instancia)
        registrar(
            self.request, self.auditoria_categoria, 'ELIMINAR', descripcion,
            objeto_tipo=objeto_tipo, objeto_id=objeto_id, cambios=diferencias(antes, None), **contexto,
        )
