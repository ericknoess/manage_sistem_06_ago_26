# roster/urls.py

from django.urls import path
from .views import RosterDashboardView

urlpatterns = [
    path('', RosterDashboardView.as_view(), name='roster_dashboard'),
]