from django.contrib import admin
from django.db.models import Count
from django.utils import timezone
from datetime import timedelta

from .models import ArticleView


@admin.register(ArticleView)
class ArticleViewAdmin(admin.ModelAdmin):
    list_display  = ("article", "viewed_date", "viewed_at")
    list_filter   = ("viewed_date",)
    search_fields = ("article__title",)
    ordering      = ("-viewed_at",)
    readonly_fields = (
        "article", "ip_hash", "session_hash",
        "viewed_at", "viewed_date",
    )
    date_hierarchy = "viewed_at"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return request.user.is_superuser

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("article")
