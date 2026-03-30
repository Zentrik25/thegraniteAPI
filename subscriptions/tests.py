"""
tests.py — Test suite for the subscriptions app.

Coverage:
  - Free articles accessible without subscription
  - Premium articles return 402 for unauthenticated readers
  - Premium articles return 402 for free-plan readers
  - Premium articles accessible for premium subscribers
  - Premium articles accessible for supporter subscribers
  - Staff always access premium articles regardless of subscription
  - Subscription creation initiates Paynow payment in USD
  - Paynow callback activates subscription
  - Expired subscriptions handled correctly
  - Plan list is public and shows USD prices
  - Payment history shows USD amounts only
  - Revenue report shows USD only
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.cache import cache, caches
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone as django_tz
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from accounts.authentication import get_tokens_for_reader
from accounts.models import ReaderAccount
from articles.models import Article, Category, PublishStatus
from users.models import StaffRole, StaffUser

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_reader(email: str = "reader@test.com", username: str = "testreader") -> ReaderAccount:
    """Create an active, verified reader."""
    reader = ReaderAccount(
        email=email,
        username=username,
        is_active=True,
        is_email_verified=True,
    )
    reader.set_password("Pass1234!")
    reader.save()
    return reader


def _make_staff(username: str = "staffuser", role: str = StaffRole.EDITOR) -> StaffUser:
    """Create a staff user with the given role."""
    return StaffUser.objects.create_user(
        username=username,
        email=f"{username}@test.com",
        password="Staff1234!",
        role=role,
    )


def _make_article(
    author: StaffUser,
    title: str = "Test Article",
    is_premium: bool = False,
    status_val: str = PublishStatus.PUBLISHED,
) -> Article:
    """Create a published article."""
    cat, _ = Category.objects.get_or_create(name="News", defaults={"slug": "news"})
    return Article.objects.create(
        title=title,
        body="Body text.",
        author=author,
        category=cat,
        status=status_val,
        is_premium=is_premium,
    )


def _make_free_plan() -> SubscriptionPlan:
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug="free",
        defaults=dict(
            name="Free",
            price_usd=Decimal("0.00"),
            billing_period=BillingPeriod.MONTHLY,
            article_access=ArticleAccess.FREE_ONLY,
            is_active=True,
        ),
    )
    return plan


def _make_premium_plan() -> SubscriptionPlan:
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug="premium",
        defaults=dict(
            name="Premium",
            price_usd=Decimal("2.00"),
            billing_period=BillingPeriod.MONTHLY,
            article_access=ArticleAccess.PREMIUM,
            is_active=True,
        ),
    )
    return plan


def _make_supporter_plan() -> SubscriptionPlan:
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug="supporter",
        defaults=dict(
            name="Supporter",
            price_usd=Decimal("5.00"),
            billing_period=BillingPeriod.MONTHLY,
            article_access=ArticleAccess.ALL,
            is_active=True,
        ),
    )
    return plan


def _make_active_subscription(reader: ReaderAccount, plan: SubscriptionPlan) -> Subscription:
    """Create an active subscription for *reader* on *plan*."""
    today = date.today()
    return Subscription.objects.create(
        reader=reader,
        plan=plan,
        status=SubscriptionStatus.ACTIVE,
        started_at=django_tz.now(),
        current_period_start=today,
        current_period_end=today + timedelta(days=30),
    )


def _reader_auth_headers(reader: ReaderAccount) -> dict:
    """Return Authorization header dict for *reader*."""
    tokens = get_tokens_for_reader(reader)
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens['access']}"}


# ---------------------------------------------------------------------------
# Plan listing
# ---------------------------------------------------------------------------

class PlanListTests(TestCase):
    """GET /api/v1/subscriptions/plans/ — public, no auth required."""

    def setUp(self) -> None:
        from django.core.cache import cache as _cache
        _cache.clear()  # plan list is cached; clear so each test sees fresh DB state
        self.client = APIClient()
        self.free_plan    = _make_free_plan()
        self.premium_plan = _make_premium_plan()

    def test_plan_list_is_public(self) -> None:
        """Plan list returns 200 without authentication."""
        response = self.client.get("/api/v1/subscriptions/plans/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_plan_list_shows_usd_prices(self) -> None:
        """Plan list includes price_usd field for each plan."""
        response = self.client.get("/api/v1/subscriptions/plans/")
        data = response.json()
        self.assertGreaterEqual(len(data), 2)
        for plan in data:
            self.assertIn("price_usd", plan)

    def test_inactive_plans_excluded(self) -> None:
        """Inactive plans do not appear in the public listing."""
        self.premium_plan.is_active = False
        self.premium_plan.save()
        response = self.client.get("/api/v1/subscriptions/plans/")
        slugs = [p["slug"] for p in response.json()]
        self.assertNotIn("premium", slugs)

    def test_free_plan_price_is_zero_usd(self) -> None:
        """Free plan shows $0.00 USD."""
        response = self.client.get("/api/v1/subscriptions/plans/")
        free = next(p for p in response.json() if p["slug"] == "free")
        self.assertEqual(free["price_usd"], "0.00")


# ---------------------------------------------------------------------------
# Paywall middleware
# ---------------------------------------------------------------------------

class PaywallMiddlewareTests(TestCase):
    """PaywallMiddleware enforces premium access on /api/v1/articles/<slug>/."""

    def setUp(self) -> None:
        self.client      = APIClient()
        self.staff_user  = _make_staff()
        self.reader      = _make_reader()
        self.free_plan   = _make_free_plan()
        self.premium_plan = _make_premium_plan()
        self.supporter_plan = _make_supporter_plan()

    def _article_url(self, slug: str) -> str:
        return f"/api/v1/articles/{slug}/"

    def test_free_article_accessible_without_auth(self) -> None:
        """A non-premium article is accessible to unauthenticated requests."""
        article = _make_article(self.staff_user, title="Free Article", is_premium=False)
        response = self.client.get(self._article_url(article.slug))
        # The articles view handles the 200/404; we just confirm no 402
        self.assertNotEqual(response.status_code, 402)

    def test_premium_article_returns_402_unauthenticated(self) -> None:
        """Premium article returns 402 for unauthenticated readers."""
        article = _make_article(self.staff_user, title="Premium Article", is_premium=True)
        response = self.client.get(self._article_url(article.slug))
        self.assertEqual(response.status_code, 402)

    def test_premium_article_head_returns_402_unauthenticated(self) -> None:
        """HEAD requests must not bypass the premium article paywall."""
        article = _make_article(self.staff_user, title="Premium Head Article", is_premium=True)
        response = self.client.head(self._article_url(article.slug))
        self.assertEqual(response.status_code, 402)

    def test_premium_article_returns_402_for_free_plan_reader(self) -> None:
        """Premium article returns 402 for reader on FREE_ONLY plan."""
        _make_active_subscription(self.reader, self.free_plan)
        headers = _reader_auth_headers(self.reader)
        article = _make_article(self.staff_user, title="Premium Only", is_premium=True)
        response = self.client.get(self._article_url(article.slug), **headers)
        self.assertEqual(response.status_code, 402)

    def test_premium_article_accessible_for_premium_subscriber(self) -> None:
        """Premium article is accessible for reader on Premium plan."""
        _make_active_subscription(self.reader, self.premium_plan)
        headers = _reader_auth_headers(self.reader)
        article = _make_article(self.staff_user, title="Premium Access", is_premium=True)
        response = self.client.get(self._article_url(article.slug), **headers)
        self.assertNotEqual(response.status_code, 402)

    def test_premium_article_accessible_for_supporter_subscriber(self) -> None:
        """Premium article is accessible for reader on Supporter plan."""
        _make_active_subscription(self.reader, self.supporter_plan)
        headers = _reader_auth_headers(self.reader)
        article = _make_article(self.staff_user, title="Supporter Access", is_premium=True)
        response = self.client.get(self._article_url(article.slug), **headers)
        self.assertNotEqual(response.status_code, 402)

    def test_staff_always_access_premium_articles(self) -> None:
        """Staff users bypass the paywall regardless of subscription."""
        article = _make_article(self.staff_user, title="Staff Premium", is_premium=True)
        # Must use a real staff JWT — the middleware inspects the Authorization header directly
        token = AccessToken.for_user(self.staff_user)
        response = self.client.get(
            self._article_url(article.slug),
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertNotEqual(response.status_code, 402)

    def test_402_response_contains_usd_upgrade_plans(self) -> None:
        """402 response body includes upgrade plans with USD pricing."""
        article = _make_article(self.staff_user, title="Paywall Test", is_premium=True)
        response = self.client.get(self._article_url(article.slug))
        self.assertEqual(response.status_code, 402)
        data = response.json()
        self.assertIn("upgrade_plans", data)
        for plan in data["upgrade_plans"]:
            self.assertEqual(plan["currency"], "USD")
            self.assertIn("price_usd", plan)

    def test_expired_subscription_returns_402(self) -> None:
        """Expired subscription does not grant access to premium articles."""
        yesterday = date.today() - timedelta(days=1)
        Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.EXPIRED,
            started_at=django_tz.now(),
            current_period_start=yesterday - timedelta(days=30),
            current_period_end=yesterday,
        )
        headers = _reader_auth_headers(self.reader)
        article = _make_article(self.staff_user, title="Expired Sub Test", is_premium=True)
        response = self.client.get(self._article_url(article.slug), **headers)
        self.assertEqual(response.status_code, 402)


# ---------------------------------------------------------------------------
# Subscribe
# ---------------------------------------------------------------------------

class SubscribeViewTests(TestCase):
    """POST /api/v1/subscriptions/subscribe/"""

    def setUp(self) -> None:
        self.client      = APIClient()
        self.reader      = _make_reader()
        self.free_plan   = _make_free_plan()
        self.premium_plan = _make_premium_plan()

    def test_subscribe_free_plan_activates_immediately(self) -> None:
        """Subscribing to a free plan activates without Paynow payment."""
        headers = _reader_auth_headers(self.reader)
        # Use BANK_CARD — free plans skip payment entirely so method doesn't matter,
        # but BANK_CARD doesn't require a phone number in the serializer.
        response = self.client.post(
            "/api/v1/subscriptions/subscribe/",
            {"plan_slug": "free", "payment_method": PaymentMethod.BANK_CARD},
            format="json",
            **headers,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["status"], SubscriptionStatus.ACTIVE)

    @patch("subscriptions.views.PaynowClient")
    def test_subscribe_premium_plan_initiates_paynow_payment(
        self, mock_paynow_cls: MagicMock
    ) -> None:
        """Subscribing to a paid plan calls Paynow and returns poll/redirect URLs."""
        mock_client = MagicMock()
        mock_client.initiate_mobile_payment.return_value = {
            "ok":           True,
            "reference":    "PAYNOW-REF-001",
            "poll_url":     "https://www.paynow.co.zw/interface/CheckPayment/?guid=test",
            "redirect_url": "",
            "error":        "",
        }
        mock_paynow_cls.return_value = mock_client

        headers = _reader_auth_headers(self.reader)
        response = self.client.post(
            "/api/v1/subscriptions/subscribe/",
            {
                "plan_slug":      "premium",
                "payment_method": PaymentMethod.ECOCASH,
                "phone_number":   "0771234567",
            },
            format="json",
            **headers,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["status"], SubscriptionStatus.TRIALING)
        self.assertIn("poll_url", data)
        mock_client.initiate_mobile_payment.assert_called_once()

    @patch("subscriptions.views.PaynowClient")
    def test_subscribe_paynow_failure_returns_502(self, mock_paynow_cls: MagicMock) -> None:
        """A Paynow API failure returns 502 and no subscription is created."""
        mock_client = MagicMock()
        mock_client.initiate_mobile_payment.return_value = {
            "ok":    False,
            "error": "Paynow unavailable",
            "reference": "", "poll_url": "", "redirect_url": "",
        }
        mock_paynow_cls.return_value = mock_client

        headers = _reader_auth_headers(self.reader)
        before_count = Subscription.objects.count()
        response = self.client.post(
            "/api/v1/subscriptions/subscribe/",
            {
                "plan_slug":      "premium",
                "payment_method": PaymentMethod.ECOCASH,
                "phone_number":   "0771234567",
            },
            format="json",
            **headers,
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(Subscription.objects.count(), before_count)

    @patch("subscriptions.views.PaynowClient")
    def test_subscribe_logs_do_not_expose_payment_reference_or_urls(
        self, mock_paynow_cls: MagicMock
    ) -> None:
        """Subscription initiation logs must not leak references or Paynow URLs."""
        secret_reference = "PAYNOW-SECRET-REF-001"
        secret_poll_url = "https://www.paynow.co.zw/interface/CheckPayment/?guid=secret-guid"
        secret_redirect_url = "https://www.paynow.co.zw/interface/initiatetransaction/?secret=1"

        mock_client = MagicMock()
        mock_client.initiate_mobile_payment.return_value = {
            "ok":           True,
            "reference":    secret_reference,
            "poll_url":     secret_poll_url,
            "redirect_url": secret_redirect_url,
            "error":        "",
        }
        mock_paynow_cls.return_value = mock_client

        headers = _reader_auth_headers(self.reader)
        with self.assertLogs("subscriptions.views", level="INFO") as captured:
            response = self.client.post(
                "/api/v1/subscriptions/subscribe/",
                {
                    "plan_slug":      "premium",
                    "payment_method": PaymentMethod.ECOCASH,
                    "phone_number":   "0771234567",
                },
                format="json",
                **headers,
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        output = "\n".join(captured.output)
        self.assertNotIn(secret_reference, output)
        self.assertNotIn(secret_poll_url, output)
        self.assertNotIn(secret_redirect_url, output)

    def test_subscribe_requires_reader_auth(self) -> None:
        """Unauthenticated requests are rejected."""
        response = self.client.post(
            "/api/v1/subscriptions/subscribe/",
            {"plan_slug": "free", "payment_method": PaymentMethod.ECOCASH},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_subscribe_invalid_plan_returns_400(self) -> None:
        """Invalid plan slug returns 400 validation error."""
        headers = _reader_auth_headers(self.reader)
        response = self.client.post(
            "/api/v1/subscriptions/subscribe/",
            {"plan_slug": "nonexistent", "payment_method": PaymentMethod.ECOCASH},
            format="json",
            **headers,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# My subscription
# ---------------------------------------------------------------------------

class MySubscriptionSelectionTests(TestCase):
    """GET /api/v1/subscriptions/my-subscription/ returns the effective row."""

    def setUp(self) -> None:
        self.client       = APIClient()
        self.reader       = _make_reader()
        self.premium_plan = _make_premium_plan()

    def test_my_subscription_returns_effective_active_subscription_not_newest_row(self) -> None:
        """Newest historical rows must not hide the reader's real active subscription."""
        today = date.today()
        active_subscription = Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.ACTIVE,
            started_at=django_tz.now() - timedelta(days=10),
            current_period_start=today - timedelta(days=10),
            current_period_end=today + timedelta(days=20),
        )
        Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.CANCELLED,
            started_at=django_tz.now(),
            current_period_start=today,
            current_period_end=today + timedelta(days=30),
            cancelled_at=django_tz.now(),
        )

        headers = _reader_auth_headers(self.reader)
        response = self.client.get("/api/v1/subscriptions/my-subscription/", **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(active_subscription.id))


