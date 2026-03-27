from django.urls import path

from .views import RecordViewView, TrendingArticlesView

app_name = "analytics"

urlpatterns = [
    path(
        "analytics/articles/<slug:slug>/view/",
        RecordViewView.as_view(),
        name="record-view",
    ),
    path(
        "analytics/trending/",
        TrendingArticlesView.as_view(),
        name="trending",
    ),
]
