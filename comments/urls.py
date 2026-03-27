from django.urls import path

from .views import ArticleCommentsView, ModerationActionView, ModerationListView

app_name = "comments"

urlpatterns = [
    # Public — read approved comments and submit new ones
    path(
        "articles/<slug:slug>/comments/",
        ArticleCommentsView.as_view(),
        name="article-comments",
    ),

    # Moderation queue — Moderator or above only
    path(
        "moderation/comments/",
        ModerationListView.as_view(),
        name="moderation-list",
    ),
    path(
        "moderation/comments/<int:pk>/",
        ModerationActionView.as_view(),
        name="moderation-action",
    ),
]
