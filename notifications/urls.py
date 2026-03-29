from django.urls import path

from .views import (
    NotificationListView,
    PushSubscribeView,
    PushUnsubscribeView,
    SendTestNotificationView,
    VapidPublicKeyView,
)

app_name = "notifications"

urlpatterns = [
    path(
        "notifications/vapid-public-key/",
        VapidPublicKeyView.as_view(),
        name="vapid-public-key",
    ),
    path(
        "notifications/subscribe/",
        PushSubscribeView.as_view(),
        name="subscribe",
    ),
    path(
        "notifications/unsubscribe/",
        PushUnsubscribeView.as_view(),
        name="unsubscribe",
    ),
    path(
        "notifications/history/",
        NotificationListView.as_view(),
        name="notification-history",
    ),
    path(
        "notifications/test/",
        SendTestNotificationView.as_view(),
        name="send-test",
    ),
]