from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import caches
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Subscriber

User = get_user_model()


def make_user(username="editor", role="senior_editor"):
    return User.objects.create_user(
        username=username,
        password="testpass123",
        email=f"{username}@granite.co.zw",
        role=role,
    )


def make_subscriber(email="reader@test.com", confirmed=False, source="footer"):
    return Subscriber.objects.create(
        email     = email,
        confirmed = confirmed,
        source    = source,
    )


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class SubscriberModelTests(TestCase):

    def test_subscriber_created_unconfirmed(self):
        s = make_subscriber()
        self.assertFalse(s.confirmed)
        self.assertIsNone(s.confirmed_at)

    def test_confirm_sets_confirmed_true(self):
        s = make_subscriber()
        s.confirm()
        self.assertTrue(s.confirmed)
        self.assertIsNotNone(s.confirmed_at)

    def test_confirm_is_idempotent(self):
        s = make_subscriber(confirmed=True)
        original_confirmed_at = s.confirmed_at
        s.confirm()
        s.refresh_from_db()
        self.assertTrue(s.confirmed)

    def test_unsubscribe_token_unique(self):
        s1 = make_subscriber("a@test.com")
        s2 = make_subscriber("b@test.com")
        self.assertNotEqual(s1.unsubscribe_token, s2.unsubscribe_token)

    def test_confirmation_token_unique(self):
        s1 = make_subscriber("c@test.com")
        s2 = make_subscriber("d@test.com")
        self.assertNotEqual(s1.confirmation_token, s2.confirmation_token)

    def test_email_is_unique(self):
        from django.db import IntegrityError
        make_subscriber("unique@test.com")
        with self.assertRaises(IntegrityError):
            make_subscriber("unique@test.com")

    def test_unsubscribe_deletes_record(self):
        s = make_subscriber("delete@test.com")
        s.unsubscribe()
        self.assertFalse(Subscriber.objects.filter(email="delete@test.com").exists())


# ---------------------------------------------------------------------------
# API — subscribe
# ---------------------------------------------------------------------------

class SubscribeAPITests(APITestCase):

    def setUp(self):
        caches["throttle"].clear()

    def tearDown(self):
        caches["throttle"].clear()

    def test_subscribe_returns_202(self):
        r = self.client.post("/api/v1/newsletter/subscribe/", {
            "email": "new@reader.com",
        })
        self.assertEqual(r.status_code, 202)

    def test_subscribe_creates_unconfirmed_subscriber(self):
        self.client.post("/api/v1/newsletter/subscribe/", {
            "email": "new2@reader.com",
        })
        s = Subscriber.objects.get(email="new2@reader.com")
        self.assertFalse(s.confirmed)

    def test_subscribe_with_source(self):
        self.client.post("/api/v1/newsletter/subscribe/", {
            "email":  "new3@reader.com",
            "source": "article-cta",
        })
        s = Subscriber.objects.get(email="new3@reader.com")
        self.assertEqual(s.source, "article-cta")

    def test_subscribe_duplicate_email_returns_202(self):
        self.client.post("/api/v1/newsletter/subscribe/", {"email": "dup@reader.com"})
        r = self.client.post("/api/v1/newsletter/subscribe/", {"email": "dup@reader.com"})
        self.assertEqual(r.status_code, 202)

    def test_subscribe_invalid_email_returns_400(self):
        r = self.client.post("/api/v1/newsletter/subscribe/", {
            "email": "not-an-email",
        })
        self.assertEqual(r.status_code, 400)

    def test_subscribe_missing_email_returns_400(self):
        r = self.client.post("/api/v1/newsletter/subscribe/", {})
        self.assertEqual(r.status_code, 400)

    def test_subscribe_normalises_email_to_lowercase(self):
        self.client.post("/api/v1/newsletter/subscribe/", {
            "email": "UPPER@READER.COM",
        })
        self.assertTrue(
            Subscriber.objects.filter(email="upper@reader.com").exists()
        )


# ---------------------------------------------------------------------------
# API — confirm
# ---------------------------------------------------------------------------

