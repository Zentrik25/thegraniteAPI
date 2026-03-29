"""
views.py — API views for the subscriptions app.

Endpoint map (all under /api/v1/subscriptions/):

  Public:
    GET  plans/                  — list active plans with USD prices

  Reader (accounts JWT required):
    GET  my-subscription/        — current subscription status
    POST subscribe/              — initiate Paynow USD payment + create subscription
    POST cancel/                 — cancel at period end
    GET  payments/               — payment history in USD

  Paynow:
    POST paynow-callback/        — Paynow result URL webhook
    GET  paynow-poll/<payment-id>/ — frontend polls payment status

  Staff (Senior Editor +):
    GET  all/                    — all subscriptions with reader details
    GET  revenue/                — revenue report in USD
"""

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authentication import ReaderJWTAuthentication
from accounts.permissions import IsReader
from core.pagination import StandardResultsPagination
from users.permissions import IsSeniorEditorOrAbove

from .models import (
    ArticleAccess,
    BillingPeriod,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
)
from .paynow_client import PaynowClient
from .serializers import (
    CancelSubscriptionSerializer,
    PaymentSerializer,
    PaynowCallbackSerializer,
    RevenueReportSerializer,
    SubscribeSerializer,
    SubscriptionListSerializer,
    SubscriptionPlanSerializer,
    SubscriptionSerializer,
)
from .tasks import process_paynow_callback

logger = logging.getLogger("subscriptions.views")

_SUBSCRIPTION_CACHE_TTL = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

class PlanListView(generics.ListAPIView):
    """
    GET /api/v1/subscriptions/plans/

    Returns all active subscription plans with USD pricing.
    No authentication required.
    """

    serializer_class    = SubscriptionPlanSerializer
    permission_classes  = [AllowAny]
    authentication_classes = []
    pagination_class    = None

    def get_queryset(self):
        """Return only active plans ordered by ascending price."""
        return SubscriptionPlan.objects.filter(is_active=True).order_by("price_usd")


# ---------------------------------------------------------------------------
# Reader — subscription status
# ---------------------------------------------------------------------------

