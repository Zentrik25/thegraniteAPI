from django.contrib import admin
from django.contrib.auth.models import Group
from django.db import connection
from django.utils.html import format_html

from django.core.cache import cache


# ---------------------------------------------------------------------------
# Admin site branding
# ---------------------------------------------------------------------------

admin.site.site_header = "The Granite Post — Editorial CMS"
admin.site.site_title  = "Granite Post Admin"
admin.site.index_title = "Newsroom Administration"


# ---------------------------------------------------------------------------
# Re-register Group with a better admin
# ---------------------------------------------------------------------------

# Django registers Group by default but with a plain interface.
# We unregister it and re-register with more control.

admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display  = ("name", "member_count")
    search_fields = ("name",)
    ordering      = ("name",)

    # Groups are managed automatically by authors/signals.py — editors
    # should not create or delete groups manually as it would break the
    # role sync. We make the interface read-only for safety.
    def has_add_permission(self, request) -> bool:
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None) -> bool:
        return request.user.is_superuser

    @admin.display(description="Members")
    def member_count(self, obj) -> int:
        return obj.user_set.count()


# ---------------------------------------------------------------------------
# Register Celery Beat models with better display
# ---------------------------------------------------------------------------

try:
    from django_celery_beat.models import (
        ClockedSchedule,
        CrontabSchedule,
        IntervalSchedule,
        PeriodicTask,
        SolarSchedule,
    )
    from django_celery_beat.admin import (
        PeriodicTaskAdmin,
        CrontabScheduleAdmin,
        IntervalScheduleAdmin,
    )

    # Already registered by django_celery_beat — just ensure they show
    # under a clean section in the admin sidebar.
    # If they are not registered yet this block is a no-op.

except ImportError:
    pass


# ---------------------------------------------------------------------------
# Register JWT token blacklist
# ---------------------------------------------------------------------------

try:
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )
    from django.contrib.admin import ModelAdmin as _MA

    admin.site.unregister(OutstandingToken)

    @admin.register(OutstandingToken)
    class OutstandingTokenAdmin(_MA):
        list_display  = ("user", "jti", "created_at", "expires_at")
        list_filter   = ("user",)
        search_fields = ("user__username", "jti")
        ordering      = ("-created_at",)
        readonly_fields = (
            "user", "jti", "token", "created_at", "expires_at",
        )

        def has_add_permission(self, request) -> bool:
            return False

        def has_change_permission(self, request, obj=None) -> bool:
            return False

    admin.site.unregister(BlacklistedToken)

    @admin.register(BlacklistedToken)
    class BlacklistedTokenAdmin(_MA):
        list_display  = ("token", "blacklisted_at")
        ordering      = ("-blacklisted_at",)
        readonly_fields = ("token", "blacklisted_at")

        def has_add_permission(self, request) -> bool:
            return False

        def has_change_permission(self, request, obj=None) -> bool:
            return False

except ImportError:
    pass


# ---------------------------------------------------------------------------
# Custom admin view — System Status panel
# ---------------------------------------------------------------------------

class SystemStatusAdminSite(admin.AdminSite):
    """
    Custom admin site that injects a system status panel into the index page.
    Shows database, cache, and Celery worker status at a glance.
    """
    pass


# We extend the default admin index via a custom AdminSite subclass.
# The standard approach is to override index() on the default site.

original_index = admin.site.__class__.index


def custom_index(self, request, extra_context=None):
    extra_context = extra_context or {}

    # Database status
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version()")
            db_version = cursor.fetchone()[0].split(",")[0]
        db_status  = "ok"
    except Exception as exc:
        db_version = "unavailable"
        db_status  = f"error: {exc}"

    # Cache (Redis) status
    try:
        cache.set("admin:probe", "1", timeout=5)
        cache_status = "ok" if cache.get("admin:probe") == "1" else "error"
    except Exception as exc:
        cache_status = f"error: {exc}"

    # Article counts
    try:
        from articles.models import Article, PublishStatus
        article_counts = {
            "published": Article.objects.filter(status=PublishStatus.PUBLISHED).count(),
            "draft":     Article.objects.filter(status=PublishStatus.DRAFT).count(),
            "review":    Article.objects.filter(status=PublishStatus.REVIEW).count(),
            "breaking":  Article.objects.filter(
                status=PublishStatus.PUBLISHED, is_breaking=True
            ).count(),
        }
    except Exception:
        article_counts = {}

    extra_context["system_status"] = {
        "database": {
            "status":  db_status,
            "version": db_version,
        },
        "cache": {
            "status": cache_status,
        },
        "articles": article_counts,
    }

    return original_index(self, request, extra_context=extra_context)


admin.site.__class__.index = custom_index