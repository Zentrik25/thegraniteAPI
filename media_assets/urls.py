from django.urls import path

from .views import MediaDetailView, MediaUploadView

app_name = "media_assets"

urlpatterns = [
    path("media/",       MediaUploadView.as_view(), name="media-list"),
    path("media/<int:pk>/", MediaDetailView.as_view(), name="media-detail"),
]