class MySubscriptionView(APIView):
    """
    GET /api/v1/subscriptions/my-subscription/

    Returns the reader's current active (or most recent) subscription.
    If the reader has no subscription, returns 404.
    Authentication: reader JWT only.
    """

    authentication_classes = [ReaderJWTAuthentication]
    permission_classes     = [IsAuthenticated, IsReader]

    @extend_schema(responses=SubscriptionSerializer)
    def get(self, request) -> Response:
        """Return the most recent subscription for the authenticated reader."""
        subscription = (
            Subscription.objects.filter(reader=request.user)
            .select_related("plan")
            .order_by("-created_at")
            .first()
        )
        if not subscription:
            return Response(
                {"detail": "You do not have an active subscription."},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = SubscriptionSerializer(subscription)
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Reader — subscribe
# ---------------------------------------------------------------------------

class SubscribeView(APIView):
    """
    POST /api/v1/subscriptions/subscribe/

    Initiates a Paynow USD payment and creates a TRIALING subscription
    record. The subscription transitions to ACTIVE once Paynow confirms
    the payment via the callback or poll endpoint.

    Free plans ($0.00) are activated immediately without payment.
    """

    authentication_classes = [ReaderJWTAuthentication]
    permission_classes     = [IsAuthenticated, IsReader]

    @extend_schema(request=SubscribeSerializer, responses={201: SubscriptionSerializer})
    def post(self, request) -> Response:
        """Create a subscription and initiate Paynow payment in USD."""
        serializer = SubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        plan_slug      = serializer.validated_data["plan_slug"]
        payment_method = serializer.validated_data["payment_method"]
        phone_number   = serializer.validated_data.get("phone_number", "")

        plan = get_object_or_404(SubscriptionPlan, slug=plan_slug, is_active=True)
        reader = request.user

        # Determine billing period length
        if plan.billing_period == BillingPeriod.ANNUAL:
            period_days = 365
        else:
            period_days = 30

        today = date.today()
        period_end = today + timedelta(days=period_days)

        # Free plan — activate immediately, no payment needed
        if plan.price_usd == Decimal("0.00"):
            subscription = Subscription.objects.create(
                reader=reader,
                plan=plan,
                status=SubscriptionStatus.ACTIVE,
                started_at=timezone.now(),
                current_period_start=today,
                current_period_end=period_end,
            )
            _invalidate_reader_subscription_cache(reader.id)
            logger.info(
                "[Subscribe] Free plan activated: reader=%s plan=%s",
                reader.email,
                plan.slug,
            )
            return Response(
                SubscriptionSerializer(subscription).data,
                status=status.HTTP_201_CREATED,
            )

        # Paid plan — create subscription in TRIALING, initiate payment
        subscription = Subscription.objects.create(
            reader=reader,
            plan=plan,
            status=SubscriptionStatus.TRIALING,
            started_at=timezone.now(),
            current_period_start=today,
            current_period_end=period_end,
        )

        reference = f"granite-sub-{subscription.id}"
        paynow    = PaynowClient()

        if payment_method in (PaymentMethod.ECOCASH, PaymentMethod.ONEMONEY):
            result = paynow.initiate_mobile_payment(
                amount_usd=float(plan.price_usd),
                phone=phone_number,
                email=reader.email,
                reference=reference,
            )
        else:
            result = paynow.initiate_web_payment(
                amount_usd=float(plan.price_usd),
                email=reader.email,
                reference=reference,
            )

        if not result["ok"]:
            subscription.delete()
            logger.warning(
                "[Subscribe] Paynow payment initiation failed: reader=%s error=%s",
                reader.email,
                result["error"],
            )
            return Response(
                {"detail": f"Payment gateway error: {result['error']}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # Record the payment
        Payment.objects.create(
            subscription=subscription,
            amount_usd=plan.price_usd,
            currency="USD",
            payment_method=payment_method,
            status=PaymentStatus.PENDING,
            paynow_reference=result["reference"],
            paynow_poll_url=result["poll_url"],
            paynow_redirect_url=result["redirect_url"],
            phone_number=phone_number,
        )

        subscription.paynow_reference = result["reference"]
        subscription.save(update_fields=["paynow_reference"])

        _invalidate_reader_subscription_cache(reader.id)

        logger.info(
            "[Subscribe] Payment initiated: reader=%s plan=%s ref=%s",
            reader.email,
            plan.slug,
            result["reference"],
        )

        response_data = SubscriptionSerializer(subscription).data
        response_data["redirect_url"] = result["redirect_url"]
        response_data["poll_url"]     = result["poll_url"]

        return Response(response_data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Reader — cancel
# ---------------------------------------------------------------------------

class CancelSubscriptionView(APIView):
    """
    POST /api/v1/subscriptions/cancel/

    Cancels the reader's active subscription. By default sets
    cancel_at_period_end=True so access continues until period end.
    If cancel_immediately=True the subscription is cancelled instantly.
    """

    authentication_classes = [ReaderJWTAuthentication]
    permission_classes     = [IsAuthenticated, IsReader]

    @extend_schema(request=CancelSubscriptionSerializer, responses={200: SubscriptionSerializer})
    def post(self, request) -> Response:
        """Cancel the authenticated reader's active subscription."""
        serializer = CancelSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cancel_immediately = serializer.validated_data["cancel_immediately"]

        subscription = (
            Subscription.objects.filter(
                reader=request.user,
                status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING],
            )
            .select_related("plan")
            .first()
        )

        if not subscription:
            return Response(
                {"detail": "No active subscription to cancel."},
                status=status.HTTP_404_NOT_FOUND,
            )

        now = timezone.now()
        if cancel_immediately:
            subscription.status      = SubscriptionStatus.CANCELLED
            subscription.cancelled_at = now
            subscription.save(update_fields=["status", "cancelled_at", "updated_at"])
        else:
            subscription.cancel_at_period_end = True
            subscription.cancelled_at         = now
            subscription.save(update_fields=["cancel_at_period_end", "cancelled_at", "updated_at"])

        _invalidate_reader_subscription_cache(request.user.id)

        logger.info(
            "[Cancel] Subscription cancelled: reader=%s sub=%s immediate=%s",
            request.user.email,
            subscription.id,
            cancel_immediately,
        )
        return Response(SubscriptionSerializer(subscription).data)


# ---------------------------------------------------------------------------
# Reader — payment history
# ---------------------------------------------------------------------------

class PaymentHistoryView(generics.ListAPIView):
    """
    GET /api/v1/subscriptions/payments/

    Returns the authenticated reader's payment history in USD.
    """

    serializer_class       = PaymentSerializer
    authentication_classes = [ReaderJWTAuthentication]
    permission_classes     = [IsAuthenticated, IsReader]
    pagination_class       = StandardResultsPagination

    def get_queryset(self):
        """Return payments for the authenticated reader, newest first."""
        return (
            Payment.objects.filter(subscription__reader=self.request.user)
            .select_related("subscription__plan")
            .order_by("-created_at")
        )


# ---------------------------------------------------------------------------
# Paynow — callback webhook
# ---------------------------------------------------------------------------

class PaynowCallbackView(APIView):
    """
    POST /api/v1/subscriptions/paynow-callback/

    Paynow POSTs payment status to this URL (the result URL).
    Validates the incoming data and enqueues process_paynow_callback
    to activate the subscription asynchronously.

    No authentication — Paynow does not send our JWT.
    """

    permission_classes     = [AllowAny]
    authentication_classes = []

    @extend_schema(request=PaynowCallbackSerializer, responses={200: None})
    def post(self, request) -> Response:
        """Accept Paynow payment callback and trigger async processing."""
        serializer = PaynowCallbackSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("[PaynowCallback] Invalid payload: %s", serializer.errors)
            return Response({"detail": "ok"})  # Always 200 to Paynow

        data      = serializer.validated_data
        reference = data.get("reference", "")

        logger.info(
            "[PaynowCallback] Received: reference=%s status=%s",
            reference,
            data.get("status", ""),
        )

        # Find the payment by Paynow reference
        # Paynow sends 'paynowreference' (no underscore) as the canonical reference
        paynow_ref = data.get("paynowreference") or reference
        try:
            payment = Payment.objects.select_related("subscription").get(
                paynow_reference=paynow_ref
            )
        except Payment.DoesNotExist:
            logger.warning("[PaynowCallback] Payment not found for reference=%s", paynow_ref)
            return Response({"detail": "ok"})

        # Enqueue async processing
        process_paynow_callback.delay(str(payment.id))

        return Response({"detail": "ok"})


# ---------------------------------------------------------------------------
# Paynow — frontend poll
# ---------------------------------------------------------------------------

class PaynowPollView(APIView):
    """
    GET /api/v1/subscriptions/paynow-poll/<payment-id>/

    The frontend polls this endpoint to check whether a pending payment
    has been confirmed. Activates subscription inline if paid.
    Authentication: reader JWT.
    """

    authentication_classes = [ReaderJWTAuthentication]
    permission_classes     = [IsAuthenticated, IsReader]

    def get(self, request, payment_id: str) -> Response:
        """Poll Paynow for payment status and return current state."""
        try:
            payment = Payment.objects.select_related("subscription__plan").get(
                id=payment_id,
                subscription__reader=request.user,
            )
        except Payment.DoesNotExist:
            return Response(
                {"detail": "Payment not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if payment.status == PaymentStatus.COMPLETED:
            return Response({
                "paid":   True,
                "status": PaymentStatus.COMPLETED,
                "subscription": SubscriptionSerializer(payment.subscription).data,
            })

        if not payment.paynow_poll_url:
            return Response({
                "paid":   False,
                "status": payment.status,
            })

        paynow  = PaynowClient()
        result  = paynow.check_payment_status(payment.paynow_poll_url)

        if not result["ok"]:
            return Response({
                "paid":   False,
                "status": payment.status,
                "error":  result["error"],
            })

        if result["paid"]:
            _activate_subscription(payment)
            _invalidate_reader_subscription_cache(request.user.id)
            return Response({
                "paid":         True,
                "status":       PaymentStatus.COMPLETED,
                "subscription": SubscriptionSerializer(payment.subscription).data,
            })

        return Response({
            "paid":   False,
            "status": payment.status,
        })


# ---------------------------------------------------------------------------
# Staff — all subscriptions
# ---------------------------------------------------------------------------

class AllSubscriptionsView(generics.ListAPIView):
    """
    GET /api/v1/subscriptions/all/

    Staff-only. Returns all subscriptions with reader details and stats.
    Requires Senior Editor role or above.
    """

    serializer_class   = SubscriptionListSerializer
    permission_classes = [IsAuthenticated, IsSeniorEditorOrAbove]
    pagination_class   = StandardResultsPagination

    def get_queryset(self):
        """Return all subscriptions ordered by most recently created."""
        qs = Subscription.objects.select_related("reader", "plan").order_by("-created_at")

        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        return qs


# ---------------------------------------------------------------------------
# Staff — revenue report
# ---------------------------------------------------------------------------

class RevenueReportView(APIView):
    """
    GET /api/v1/subscriptions/revenue/

    Staff-only revenue report. All monetary values are in USD only.
    Returns total active subscribers, monthly revenue, all-time revenue,
    and a breakdown by plan.
    Requires Senior Editor role or above.
    """

    permission_classes = [IsAuthenticated, IsSeniorEditorOrAbove]

    def get(self, request) -> Response:
        """Generate and return USD revenue report."""
        now   = timezone.now()
        today = now.date()

        # First day of current month
        month_start = today.replace(day=1)

        total_active = Subscription.objects.filter(
            status=SubscriptionStatus.ACTIVE,
            current_period_end__gte=today,
        ).count()

        total_revenue_month = (
            Payment.objects.filter(
                status=PaymentStatus.COMPLETED,
                created_at__gte=timezone.make_aware(
                    timezone.datetime(month_start.year, month_start.month, 1)
                ),
            ).aggregate(total=Sum("amount_usd"))["total"]
            or Decimal("0.00")
        )

        total_revenue_all = (
            Payment.objects.filter(status=PaymentStatus.COMPLETED)
            .aggregate(total=Sum("amount_usd"))["total"]
            or Decimal("0.00")
        )

        # Per-plan breakdown
        breakdown = []
        for plan in SubscriptionPlan.objects.filter(is_active=True).order_by("price_usd"):
            active_count = Subscription.objects.filter(
                plan=plan,
                status=SubscriptionStatus.ACTIVE,
                current_period_end__gte=today,
            ).count()
            breakdown.append({
                "plan_name":       plan.name,
                "plan_slug":       plan.slug,
                "price_usd":       str(plan.price_usd),
                "active_count":    active_count,
                "currency":        "USD",
            })

        data = {
            "total_active_subscribers":   total_active,
            "total_revenue_usd_month":    total_revenue_month,
            "total_revenue_usd_all_time": total_revenue_all,
            "currency":                   "USD",
            "report_month":               month_start.strftime("%B %Y"),
            "breakdown_by_plan":          breakdown,
        }

        serializer = RevenueReportSerializer(data)
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _activate_subscription(payment: Payment) -> None:
    """
    Mark *payment* as COMPLETED and activate the linked subscription.

    Called when Paynow confirms payment — either from the poll endpoint
    or the async task.
    """
    payment.status = PaymentStatus.COMPLETED
    payment.save(update_fields=["status", "updated_at"])

    subscription = payment.subscription
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.paynow_reference = payment.paynow_reference
    subscription.save(update_fields=["status", "paynow_reference", "updated_at"])

    logger.info(
        "[Activate] Subscription activated: sub=%s payment=%s",
        subscription.id,
        payment.id,
    )


def _invalidate_reader_subscription_cache(reader_id) -> None:
    """Remove cached subscription status for *reader_id*."""
    cache_key = f"subscriptions:reader:{reader_id}:status"
    cache.delete(cache_key)
