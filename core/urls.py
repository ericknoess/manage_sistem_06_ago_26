from django.contrib import admin
from django.urls import path, include


# core/urls.py
urlpatterns = [
    path('admin/', admin.site.urls),
    path('roster/', include('roster.urls')),
]