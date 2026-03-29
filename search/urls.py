from django.urls import path

from .views import ArticleSearchView

app_name = "search"

urlpatterns = [
    path("search/", ArticleSearchView.as_view(), name="article-search"),
]