# ---------------------------------------------------------------------------
# Paynow callback
# ---------------------------------------------------------------------------

class PaynowCallbackTests(TestCase):
    """POST /api/v1/subscriptions/paynow-callback/"""

    def setUp(self) -> None:
        self.client       = APIClient()
        self.reader       = _make_reader()
        self.premium_plan = _make_premium_plan()
        caches["throttle"].clear()
        today = date.today()
        self.subscription = Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.TRIALING,
            started_at=django_tz.now(),
            current_period_start=today,
            current_period_end=today + timedelta(days=30),
            paynow_reference="PAYNOW-TEST-001",
        )
        self.payment = Payment.objects.create(
            subscription=self.subscription,
            amount_usd=Decimal("2.00"),
            currency="USD",
            payment_method=PaymentMethod.ECOCASH,
            status=PaymentStatus.PENDING,
            paynow_reference="PAYNOW-TEST-001",
            paynow_poll_url="https://www.paynow.co.zw/interface/CheckPayment/?guid=test",
        )

    @patch("subscriptions.views.process_paynow_callback")
    def test_callback_enqueues_task(self, mock_task: MagicMock) -> None:
        """Paynow callback enqueues the process_paynow_callback task."""
        response = self.client.post(
            "/api/v1/subscriptions/paynow-callback/",
            {
                "reference":       "granite-sub-test",
                "paynowreference": "PAYNOW-TEST-001",
                "status":          "Paid",
                "pollurl":         "https://www.paynow.co.zw/interface/CheckPayment/?guid=test",
                "amount":          "2.00",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_task.delay.assert_called_once_with(str(self.payment.id))

    @patch("subscriptions.views.process_paynow_callback")
    def test_malformed_callback_rejected(self, mock_task: MagicMock) -> None:
        """Malformed callback bodies should be rejected before task dispatch."""
        response = self.client.post(
            "/api/v1/subscriptions/paynow-callback/",
            {
                "status": "Paid",
                "pollurl": "https://www.paynow.co.zw/interface/CheckPayment/?guid=test",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Invalid callback payload.")
        mock_task.delay.assert_not_called()

    @patch("subscriptions.views.process_paynow_callback")
    def test_callback_logs_do_not_expose_payment_references(self, mock_task: MagicMock) -> None:
        """Callback logs must not contain raw Paynow or merchant references."""
        with self.assertLogs("subscriptions.views", level="INFO") as captured:
            response = self.client.post(
                "/api/v1/subscriptions/paynow-callback/",
                {
                    "reference":       "granite-sub-secret",
                    "paynowreference": self.payment.paynow_reference,
                    "status":          "Paid",
                    "pollurl":         "https://www.paynow.co.zw/interface/CheckPayment/?guid=secret",
                    "amount":          "2.00",
                },
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(mock_task.delay.called)
        output = "\n".join(captured.output)
        self.assertNotIn("granite-sub-secret", output)
        self.assertNotIn(self.payment.paynow_reference, output)

    @patch("subscriptions.views.process_paynow_callback")
    def test_duplicate_callback_is_suppressed_before_worker_enqueue(
        self, mock_task: MagicMock
    ) -> None:
        """Repeated valid callbacks should not enqueue duplicate worker jobs."""
        payload = {
            "reference":       "granite-sub-test",
            "paynowreference": self.payment.paynow_reference,
            "status":          "Paid",
            "pollurl":         "https://www.paynow.co.zw/interface/CheckPayment/?guid=test",
            "amount":          "2.00",
        }

        first = self.client.post("/api/v1/subscriptions/paynow-callback/", payload)
        second = self.client.post("/api/v1/subscriptions/paynow-callback/", payload)

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        mock_task.delay.assert_called_once_with(str(self.payment.id))

    @patch("subscriptions.paynow_client.PaynowClient")
    def test_process_callback_activates_subscription(self, mock_paynow_cls: MagicMock) -> None:
        """process_paynow_callback task activates subscription when payment confirmed."""
        from subscriptions.tasks import process_paynow_callback as task

        mock_client = MagicMock()
        mock_client.check_payment_status.return_value = {
            "ok":        True,
            "paid":      True,
            "reference": "PAYNOW-TEST-001",
            "amount":    2.00,
            "status":    "Paid",
            "error":     "",
        }
        mock_paynow_cls.return_value = mock_client

        task(str(self.payment.id))

        self.payment.refresh_from_db()
        self.subscription.refresh_from_db()

        self.assertEqual(self.payment.status, PaymentStatus.COMPLETED)
        self.assertEqual(self.subscription.status, SubscriptionStatus.ACTIVE)

    @patch("subscriptions.paynow_client.PaynowClient")
    def test_repeated_callback_processing_is_harmless(self, mock_paynow_cls: MagicMock) -> None:
        """A second callback run is a no-op once the payment is already completed."""
        from subscriptions.tasks import process_paynow_callback as task

        mock_client = MagicMock()
        mock_client.check_payment_status.return_value = {
            "ok":        True,
            "paid":      True,
            "reference": "PAYNOW-TEST-001",
            "amount":    2.00,
            "status":    "Paid",
            "error":     "",
        }
        mock_paynow_cls.return_value = mock_client

        task(str(self.payment.id))
        task(str(self.payment.id))

        self.payment.refresh_from_db()
        self.subscription.refresh_from_db()

        self.assertEqual(self.payment.status, PaymentStatus.COMPLETED)
        self.assertEqual(self.subscription.status, SubscriptionStatus.ACTIVE)
        self.assertEqual(mock_client.check_payment_status.call_count, 1)


# ---------------------------------------------------------------------------
# Paynow poll
# ---------------------------------------------------------------------------

class PaynowPollViewTests(TestCase):
    """GET /api/v1/subscriptions/paynow-poll/<payment-id>/"""

    def setUp(self) -> None:
        self.client       = APIClient()
        self.reader       = _make_reader()
        self.premium_plan = _make_premium_plan()
        caches["throttle"].clear()
        today = date.today()
        self.subscription = Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.TRIALING,
            started_at=django_tz.now(),
            current_period_start=today,
            current_period_end=today + timedelta(days=30),
            paynow_reference="PAYNOW-POLL-001",
        )
        self.payment = Payment.objects.create(
            subscription=self.subscription,
            amount_usd=Decimal("2.00"),
            currency="USD",
            payment_method=PaymentMethod.ECOCASH,
            status=PaymentStatus.PENDING,
            paynow_reference="PAYNOW-POLL-001",
            paynow_poll_url="https://www.paynow.co.zw/interface/CheckPayment/?guid=poll",
        )
        self.headers = _reader_auth_headers(self.reader)

    @patch("subscriptions.views.PaynowClient")
    def test_poll_amount_mismatch_rejects_activation(self, mock_paynow_cls: MagicMock) -> None:
        """Poll path must not activate access when Paynow reports the wrong amount."""
        mock_client = MagicMock()
        mock_client.check_payment_status.return_value = {
            "ok":        True,
            "paid":      True,
            "reference": "PAYNOW-POLL-001",
            "amount":    0.50,
            "status":    "Paid",
            "error":     "",
        }
        mock_paynow_cls.return_value = mock_client

        response = self.client.get(
            f"/api/v1/subscriptions/paynow-poll/{self.payment.id}/",
            **self.headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["paid"], False)
        self.assertEqual(response.json()["status"], PaymentStatus.PENDING)
        self.assertIn("error", response.json())

        self.payment.refresh_from_db()
        self.subscription.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.PENDING)
        self.assertEqual(self.subscription.status, SubscriptionStatus.TRIALING)

    @patch("subscriptions.views.PaynowClient")
    def test_poll_endpoint_is_throttled(self, mock_paynow_cls: MagicMock) -> None:
        """Poll endpoint should rate-limit repeated checks for the same payment."""
        from subscriptions.throttling import PaymentPollThrottle

        mock_client = MagicMock()
        mock_client.check_payment_status.return_value = {
            "ok":        True,
            "paid":      False,
            "reference": "PAYNOW-POLL-001",
            "amount":    2.00,
            "status":    "Sent",
            "error":     "",
        }
        mock_paynow_cls.return_value = mock_client

        with patch.object(PaymentPollThrottle, "rate", "2/min"):
            first = self.client.get(
                f"/api/v1/subscriptions/paynow-poll/{self.payment.id}/",
                **self.headers,
            )
            second = self.client.get(
                f"/api/v1/subscriptions/paynow-poll/{self.payment.id}/",
                **self.headers,
            )
            third = self.client.get(
                f"/api/v1/subscriptions/paynow-poll/{self.payment.id}/",
                **self.headers,
            )

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(third.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    @patch("subscriptions.paynow_client.PaynowClient")
    def test_poll_after_callback_processing_returns_completed_without_reactivation(
        self, mock_paynow_cls: MagicMock
    ) -> None:
        """Overlapping callback then poll processing should only activate once."""
        from subscriptions.tasks import process_paynow_callback as task

        mock_client = MagicMock()
        mock_client.check_payment_status.return_value = {
            "ok":        True,
            "paid":      True,
            "reference": "PAYNOW-POLL-001",
            "amount":    2.00,
            "status":    "Paid",
            "error":     "",
        }
        mock_paynow_cls.return_value = mock_client

        task(str(self.payment.id))

        with patch("subscriptions.views.services.activate_subscription") as mock_activate:
            response = self.client.get(
                f"/api/v1/subscriptions/paynow-poll/{self.payment.id}/",
                **self.headers,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["paid"], True)
        self.assertEqual(response.json()["status"], PaymentStatus.COMPLETED)
        mock_activate.assert_not_called()


# ---------------------------------------------------------------------------
# Payment history
# ---------------------------------------------------------------------------

class PaymentHistoryTests(TestCase):
    """GET /api/v1/subscriptions/payments/"""

    def setUp(self) -> None:
        self.client       = APIClient()
        self.reader       = _make_reader()
        self.premium_plan = _make_premium_plan()
        today             = date.today()
        self.subscription = Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.ACTIVE,
            started_at=django_tz.now(),
            current_period_start=today,
            current_period_end=today + timedelta(days=30),
        )
        Payment.objects.create(
            subscription=self.subscription,
            amount_usd=Decimal("2.00"),
            currency="USD",
            payment_method=PaymentMethod.ECOCASH,
            status=PaymentStatus.COMPLETED,
        )

    def test_payment_history_shows_usd_amounts(self) -> None:
        """Payment history returns amount_usd and currency='USD' for each record."""
        headers = _reader_auth_headers(self.reader)
        response = self.client.get("/api/v1/subscriptions/payments/", **headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertGreater(len(results), 0)
        for payment in results:
            self.assertIn("amount_usd", payment)
            self.assertEqual(payment["currency"], "USD")

    def test_payment_history_requires_reader_auth(self) -> None:
        """Unauthenticated requests are rejected."""
        response = self.client.get("/api/v1/subscriptions/payments/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Revenue report
# ---------------------------------------------------------------------------

class RevenueReportTests(TestCase):
    """GET /api/v1/subscriptions/revenue/ — staff only."""

    def setUp(self) -> None:
        self.client        = APIClient()
        self.senior_editor = _make_staff("senior", StaffRole.SENIOR_EDITOR)
        self.author        = _make_staff("author", StaffRole.AUTHOR)
        self.reader        = _make_reader()
        self.premium_plan  = _make_premium_plan()
        today              = date.today()
        sub = Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.ACTIVE,
            started_at=django_tz.now(),
            current_period_start=today,
            current_period_end=today + timedelta(days=30),
        )
        Payment.objects.create(
            subscription=sub,
            amount_usd=Decimal("2.00"),
            currency="USD",
            payment_method=PaymentMethod.ECOCASH,
            status=PaymentStatus.COMPLETED,
        )

    def test_revenue_report_shows_usd(self) -> None:
        """Revenue report returns USD totals and currency='USD'."""
        self.client.force_authenticate(user=self.senior_editor)
        response = self.client.get("/api/v1/subscriptions/revenue/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["currency"], "USD")
        self.assertIn("total_active_subscribers", data)
        self.assertIn("total_revenue_usd_month", data)
        self.assertIn("total_revenue_usd_all_time", data)
        self.assertIn("breakdown_by_plan", data)
        for item in data["breakdown_by_plan"]:
            self.assertEqual(item["currency"], "USD")

    def test_revenue_report_requires_senior_editor(self) -> None:
        """Authors cannot access the revenue report."""
        self.client.force_authenticate(user=self.author)
        response = self.client.get("/api/v1/subscriptions/revenue/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_revenue_report_unauthenticated_rejected(self) -> None:
        """Unauthenticated requests are rejected."""
        response = self.client.get("/api/v1/subscriptions/revenue/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Expired subscription task
# ---------------------------------------------------------------------------

class ExpiredSubscriptionTaskTests(TestCase):
    """check_expired_subscriptions Celery task."""

    def setUp(self) -> None:
        self.reader       = _make_reader()
        self.premium_plan = _make_premium_plan()

    def test_expired_subscriptions_marked_expired(self) -> None:
        """Task marks ACTIVE subscriptions with past period_end as EXPIRED."""
        from subscriptions.tasks import check_expired_subscriptions

        yesterday = date.today() - timedelta(days=1)
        sub = Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.ACTIVE,
            started_at=django_tz.now(),
            current_period_start=yesterday - timedelta(days=29),
            current_period_end=yesterday,
        )

        check_expired_subscriptions()

        sub.refresh_from_db()
        self.assertEqual(sub.status, SubscriptionStatus.EXPIRED)

    def test_active_subscriptions_not_affected(self) -> None:
        """Task does not touch subscriptions with a future period_end."""
        from subscriptions.tasks import check_expired_subscriptions

        today = date.today()
        sub = Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.ACTIVE,
            started_at=django_tz.now(),
            current_period_start=today,
            current_period_end=today + timedelta(days=25),
        )

        check_expired_subscriptions()

        sub.refresh_from_db()
        self.assertEqual(sub.status, SubscriptionStatus.ACTIVE)

    def test_expiry_task_invalidates_reader_cache(self) -> None:
        """Expiring a subscription must evict cached paywall access for that reader."""
        from subscriptions.tasks import check_expired_subscriptions

        yesterday = date.today() - timedelta(days=1)
        sub = Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.ACTIVE,
            started_at=django_tz.now(),
            current_period_start=yesterday - timedelta(days=29),
            current_period_end=yesterday,
        )
        cache_key = f"subscriptions:reader:{self.reader.id}:status"
        cache.set(cache_key, True, 300)

        check_expired_subscriptions()

        sub.refresh_from_db()
        self.assertEqual(sub.status, SubscriptionStatus.EXPIRED)
        self.assertIsNone(cache.get(cache_key))


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

class CancelSubscriptionTests(TestCase):
    """POST /api/v1/subscriptions/cancel/"""

    def setUp(self) -> None:
        self.client       = APIClient()
        self.reader       = _make_reader()
        self.premium_plan = _make_premium_plan()
        self.subscription = _make_active_subscription(self.reader, self.premium_plan)

    def test_cancel_at_period_end_by_default(self) -> None:
        """Default cancellation sets cancel_at_period_end=True."""
        headers = _reader_auth_headers(self.reader)
        response = self.client.post(
            "/api/v1/subscriptions/cancel/",
            {"cancel_immediately": False},
            format="json",
            **headers,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.cancel_at_period_end)
        self.assertEqual(self.subscription.status, SubscriptionStatus.ACTIVE)

    def test_cancel_immediately_sets_cancelled_status(self) -> None:
        """cancel_immediately=True transitions status to CANCELLED at once."""
        headers = _reader_auth_headers(self.reader)
        response = self.client.post(
            "/api/v1/subscriptions/cancel/",
            {"cancel_immediately": True},
            format="json",
            **headers,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, SubscriptionStatus.CANCELLED)

    def test_cancel_without_subscription_returns_404(self) -> None:
        """Cancelling with no active subscription returns 404."""
        reader2 = _make_reader("other@test.com", "otherreader")
        headers = _reader_auth_headers(reader2)
        response = self.client.post(
            "/api/v1/subscriptions/cancel/",
            {"cancel_immediately": False},
            format="json",
            **headers,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# Payment safety — services.activate_subscription
# ---------------------------------------------------------------------------

class ActivationServiceTests(TestCase):
    """
    Unit tests for subscriptions.services.activate_subscription.

    Covers idempotency, amount verification, and atomicity.
    """

    def setUp(self) -> None:
        self.reader       = _make_reader()
        self.premium_plan = _make_premium_plan()
        today = date.today()
        self.subscription = Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.TRIALING,
            started_at=django_tz.now(),
            current_period_start=today,
            current_period_end=today + timedelta(days=30),
            paynow_reference="PAYNOW-SVC-001",
        )
        self.payment = Payment.objects.create(
            subscription=self.subscription,
            amount_usd=Decimal("2.00"),
            currency="USD",
            payment_method=PaymentMethod.ECOCASH,
            status=PaymentStatus.PENDING,
            paynow_reference="PAYNOW-SVC-001",
            paynow_poll_url="https://www.paynow.co.zw/interface/CheckPayment/?guid=svc",
        )

    def test_activation_sets_payment_completed_and_subscription_active(self) -> None:
        """Service sets payment COMPLETED and subscription ACTIVE in one call."""
        from subscriptions.services import activate_subscription
        result = activate_subscription(str(self.payment.id), 2.00)
        self.assertTrue(result)
        self.payment.refresh_from_db()
        self.subscription.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.COMPLETED)
        self.assertEqual(self.subscription.status, SubscriptionStatus.ACTIVE)

    def test_activation_is_idempotent(self) -> None:
        """Calling activate_subscription twice returns False on the second call."""
        from subscriptions.services import activate_subscription
        first  = activate_subscription(str(self.payment.id), 2.00)
        second = activate_subscription(str(self.payment.id), 2.00)
        self.assertTrue(first)
        self.assertFalse(second)
        # Subscription is still ACTIVE — not accidentally reset.
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, SubscriptionStatus.ACTIVE)

    def test_activation_rejected_on_amount_mismatch(self) -> None:
        """Service refuses activation when reported amount differs by more than $0.01."""
        from subscriptions.services import activate_subscription
        result = activate_subscription(str(self.payment.id), 0.50)  # expected $2.00
        self.assertFalse(result)
        self.payment.refresh_from_db()
        self.subscription.refresh_from_db()
        # Nothing should have changed.
        self.assertEqual(self.payment.status, PaymentStatus.PENDING)
        self.assertEqual(self.subscription.status, SubscriptionStatus.TRIALING)

    def test_activation_accepts_amount_within_tolerance(self) -> None:
        """Service accepts reported amounts within the ±$0.01 tolerance band."""
        from subscriptions.services import activate_subscription
        result = activate_subscription(str(self.payment.id), 2.009)  # within $0.01
        self.assertTrue(result)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, PaymentStatus.COMPLETED)


# ---------------------------------------------------------------------------
# Payment safety — DB integrity constraints
# ---------------------------------------------------------------------------

class PaymentIntegrityConstraintTests(TestCase):
    """Model-level integrity guards for duplicate subscriptions and references."""

    def setUp(self) -> None:
        self.reader       = _make_reader()
        self.premium_plan = _make_premium_plan()

    def test_reader_cannot_have_two_effective_subscriptions(self) -> None:
        """DB constraint blocks a second ACTIVE/TRIALING subscription for the same reader."""
        today = date.today()
        Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.ACTIVE,
            started_at=django_tz.now(),
            current_period_start=today,
            current_period_end=today + timedelta(days=30),
        )

        with self.assertRaises(IntegrityError):
            Subscription.objects.create(
                reader=self.reader,
                plan=self.premium_plan,
                status=SubscriptionStatus.TRIALING,
                started_at=django_tz.now(),
                current_period_start=today,
                current_period_end=today + timedelta(days=30),
            )

    def test_paynow_reference_must_be_unique_when_present(self) -> None:
        """DB constraint blocks duplicate non-blank Paynow references."""
        today = date.today()
        subscription = Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.TRIALING,
            started_at=django_tz.now(),
            current_period_start=today,
            current_period_end=today + timedelta(days=30),
        )
        Payment.objects.create(
            subscription=subscription,
            amount_usd=Decimal("2.00"),
            currency="USD",
            payment_method=PaymentMethod.ECOCASH,
            status=PaymentStatus.PENDING,
            paynow_reference="PAYNOW-DUP-001",
            paynow_poll_url="https://www.paynow.co.zw/interface/CheckPayment/?guid=dup1",
        )

        with self.assertRaises(IntegrityError):
            Payment.objects.create(
                subscription=subscription,
                amount_usd=Decimal("2.00"),
                currency="USD",
                payment_method=PaymentMethod.ECOCASH,
                status=PaymentStatus.PENDING,
                paynow_reference="PAYNOW-DUP-001",
                paynow_poll_url="https://www.paynow.co.zw/interface/CheckPayment/?guid=dup2",
            )


