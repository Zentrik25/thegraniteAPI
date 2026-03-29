from django.urls import path

from .views import RedirectDetailView, RedirectListView

app_name = "redirects"

urlpatterns = [
    path(
        "redirects/",
        RedirectListView.as_view(),
        name="redirect-list",
    ),
    path(
        "redirects/<int:pk>/",
        RedirectDetailView.as_view(),
        name="redirect-detail",
    ),
]