class ConfirmAPITests(APITestCase):

    def setUp(self):
        self.subscriber = make_subscriber("confirm@reader.com")

    def test_confirm_valid_token_returns_200(self):
        r = self.client.get(
            f"/api/v1/newsletter/confirm/?token={self.subscriber.confirmation_token}"
        )
        self.assertEqual(r.status_code, 200)

    def test_confirm_sets_confirmed_true(self):
        self.client.get(
            f"/api/v1/newsletter/confirm/?token={self.subscriber.confirmation_token}"
        )
        self.subscriber.refresh_from_db()
        self.assertTrue(self.subscriber.confirmed)

    def test_confirm_invalid_token_returns_400(self):
        r = self.client.get(
            "/api/v1/newsletter/confirm/?token=00000000-0000-0000-0000-000000000000"
        )
        self.assertEqual(r.status_code, 400)

    def test_confirm_missing_token_returns_400(self):
        r = self.client.get("/api/v1/newsletter/confirm/")
        self.assertEqual(r.status_code, 400)

    def test_confirm_already_confirmed_returns_200(self):
        self.subscriber.confirm()
        r = self.client.get(
            f"/api/v1/newsletter/confirm/?token={self.subscriber.confirmation_token}"
        )
        self.assertEqual(r.status_code, 200)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@test.com",
    SITE_URL="https://api.test",
)
class NewsletterEmailTaskTests(TestCase):

    def setUp(self):
        self.subscriber = make_subscriber("mailtask@reader.com")

    def test_send_confirmation_email_uses_site_url_and_does_not_log_token(self):
        from .tasks import send_confirmation_email

        token = str(self.subscriber.confirmation_token)
        with self.assertLogs("newsletter.tasks", level="INFO") as captured:
            send_confirmation_email(self.subscriber.pk)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["mailtask@reader.com"])
        self.assertIn(
            f"https://api.test/api/v1/newsletter/confirm/?token={token}",
            mail.outbox[0].body,
        )
        self.assertNotIn(token, "\n".join(captured.output))

    def test_send_welcome_email_sends_plain_email(self):
        from .tasks import send_welcome_email

        send_welcome_email(self.subscriber.pk)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["mailtask@reader.com"])
        self.assertIn("Welcome to The Granite Post newsletter", mail.outbox[0].subject)


# ---------------------------------------------------------------------------
# API — unsubscribe
# ---------------------------------------------------------------------------

class UnsubscribeAPITests(APITestCase):

    def setUp(self):
        self.subscriber = make_subscriber("unsub@reader.com", confirmed=True)

    def test_unsubscribe_valid_token_returns_200(self):
        r = self.client.post("/api/v1/newsletter/unsubscribe/", {
            "token": str(self.subscriber.unsubscribe_token),
        })
        self.assertEqual(r.status_code, 200)

    def test_unsubscribe_deletes_subscriber(self):
        self.client.post("/api/v1/newsletter/unsubscribe/", {
            "token": str(self.subscriber.unsubscribe_token),
        })
        self.assertFalse(
            Subscriber.objects.filter(email="unsub@reader.com").exists()
        )

    def test_unsubscribe_invalid_token_returns_200(self):
        r = self.client.post("/api/v1/newsletter/unsubscribe/", {
            "token": "00000000-0000-0000-0000-000000000000",
        })
        self.assertEqual(r.status_code, 200)

    def test_unsubscribe_missing_token_returns_400(self):
        r = self.client.post("/api/v1/newsletter/unsubscribe/", {})
        self.assertEqual(r.status_code, 400)


# ---------------------------------------------------------------------------
# API — subscriber list (admin)
# ---------------------------------------------------------------------------

class SubscriberListAPITests(APITestCase):

    def setUp(self):
        self.senior = make_user("senior", "senior_editor")
        self.editor = make_user("editor", "editor")
        make_subscriber("confirmed@test.com", confirmed=True)
        make_subscriber("unconfirmed@test.com", confirmed=False)

    def test_requires_auth(self):
        r = self.client.get("/api/v1/newsletter/subscribers/")
        self.assertEqual(r.status_code, 401)

    def test_editor_cannot_access(self):
        self.client.force_authenticate(self.editor)
        r = self.client.get("/api/v1/newsletter/subscribers/")
        self.assertEqual(r.status_code, 403)

    def test_senior_editor_can_access(self):
        self.client.force_authenticate(self.senior)
        r = self.client.get("/api/v1/newsletter/subscribers/")
        self.assertEqual(r.status_code, 200)

    def test_default_returns_confirmed_only(self):
        self.client.force_authenticate(self.senior)
        r = self.client.get("/api/v1/newsletter/subscribers/")
        emails = [s["email"] for s in r.data["results"]]
        self.assertIn("confirmed@test.com",    emails)
        self.assertNotIn("unconfirmed@test.com", emails)

    def test_filter_unconfirmed(self):
        self.client.force_authenticate(self.senior)
        r = self.client.get("/api/v1/newsletter/subscribers/?confirmed=false")
        emails = [s["email"] for s in r.data["results"]]
        self.assertIn("unconfirmed@test.com", emails)
        self.assertNotIn("confirmed@test.com", emails)

    def test_filter_all(self):
        self.client.force_authenticate(self.senior)
        r = self.client.get("/api/v1/newsletter/subscribers/?confirmed=all")
        self.assertEqual(r.data["total_all"], 2)

    def test_response_includes_totals(self):
        self.client.force_authenticate(self.senior)
        r = self.client.get("/api/v1/newsletter/subscribers/")
        self.assertIn("total_confirmed",   r.data)
        self.assertIn("total_unconfirmed", r.data)
        self.assertIn("total_all",         r.data)

    def test_email_not_exposed_without_auth(self):
        r = self.client.get("/api/v1/newsletter/subscribers/")
        self.assertEqual(r.status_code, 401)