# ---------------------------------------------------------------------------
# Payment safety — duplicate subscription guard
# ---------------------------------------------------------------------------

class DuplicateSubscriptionGuardTests(TestCase):
    """
    POST /api/v1/subscriptions/subscribe/ must reject if reader already has
    an ACTIVE or TRIALING subscription.
    """

    def setUp(self) -> None:
        self.client       = APIClient()
        self.reader       = _make_reader()
        self.premium_plan = _make_premium_plan()

    def test_duplicate_active_subscription_returns_409(self) -> None:
        """A second subscribe attempt while ACTIVE returns 409 Conflict."""
        _make_active_subscription(self.reader, self.premium_plan)
        headers = _reader_auth_headers(self.reader)
        response = self.client.post(
            "/api/v1/subscriptions/subscribe/",
            {"plan_slug": "free", "payment_method": PaymentMethod.BANK_CARD},
            format="json",
            **headers,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_duplicate_trialing_subscription_returns_409(self) -> None:
        """A second subscribe attempt while a TRIALING sub exists returns 409."""
        today = date.today()
        Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.TRIALING,
            started_at=django_tz.now(),
            current_period_start=today,
            current_period_end=today + timedelta(days=30),
        )
        headers = _reader_auth_headers(self.reader)
        response = self.client.post(
            "/api/v1/subscriptions/subscribe/",
            {"plan_slug": "free", "payment_method": PaymentMethod.BANK_CARD},
            format="json",
            **headers,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_expired_subscription_allows_new_subscribe(self) -> None:
        """An EXPIRED subscription does not block a new subscribe attempt."""
        yesterday = date.today() - timedelta(days=1)
        Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.EXPIRED,
            started_at=django_tz.now(),
            current_period_start=yesterday - timedelta(days=30),
            current_period_end=yesterday,
        )
        headers = _reader_auth_headers(self.reader)
        response = self.client.post(
            "/api/v1/subscriptions/subscribe/",
            {"plan_slug": "free", "payment_method": PaymentMethod.BANK_CARD},
            format="json",
            **headers,
        )
        # Free plan activates immediately — must not be 409.
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Payment safety — OneMoney provider
# ---------------------------------------------------------------------------

