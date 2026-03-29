from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from articles.models import Article, PublishStatus

from .models import Notification, PushSubscription

User = get_user_model()


def make_user(username="reporter", role="author"):
    return User.objects.create_user(
        username=username,
        password="testpass123",
        email=f"{username}@granite.co.zw",
        role=role,
    )


def make_article(author, title="Test Article", is_breaking=False):
    return Article.objects.create(
        title      = title,
        body       = "Body content.",
        author     = author,
        status     = PublishStatus.PUBLISHED,
        is_breaking = is_breaking,
    )


def make_subscription(endpoint="https://fcm.googleapis.com/test/1", is_active=True):
    return PushSubscription.objects.create(
        endpoint   = endpoint,
        p256dh     = "test_p256dh_key",
        auth       = "test_auth_secret",
        user_agent = "Mozilla/5.0 Test Browser",
        is_active  = is_active,
    )


class PushSubscriptionModelTests(TestCase):

    def test_str_includes_id(self):
        s = make_subscription()
        self.assertIn("PushSubscription", str(s))

    def test_unique_endpoint_enforced(self):
        from django.db import IntegrityError
        make_subscription("https://fcm.googleapis.com/unique/1")
        with self.assertRaises(IntegrityError):
            make_subscription("https://fcm.googleapis.com/unique/1")

    def test_default_is_active_true(self):
        s = make_subscription("https://fcm.googleapis.com/test/2")
        self.assertTrue(s.is_active)


class PushSubscribeAPITests(APITestCase):

    def setUp(self):
        caches["throttle"].clear()

    def test_subscribe_returns_201(self):
        r = self.client.post("/api/v1/notifications/subscribe/", {
            "endpoint": "https://fcm.googleapis.com/test/sub1",
            "p256dh":   "test_key",
            "auth":     "test_auth",
        })
        self.assertEqual(r.status_code, 201)

    def test_subscribe_creates_subscription(self):
        self.client.post("/api/v1/notifications/subscribe/", {
            "endpoint": "https://fcm.googleapis.com/test/sub2",
            "p256dh":   "test_key",
            "auth":     "test_auth",
        })
        self.assertTrue(
            PushSubscription.objects.filter(
                endpoint="https://fcm.googleapis.com/test/sub2"
            ).exists()
        )

    def test_subscribe_reactivates_inactive(self):
        sub = make_subscription(
            "https://fcm.googleapis.com/test/sub3",
            is_active=False,
        )
        self.client.post("/api/v1/notifications/subscribe/", {
            "endpoint": "https://fcm.googleapis.com/test/sub3",
            "p256dh":   "new_key",
            "auth":     "new_auth",
        })
        sub.refresh_from_db()
        self.assertTrue(sub.is_active)

    def test_subscribe_invalid_endpoint_returns_400(self):
        r = self.client.post("/api/v1/notifications/subscribe/", {
            "endpoint": "http://not-https.com/push",
            "p256dh":   "test_key",
            "auth":     "test_auth",
        })
        self.assertEqual(r.status_code, 400)

    def test_subscribe_missing_fields_returns_400(self):
        r = self.client.post("/api/v1/notifications/subscribe/", {
            "endpoint": "https://fcm.googleapis.com/test/sub4",
        })
        self.assertEqual(r.status_code, 400)

    def test_subscribe_no_auth_required(self):
        r = self.client.post("/api/v1/notifications/subscribe/", {
            "endpoint": "https://fcm.googleapis.com/test/sub5",
            "p256dh":   "test_key",
            "auth":     "test_auth",
        })
        self.assertIn(r.status_code, [200, 201])


class PushUnsubscribeAPITests(APITestCase):

    def setUp(self):
        caches["throttle"].clear()

    def test_unsubscribe_deactivates_subscription(self):
        sub = make_subscription("https://fcm.googleapis.com/unsub/1")
        self.client.post("/api/v1/notifications/unsubscribe/", {
            "endpoint": "https://fcm.googleapis.com/unsub/1",
        })
        sub.refresh_from_db()
        self.assertFalse(sub.is_active)

    def test_unsubscribe_missing_endpoint_returns_400(self):
        r = self.client.post("/api/v1/notifications/unsubscribe/", {})
        self.assertEqual(r.status_code, 400)

    def test_unsubscribe_unknown_endpoint_returns_200(self):
        r = self.client.post("/api/v1/notifications/unsubscribe/", {
            "endpoint": "https://fcm.googleapis.com/unknown/1",
        })
        self.assertEqual(r.status_code, 200)


class VapidPublicKeyAPITests(APITestCase):

    def test_vapid_key_endpoint_returns_200_or_503(self):
        r = self.client.get("/api/v1/notifications/vapid-public-key/")
        self.assertIn(r.status_code, [200, 503])

    def test_vapid_key_is_public(self):
        r = self.client.get("/api/v1/notifications/vapid-public-key/")
        self.assertIn(r.status_code, [200, 503])


class NotificationHistoryAPITests(APITestCase):

    def setUp(self):
        self.editor = make_user("notif_editor", role="editor")
        self.author = make_user("notif_author", role="author")
        self.user   = make_user("notif_user",   role="contributor")

        Notification.objects.create(
            title         = "Breaking: Test Notification",
            body          = "Test body",
            url           = "/articles/test/",
            sent_count    = 100,
            success_count = 95,
            failed_count  = 5,
        )

    def test_history_requires_auth(self):
        r = self.client.get("/api/v1/notifications/history/")
        self.assertEqual(r.status_code, 401)

    def test_contributor_cannot_access(self):
        self.client.force_authenticate(self.user)
        r = self.client.get("/api/v1/notifications/history/")
        self.assertEqual(r.status_code, 403)

    def test_editor_can_access(self):
        self.client.force_authenticate(self.editor)
        r = self.client.get("/api/v1/notifications/history/")
        self.assertEqual(r.status_code, 200)

    def test_response_has_notification_fields(self):
        self.client.force_authenticate(self.editor)
        r = self.client.get("/api/v1/notifications/history/")
        self.assertEqual(r.status_code, 200)
        if r.data["results"]:
            entry = r.data["results"][0]
            for field in (
                "id", "title", "body", "sent_count",
                "success_count", "failed_count", "sent_at",
            ):
                self.assertIn(field, entry)

    def test_history_shows_sent_stats(self):
        self.client.force_authenticate(self.editor)
        r = self.client.get("/api/v1/notifications/history/")
        entry = r.data["results"][0]
        self.assertEqual(entry["sent_count"],    100)
        self.assertEqual(entry["success_count"], 95)
        self.assertEqual(entry["failed_count"],  5)