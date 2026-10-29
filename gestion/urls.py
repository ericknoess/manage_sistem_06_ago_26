# gestion/urls.py — Proyectos, tareas de oficina y tableros Kanban (no GMP)

from django.urls import include, path
from django.views.generic import TemplateView
from rest_framework.routers import DefaultRouter

from .views import (ChecklistViewSet, ColumnaViewSet, DependenciaViewSet, EtiquetaViewSet, ProyectoPaginaView, ProyectoViewSet,
                    TareaViewSet)

router = DefaultRouter()
router.register(r'gestion/proyectos', ProyectoViewSet, basename='gestion-proyecto')
router.register(r'gestion/tareas', TareaViewSet, basename='gestion-tarea')
router.register(r'gestion/columnas', ColumnaViewSet, basename='gestion-columna')
router.register(r'gestion/etiquetas', EtiquetaViewSet, basename='gestion-etiqueta')
router.register(r'gestion/dependencias', DependenciaViewSet, basename='gestion-dependencia')
router.register(r'gestion/checklist', ChecklistViewSet, basename='gestion-checklist')

urlpatterns = [
    path('proyectos/', TemplateView.as_view(template_name='gestion/proyectos.html'), name='gestion-proyectos'),
    path('proyectos/<int:pk>/', ProyectoPaginaView.as_view(), name='gestion-proyecto'),
    path('api/', include(router.urls)),
]
