from unittest.mock import call, patch

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


# ---------------------------------------------------------------------------
# Breaking-news signal — prior-state detection
# ---------------------------------------------------------------------------

def _push_was_scheduled(mock_commit) -> bool:
    """
    Return True if our breaking-news _push callback was registered with
    on_commit.

    Both notifications.signals and core.signals call transaction.on_commit
    on article saves (core schedules a sitemap ping).  Patching the shared
    transaction module means both closures appear in mock_commit.call_args_list.
    We discriminate by qualname: our callback is always named
    'send_breaking_news_notification.<locals>._push'.
    """
    return any(
        "_push" in getattr(c.args[0], "__qualname__", "")
        for c in mock_commit.call_args_list
    )


class BreakingNewsSignalTests(TestCase):
    """
    Verify send_breaking_news_notification fires exactly on False→True
    transitions and stays quiet for no-op re-saves or non-breaking updates.

    Uses TestCase (not TransactionTestCase) so on_commit callbacks never
    actually execute — we inspect what was *registered* with on_commit
    rather than what ran.
    """

    def setUp(self):
        self.author = make_user("signal_author", role="author")

    def test_false_to_true_transition_queues_notification(self):
        """
        The bug: post_save queried the DB after save and always read
        is_breaking=True, so it treated every False→True transition as a
        no-op and never queued a notification.  After the fix, the _push
        callback must be registered with on_commit.
        """
        article = make_article(self.author, title="Transition Article", is_breaking=False)

        with patch("notifications.signals.transaction.on_commit") as mock_commit:
            article.is_breaking = True
            article.save(update_fields=["is_breaking", "updated_at"])

        self.assertTrue(
            _push_was_scheduled(mock_commit),
            "Expected _push to be registered with on_commit for False→True transition",
        )

    def test_already_breaking_save_does_not_re_queue(self):
        """
        Saving an article that was already is_breaking=True must not schedule
        a second _push notification callback.
        """
        article = make_article(self.author, title="Already Breaking", is_breaking=True)

        with patch("notifications.signals.transaction.on_commit") as mock_commit:
            article.title = "Already Breaking (edited)"
            article.save(update_fields=["title", "updated_at"])

        self.assertFalse(
            _push_was_scheduled(mock_commit),
            "Expected no _push for a re-save of an already-breaking article",
        )

    def test_non_breaking_update_does_not_queue(self):
        """Updating a non-breaking article's title must not register _push."""
        article = make_article(self.author, title="Normal Article", is_breaking=False)

        with patch("notifications.signals.transaction.on_commit") as mock_commit:
            article.title = "Normal Article (updated)"
            article.save(update_fields=["title", "updated_at"])

        self.assertFalse(
            _push_was_scheduled(mock_commit),
            "Expected no _push for a non-breaking article save",
        )

    def test_true_to_false_transition_does_not_queue(self):
        """Clearing is_breaking must not register a _push callback."""
        article = make_article(self.author, title="Was Breaking", is_breaking=True)

        with patch("notifications.signals.transaction.on_commit") as mock_commit:
            article.is_breaking = False
            article.save(update_fields=["is_breaking", "updated_at"])

        self.assertFalse(
            _push_was_scheduled(mock_commit),
            "Expected no _push when is_breaking is cleared",
        )

    def test_new_article_created_breaking_queues_notification(self):
        """
        A brand-new article created with is_breaking=True is treated as a
        False→True transition and must register _push.
        """
        with patch("notifications.signals.transaction.on_commit") as mock_commit:
            make_article(self.author, title="Born Breaking", is_breaking=True)

        self.assertTrue(
            _push_was_scheduled(mock_commit),
            "Expected _push for a new article created with is_breaking=True",
        )

    def test_new_article_created_not_breaking_does_not_queue(self):
        """Creating a non-breaking article must not register _push."""
        with patch("notifications.signals.transaction.on_commit") as mock_commit:
            make_article(self.author, title="Born Normal", is_breaking=False)

        self.assertFalse(
            _push_was_scheduled(mock_commit),
            "Expected no _push for a new article created with is_breaking=False",
        )