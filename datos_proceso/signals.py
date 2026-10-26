# datos_proceso/signals.py — Las series preparadas (SeriesLote) se borran en cuanto cambia algo de su lote.

from django.db.models.signals import post_save
from django.dispatch import receiver

from procesos.models import FaseLote, LoteProduccion
from .models import SeriesLote, TomaDatos, ValorParametro


def invalidar_series(lote_ids):
    """Borra las series preparadas de esos lotes (se regeneran al graficar). Llamarla tras escrituras masivas."""
    ids = [i for i in (lote_ids if isinstance(lote_ids, (list, set, tuple)) else [lote_ids]) if i]
    if ids:
        SeriesLote.objects.filter(lote_id__in=ids).delete()


@receiver(post_save, sender=LoteProduccion)
def _lote(sender, instance, **kwargs):
    invalidar_series(instance.pk)


@receiver(post_save, sender=FaseLote)
def _fase(sender, instance, **kwargs):
    invalidar_series(instance.lote_id)


@receiver(post_save, sender=TomaDatos)
def _toma(sender, instance, **kwargs):
    invalidar_series(FaseLote.objects.filter(pk=instance.fase_id).values_list('lote_id', flat=True).first())


@receiver(post_save, sender=ValorParametro)
def _valor(sender, instance, **kwargs):
    invalidar_series(TomaDatos.objects.filter(pk=instance.toma_id).values_list('fase__lote_id', flat=True).first())