class OneMoneyProviderTests(TestCase):
    """
    EcoCash and OneMoney subscriptions must use distinct Paynow provider strings.
    """

    def setUp(self) -> None:
        self.client       = APIClient()
        self.reader       = _make_reader()
        self.premium_plan = _make_premium_plan()

    @patch("subscriptions.views.PaynowClient")
    def test_onemoney_uses_onemoney_provider(self, mock_paynow_cls: MagicMock) -> None:
        """OneMoney payment passes 'onemoney' as provider to Paynow SDK."""
        mock_client = MagicMock()
        mock_client.initiate_mobile_payment.return_value = {
            "ok": True,
            "reference": "PAYNOW-OM-001",
            "poll_url": "https://www.paynow.co.zw/interface/CheckPayment/?guid=om",
            "redirect_url": "",
            "error": "",
        }
        mock_paynow_cls.return_value = mock_client

        headers = _reader_auth_headers(self.reader)
        self.client.post(
            "/api/v1/subscriptions/subscribe/",
            {
                "plan_slug":      "premium",
                "payment_method": PaymentMethod.ONEMONEY,
                "phone_number":   "0731234567",
            },
            format="json",
            **headers,
        )

        # Confirm the service layer passed ONEMONEY down to the client.
        mock_client.initiate_mobile_payment.assert_called_once()
        call_kwargs = mock_client.initiate_mobile_payment.call_args
        passed_method = call_kwargs.kwargs.get(
            "payment_method",
            call_kwargs.args[4] if len(call_kwargs.args) > 4 else None,
        )
        self.assertEqual(passed_method.upper(), PaymentMethod.ONEMONEY.upper())

    def _make_paynow_client_with_mock_sdk(self) -> tuple:
        """
        Construct a PaynowClient without invoking __init__ (which imports the
        ``paynow`` package that is not installed in the test environment) and
        inject a mock SDK instance.  Returns (client, mock_sdk).
        """
        from subscriptions.paynow_client import PaynowClient

        mock_sdk = MagicMock()
        mock_sdk.create_payment.return_value = MagicMock()
        mock_sdk.send_mobile.return_value = MagicMock(
            success=True, paynow_reference="REF", poll_url="https://paynow/poll"
        )
        client = PaynowClient.__new__(PaynowClient)
        client._paynow = mock_sdk
        return client, mock_sdk

    def test_paynow_client_passes_onemoney_string_to_sdk(self) -> None:
        """PaynowClient.initiate_mobile_payment sends 'onemoney' to the SDK."""
        client, mock_sdk = self._make_paynow_client_with_mock_sdk()
        client.initiate_mobile_payment(
            amount_usd=2.00,
            phone="0731234567",
            email="reader@test.com",
            reference="sub-test",
            payment_method="ONEMONEY",
        )
        call_args = mock_sdk.send_mobile.call_args
        provider_arg = call_args.args[2] if len(call_args.args) > 2 else call_args.kwargs.get("method")
        self.assertEqual(provider_arg, "onemoney")

    def test_paynow_client_passes_ecocash_string_to_sdk(self) -> None:
        """PaynowClient.initiate_mobile_payment sends 'ecocash' for EcoCash."""
        client, mock_sdk = self._make_paynow_client_with_mock_sdk()
        client.initiate_mobile_payment(
            amount_usd=2.00,
            phone="0771234567",
            email="reader@test.com",
            reference="sub-test",
            payment_method="ECOCASH",
        )
        call_args = mock_sdk.send_mobile.call_args
        provider_arg = call_args.args[2] if len(call_args.args) > 2 else call_args.kwargs.get("method")
        self.assertEqual(provider_arg, "ecocash")

    def test_paynow_client_poll_logs_do_not_expose_poll_url_or_reference(self) -> None:
        """Client polling logs must not contain the raw poll URL or reference."""
        client, mock_sdk = self._make_paynow_client_with_mock_sdk()
        mock_sdk.check_transaction_status.return_value = MagicMock(
            paid=True,
            paynow_reference="PAYNOW-POLL-SECRET",
            amount=2.00,
            status="Paid",
        )
        secret_poll_url = "https://www.paynow.co.zw/interface/CheckPayment/?guid=secret-guid"

        with self.assertLogs("subscriptions.paynow_client", level="INFO") as captured:
            result = client.check_payment_status(secret_poll_url)

        self.assertTrue(result["ok"])
        output = "\n".join(captured.output)
        self.assertNotIn(secret_poll_url, output)
        self.assertNotIn("PAYNOW-POLL-SECRET", output)


