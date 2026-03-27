from django.urls import path

from core.jwt import GraniteTokenObtainPairView
from .views import APIRootView, HealthCheckView

app_name = "core"

urlpatterns = [
    path("health/",         HealthCheckView.as_view(),          name="health"),
    path("api/v1/",         APIRootView.as_view(),              name="api-root"),
    path("api/auth/login/", GraniteTokenObtainPairView.as_view(), name="token-login"),
]
