import logging

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardResultsPagination
from users.permissions import IsSeniorEditorOrAbove

from .models import Subscriber
from .serializers import (
    SubscribeSerializer,
    SubscriberSerializer,
    UnsubscribeSerializer,
)
from .throttling import SubscribeRateThrottle

logger = logging.getLogger("newsletter.views")


class SubscribeView(APIView):
    """
    POST /api/v1/newsletter/subscribe/

    Step 1 of double opt-in. Creates an unconfirmed subscriber record
    and queues a confirmation email.

    Returns 202 whether the email already exists or not — this prevents
    email enumeration attacks where an attacker could probe which emails
    are subscribed by checking the response.
    """

    permission_classes = [AllowAny]
    throttle_classes   = [SubscribeRateThrottle]

    def post(self, request):
        serializer = SubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email  = serializer.validated_data["email"]
        source = serializer.validated_data.get("source", "")

        subscriber, created = Subscriber.objects.get_or_create(
            email    = email,
            defaults = {"source": source},
        )

        if created:
            # Queue confirmation email.
            from .tasks import send_confirmation_email
            send_confirmation_email.apply_async(
                args=[subscriber.pk],
                queue="slow",
            )
            logger.info(
                "New subscriber: email=%s source=%s",
                email,
                source,
            )
        elif subscriber.confirmed:
            # Already confirmed — silently return 202.
            logger.debug("Subscribe attempt for already confirmed email: %s", email)
        else:
            # Unconfirmed — resend confirmation.
            from .tasks import send_confirmation_email
            send_confirmation_email.apply_async(
                args=[subscriber.pk],
                queue="slow",
            )
            logger.info("Resent confirmation email to: %s", email)

        return Response(
            {
                "detail": (
                    "Thank you for subscribing. "
                    "Please check your email for a confirmation link."
                ),
            },
            status=status.HTTP_202_ACCEPTED,
        )


class ConfirmView(APIView):
    """
    GET /api/v1/newsletter/confirm/?token=<uuid>

    Step 2 of double opt-in. Confirms the subscriber's email address.
    Called when the reader clicks the link in their confirmation email.
    """

    permission_classes = [AllowAny]
    throttle_classes   = []

    def get(self, request):
        token = request.query_params.get("token", "")

        if not token:
            return Response(
                {"detail": "Confirmation token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            subscriber = Subscriber.objects.get(confirmation_token=token)
        except (Subscriber.DoesNotExist, ValueError):
            return Response(
                {"detail": "Invalid or expired confirmation token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if subscriber.confirmed:
            return Response(
                {"detail": "Your email address is already confirmed."},
                status=status.HTTP_200_OK,
            )

        subscriber.confirm()

        # Queue welcome email.
        from .tasks import send_welcome_email
        send_welcome_email.apply_async(
            args=[subscriber.pk],
            queue="slow",
        )

        logger.info("Subscriber confirmed: email=%s", subscriber.email)

        return Response(
            {
                "detail": (
                    "Your email address has been confirmed. "
                    "Welcome to The Granite Post newsletter."
                ),
            },
            status=status.HTTP_200_OK,
        )


class UnsubscribeView(APIView):
    """
    POST /api/v1/newsletter/unsubscribe/

    Unsubscribes a reader using their unsubscribe token.
    The token is included in every newsletter email footer.
    No login required — anyone with the token can unsubscribe.

    Returns 200 whether the token is valid or not to prevent
    token enumeration attacks.
    """

    permission_classes = [AllowAny]
    throttle_classes   = []

    def post(self, request):
        serializer = UnsubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data["token"]

        try:
            subscriber = Subscriber.objects.get(unsubscribe_token=token)
            email      = subscriber.email
            subscriber.unsubscribe()
            logger.info("Subscriber unsubscribed: email=%s", email)
        except Subscriber.DoesNotExist:
            # Return 200 regardless — prevents token enumeration.
            pass

        return Response(
            {
                "detail": (
                    "You have been successfully unsubscribed from "
                    "The Granite Post newsletter."
                ),
            },
            status=status.HTTP_200_OK,
        )


class SubscriberListView(generics.ListAPIView):
    """
    GET /api/v1/newsletter/subscribers/

    Full subscriber list. Senior Editors and above only.
    Subscriber emails are personal data — not every staff member
    should have access to this list.

    ?confirmed=true  — confirmed subscribers only (default)
    ?confirmed=false — unconfirmed subscribers
    ?confirmed=all   — all subscribers
    """

    serializer_class   = SubscriberSerializer
    permission_classes = [IsAuthenticated, IsSeniorEditorOrAbove]
    pagination_class   = StandardResultsPagination

    def get_queryset(self):
        confirmed_param = self.request.query_params.get("confirmed", "true")

        if confirmed_param == "false":
            return Subscriber.objects.filter(confirmed=False)
        elif confirmed_param == "all":
            return Subscriber.objects.all()
        else:
            return Subscriber.objects.filter(confirmed=True)

    def list(self, request, *args, **kwargs):
        queryset  = self.get_queryset()
        response  = super().list(request, *args, **kwargs)

        # Inject total counts into the response for the dashboard.
        response.data["total_confirmed"]   = Subscriber.objects.filter(confirmed=True).count()
        response.data["total_unconfirmed"] = Subscriber.objects.filter(confirmed=False).count()
        response.data["total_all"]         = Subscriber.objects.count()

        return response
