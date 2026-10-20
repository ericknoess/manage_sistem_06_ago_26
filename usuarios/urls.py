# usuarios/urls.py

from django.urls import path

from .views import LoginView, LogoutView, SesionAPIView

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('api/sesion/', SesionAPIView.as_view(), name='api-sesion'),
]
