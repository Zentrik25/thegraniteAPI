import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardResultsPagination
from users.permissions import IsEditorOrAbove

from .models import Notification, PushSubscription
from .serializers import (
    NotificationSerializer,
    PushSubscribeSerializer,
    PushSubscriptionSerializer,
)

logger = logging.getLogger("notifications.views")


class VapidPublicKeyView(APIView):
    """
    GET /api/v1/notifications/vapid-public-key/

    Returns the VAPID public key needed by the browser to
    subscribe to push notifications.

    The frontend calls this endpoint to get the key before
    calling pushManager.subscribe().
    """

    permission_classes = [AllowAny]

    def get(self, request):
        import os
        public_key = os.environ.get("VAPID_PUBLIC_KEY", "")

        if not public_key:
            return Response(
                {"detail": "Push notifications are not configured on this server."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({"vapid_public_key": public_key})


class PushSubscribeView(APIView):
    """
    POST /api/v1/notifications/subscribe/

    Register a browser push subscription.
    Called by the frontend after the reader grants notification permission.

    The browser provides the endpoint, p256dh, and auth values
    from the PushSubscription object.

    If the endpoint already exists the subscription is updated
    (reactivated if it was deactivated).
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PushSubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        subscription, created = PushSubscription.objects.update_or_create(
            endpoint = serializer.validated_data["endpoint"],
            defaults = {
                "p256dh":     serializer.validated_data["p256dh"],
                "auth":       serializer.validated_data["auth"],
                "user_agent": serializer.validated_data.get("user_agent", ""),
                "is_active":  True,
            },
        )

        action = "created" if created else "reactivated"
        logger.info(
            "Push subscription %s: id=%s",
            action,
            subscription.pk,
        )

        return Response(
            PushSubscriptionSerializer(subscription).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PushUnsubscribeView(APIView):
    """
    POST /api/v1/notifications/unsubscribe/

    Deactivate a push subscription by endpoint URL.
    Called when the reader turns off notifications in the browser.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        endpoint = request.data.get("endpoint", "").strip()

        if not endpoint:
            return Response(
                {"detail": "Endpoint is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        updated = PushSubscription.objects.filter(
            endpoint=endpoint
        ).update(is_active=False)

        if updated:
            logger.info("Push subscription deactivated: endpoint=%s...", endpoint[:50])

        return Response(
            {"detail": "Unsubscribed successfully."},
            status=status.HTTP_200_OK,
        )


class NotificationListView(APIView):
    """
    GET /api/v1/notifications/history/

    History of all notifications sent. Editor and above only.
    Useful for knowing what breaking news was pushed and to how many readers.
    """

    permission_classes = [IsAuthenticated, IsEditorOrAbove]
    pagination_class   = StandardResultsPagination

    def get(self, request):
        notifications = Notification.objects.select_related("article").order_by(
            "-sent_at"
        )
        paginator  = self.pagination_class()
        page       = paginator.paginate_queryset(notifications, request)
        serializer = NotificationSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class SendTestNotificationView(APIView):
    """
    POST /api/v1/notifications/test/

    Send a test push notification to all active subscriptions.
    Admin only. Used to verify push notifications are working.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != "admin" and not request.user.is_superuser:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only admins can send test notifications.")

        from .tasks import send_test_push
        send_test_push.apply_async(queue="slow")

        return Response(
            {"detail": "Test notification queued for all active subscribers."},
            status=status.HTTP_202_ACCEPTED,
        )