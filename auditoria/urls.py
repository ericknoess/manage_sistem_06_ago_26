# auditoria/urls.py

from django.urls import include, path
from django.views.generic import TemplateView
from rest_framework.routers import DefaultRouter

from .views import RegistroAuditoriaViewSet

router = DefaultRouter()
router.register(r'auditoria', RegistroAuditoriaViewSet, basename='auditoria')

urlpatterns = [
    path('auditoria/', TemplateView.as_view(template_name='auditoria/bitacora.html'), name='bitacora-auditoria'),
    path('api/', include(router.urls)),
]