# ---------------------------------------------------------------------------
# Payment safety — cancel_at_period_end ordering fix
# ---------------------------------------------------------------------------

class CancelAtPeriodEndTaskTests(TestCase):
    """
    check_expired_subscriptions must finalise cancel_at_period_end subscriptions
    as CANCELLED, not EXPIRED.
    """

    def setUp(self) -> None:
        self.reader       = _make_reader()
        self.premium_plan = _make_premium_plan()

    def test_cancel_at_period_end_finalised_as_cancelled(self) -> None:
        """Subscriptions with cancel_at_period_end=True end up CANCELLED not EXPIRED."""
        from subscriptions.tasks import check_expired_subscriptions

        yesterday = date.today() - timedelta(days=1)
        sub = Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.ACTIVE,
            cancel_at_period_end=True,
            started_at=django_tz.now(),
            current_period_start=yesterday - timedelta(days=30),
            current_period_end=yesterday,
        )

        check_expired_subscriptions()

        sub.refresh_from_db()
        self.assertEqual(sub.status, SubscriptionStatus.CANCELLED)

    def test_ordinary_expired_not_affected_by_cancel_branch(self) -> None:
        """Subscriptions without cancel_at_period_end are still marked EXPIRED."""
        from subscriptions.tasks import check_expired_subscriptions

        yesterday = date.today() - timedelta(days=1)
        sub = Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.ACTIVE,
            cancel_at_period_end=False,
            started_at=django_tz.now(),
            current_period_start=yesterday - timedelta(days=30),
            current_period_end=yesterday,
        )

        check_expired_subscriptions()

        sub.refresh_from_db()
        self.assertEqual(sub.status, SubscriptionStatus.EXPIRED)

    def test_cancel_at_period_end_finalisation_invalidates_reader_cache(self) -> None:
        """Finalising a period-end cancellation must evict cached paywall access."""
        from subscriptions.tasks import check_expired_subscriptions

        yesterday = date.today() - timedelta(days=1)
        sub = Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.ACTIVE,
            cancel_at_period_end=True,
            started_at=django_tz.now(),
            current_period_start=yesterday - timedelta(days=30),
            current_period_end=yesterday,
        )
        cache_key = f"subscriptions:reader:{self.reader.id}:status"
        cache.set(cache_key, True, 300)

        check_expired_subscriptions()

        sub.refresh_from_db()
        self.assertEqual(sub.status, SubscriptionStatus.CANCELLED)
        self.assertIsNone(cache.get(cache_key))


