from django.urls import path

from .views import AuditLogListView, AuditLogObjectView

app_name = "audit"

urlpatterns = [
    path(
        "audit/",
        AuditLogListView.as_view(),
        name="audit-list",
    ),
    path(
        "audit/<str:content_type_name>/<str:object_id>/",
        AuditLogObjectView.as_view(),
        name="audit-object",
    ),
]