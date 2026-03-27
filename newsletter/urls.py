from django.urls import path

from .views import (
    ConfirmView,
    SubscribeView,
    SubscriberListView,
    UnsubscribeView,
)

app_name = "newsletter"

urlpatterns = [
    path("newsletter/subscribe/",    SubscribeView.as_view(),      name="subscribe"),
    path("newsletter/confirm/",      ConfirmView.as_view(),         name="confirm"),
    path("newsletter/unsubscribe/",  UnsubscribeView.as_view(),     name="unsubscribe"),
    path("newsletter/subscribers/",  SubscriberListView.as_view(),  name="subscriber-list"),
]