# ---------------------------------------------------------------------------
# Renewal reminder scheduling
# ---------------------------------------------------------------------------

class RenewalReminderQueueTests(TestCase):
    """queue_renewal_reminders should enqueue only due active subscriptions."""

    def setUp(self) -> None:
        self.reader       = _make_reader()
        self.premium_plan = _make_premium_plan()

    @patch("subscriptions.tasks.send_renewal_reminder")
    def test_queue_renewal_reminders_enqueues_only_due_active_subscriptions(
        self, mock_reminder_task: MagicMock
    ) -> None:
        """Only ACTIVE, non-cancelling subscriptions ending in 3 days are queued."""
        from subscriptions.tasks import queue_renewal_reminders

        target_date = date.today() + timedelta(days=3)
        eligible = Subscription.objects.create(
            reader=self.reader,
            plan=self.premium_plan,
            status=SubscriptionStatus.ACTIVE,
            started_at=django_tz.now(),
            current_period_start=date.today() - timedelta(days=27),
            current_period_end=target_date,
        )
        Subscription.objects.create(
            reader=_make_reader("cancel@test.com", "cancelreader"),
            plan=self.premium_plan,
            status=SubscriptionStatus.ACTIVE,
            cancel_at_period_end=True,
            started_at=django_tz.now(),
            current_period_start=date.today() - timedelta(days=27),
            current_period_end=target_date,
        )
        Subscription.objects.create(
            reader=_make_reader("expired@test.com", "expiredreader"),
            plan=self.premium_plan,
            status=SubscriptionStatus.EXPIRED,
            started_at=django_tz.now(),
            current_period_start=date.today() - timedelta(days=30),
            current_period_end=target_date,
        )

        queue_renewal_reminders()

        mock_reminder_task.delay.assert_called_once_with(str(eligible.id))


# ---------------------------------------------------------------------------
# Scheduler configuration
# ---------------------------------------------------------------------------

class SubscriptionLifecycleScheduleTests(TestCase):
    """Subscription lifecycle tasks must be present in Celery Beat config."""

    def test_celery_beat_schedule_includes_subscription_lifecycle_tasks(self) -> None:
        """Beat config includes expiry and renewal reminder tasks."""
        schedule = settings.CELERY_BEAT_SCHEDULE

        self.assertIn("subscriptions-check-expired-daily", schedule)
        self.assertEqual(
            schedule["subscriptions-check-expired-daily"]["task"],
            "subscriptions.tasks.check_expired_subscriptions",
        )
        self.assertIn("subscriptions-queue-renewal-reminders-daily", schedule)
        self.assertEqual(
            schedule["subscriptions-queue-renewal-reminders-daily"]["task"],
            "subscriptions.tasks.queue_renewal_reminders",
        )
