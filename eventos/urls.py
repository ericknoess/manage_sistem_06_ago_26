# eventos/urls.py

from django.urls import include, path
from django.views.generic import TemplateView
from rest_framework.routers import DefaultRouter

from .views import EventoGMPViewSet

router = DefaultRouter()
router.register(r'eventos', EventoGMPViewSet, basename='eventos-gmp')

urlpatterns = [
    path('eventos/', TemplateView.as_view(template_name='eventos/eventos.html'), name='eventos-gmp'),
    path('api/', include(router.urls)),
]
