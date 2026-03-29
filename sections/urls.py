from django.urls import path

from .views import SectionArticlesView, SectionDetailView, SectionListView

app_name = "sections"

urlpatterns = [
    path(
        "sections/",
        SectionListView.as_view(),
        name="section-list",
    ),
    path(
        "sections/<slug:slug>/",
        SectionDetailView.as_view(),
        name="section-detail",
    ),
    path(
        "sections/<slug:slug>/articles/",
        SectionArticlesView.as_view(),
        name="section-articles",
    ),
]