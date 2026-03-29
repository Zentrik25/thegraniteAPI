"""
urls.py — URL routing for the subscriptions app.

All patterns are mounted under /api/v1/ in config/urls.py.

Route map (relative to /api/v1/):
  GET  subscriptions/plans/                      — public plan listing
  GET  subscriptions/my-subscription/            — reader's current subscription
  POST subscriptions/subscribe/                  — start subscription + Paynow payment
  POST subscriptions/cancel/                     — cancel subscription
  GET  subscriptions/payments/                   — payment history
  POST subscriptions/paynow-callback/            — Paynow result URL webhook
  GET  subscriptions/paynow-poll/<payment-id>/   — frontend payment status poll
  GET  subscriptions/all/                        — staff: all subscriptions
  GET  subscriptions/revenue/                    — staff: USD revenue report
"""

from django.urls import path

from .views import (
    AllSubscriptionsView,
    CancelSubscriptionView,
    MySubscriptionView,
    PaymentHistoryView,
    PaynowCallbackView,
    PaynowPollView,
    PlanListView,
    RevenueReportView,
    SubscribeView,
)

app_name = "subscriptions"

urlpatterns = [
    # Public
    path(
        "subscriptions/plans/",
        PlanListView.as_view(),
        name="plan-list",
    ),

    # Reader
    path(
        "subscriptions/my-subscription/",
        MySubscriptionView.as_view(),
        name="my-subscription",
    ),
    path(
        "subscriptions/subscribe/",
        SubscribeView.as_view(),
        name="subscribe",
    ),
    path(
        "subscriptions/cancel/",
        CancelSubscriptionView.as_view(),
        name="cancel",
    ),
    path(
        "subscriptions/payments/",
        PaymentHistoryView.as_view(),
        name="payment-history",
    ),

    # Paynow
    path(
        "subscriptions/paynow-callback/",
        PaynowCallbackView.as_view(),
        name="paynow-callback",
    ),
    path(
        "subscriptions/paynow-poll/<uuid:payment_id>/",
        PaynowPollView.as_view(),
        name="paynow-poll",
    ),

    # Staff
    path(
        "subscriptions/all/",
        AllSubscriptionsView.as_view(),
        name="all-subscriptions",
    ),
    path(
        "subscriptions/revenue/",
        RevenueReportView.as_view(),
        name="revenue-report",
    ),
]
