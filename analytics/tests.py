from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from articles.models import Article, Category, PublishStatus

from .models import ArticleView

User = get_user_model()


def make_user(username="reporter", role="author"):
    return User.objects.create_user(
        username=username,
        password="testpass123",
        email=f"{username}@granite.co.zw",
        role=role,
    )


def make_article(author, title="Test Article", art_status=PublishStatus.PUBLISHED):
    return Article.objects.create(
        title=title,
        body="Body content.",
        author=author,
        status=art_status,
    )


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class ArticleViewModelTests(TestCase):

    def test_hash_ip_returns_64_char_hex(self):
        h = ArticleView.hash_ip("192.168.1.1")
        self.assertEqual(len(h), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))

    def test_hash_ip_same_ip_same_hash(self):
        self.assertEqual(
            ArticleView.hash_ip("10.0.0.1"),
            ArticleView.hash_ip("10.0.0.1"),
        )

    def test_hash_ip_different_ips_different_hashes(self):
        self.assertNotEqual(
            ArticleView.hash_ip("10.0.0.1"),
            ArticleView.hash_ip("10.0.0.2"),
        )

    def test_hash_session_empty_returns_empty(self):
        self.assertEqual(ArticleView.hash_session(""), "")
        self.assertEqual(ArticleView.hash_session(None), "")

    def test_hash_session_returns_64_char_hex(self):
        h = ArticleView.hash_session("abc123sessionkey")
        self.assertEqual(len(h), 64)


# ---------------------------------------------------------------------------
# Signal — view count increment
# ---------------------------------------------------------------------------

class ViewCountSignalTests(TestCase):

    def setUp(self):
        self.user    = make_user()
        self.article = make_article(self.user)

    def test_view_count_increments_on_new_view(self):
        self.assertEqual(self.article.view_count, 0)
        ArticleView.objects.create(
            article     = self.article,
            ip_hash     = ArticleView.hash_ip("1.2.3.4"),
            viewed_at   = timezone.now(),
            viewed_date = timezone.now().date(),
        )
        self.article.refresh_from_db()
        self.assertEqual(self.article.view_count, 1)

    def test_view_count_does_not_increment_on_update(self):
        view = ArticleView.objects.create(
            article     = self.article,
            ip_hash     = ArticleView.hash_ip("1.2.3.4"),
            viewed_at   = timezone.now(),
            viewed_date = timezone.now().date(),
        )
        self.article.refresh_from_db()
        self.assertEqual(self.article.view_count, 1)

        # Update the view record — should NOT increment again.
        view.session_hash = "updated"
        view.save()
        self.article.refresh_from_db()
        self.assertEqual(self.article.view_count, 1)

    def test_duplicate_view_raises_integrity_error(self):
        from django.db import IntegrityError
        today = timezone.now().date()
        ip    = ArticleView.hash_ip("1.2.3.4")

        ArticleView.objects.create(
            article     = self.article,
            ip_hash     = ip,
            viewed_at   = timezone.now(),
            viewed_date = today,
        )
        with self.assertRaises(IntegrityError):
            ArticleView.objects.create(
                article     = self.article,
                ip_hash     = ip,
                viewed_at   = timezone.now(),
                viewed_date = today,
            )


# ---------------------------------------------------------------------------
# API — record view
# ---------------------------------------------------------------------------

class RecordViewAPITests(APITestCase):

    def setUp(self):
        self.user    = make_user()
        self.article = make_article(self.user)
        self.url     = f"/api/v1/analytics/articles/{self.article.slug}/view/"
        # Clear throttle cache so each test starts with a clean slate.
        caches["throttle"].clear()

    def tearDown(self):
        caches["throttle"].clear()

    def test_post_records_view_returns_200(self):
        r = self.client.post(self.url)
        self.assertEqual(r.status_code, 200)

    def test_post_returns_recorded_true_on_first_view(self):
        r = self.client.post(self.url)
        self.assertTrue(r.data["recorded"])

    def test_post_returns_recorded_false_on_duplicate(self):
        self.client.post(self.url)
        r = self.client.post(self.url)
        self.assertFalse(r.data["recorded"])

    def test_post_returns_view_count(self):
        r = self.client.post(self.url)
        self.assertIn("view_count", r.data)
        self.assertEqual(r.data["view_count"], 1)

    def test_post_increments_view_count_on_article(self):
        self.client.post(self.url)
        self.article.refresh_from_db()
        self.assertEqual(self.article.view_count, 1)

    def test_draft_article_returns_404(self):
        draft = make_article(self.user, title="Draft", art_status=PublishStatus.DRAFT)
        r = self.client.post(f"/api/v1/analytics/articles/{draft.slug}/view/")
        self.assertEqual(r.status_code, 404)

    def test_staff_view_not_counted(self):
        staff = make_user("staff", role="admin")
        self.client.force_authenticate(staff)
        r = self.client.post(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["recorded"])
        self.article.refresh_from_db()
        self.assertEqual(self.article.view_count, 0)

    def test_unknown_slug_returns_404(self):
        r = self.client.post("/api/v1/analytics/articles/does-not-exist/view/")
        self.assertEqual(r.status_code, 404)


# ---------------------------------------------------------------------------
# API — trending
# ---------------------------------------------------------------------------

class TrendingAPITests(APITestCase):

    def setUp(self):
        self.user = make_user("trend_reporter")
        self.cat  = Category.objects.create(name="Trending News")
        self.a1   = make_article(self.user, title="Popular Article")
        self.a2   = make_article(self.user, title="Less Popular Article")

        today = timezone.now().date()

        # a1 gets 5 views from different IPs.
        for i in range(5):
            ArticleView.objects.create(
                article     = self.a1,
                ip_hash     = ArticleView.hash_ip(f"1.2.3.{i}"),
                viewed_at   = timezone.now(),
                viewed_date = today,
            )
        # a2 gets 2 views.
        for i in range(2):
            ArticleView.objects.create(
                article     = self.a2,
                ip_hash     = ArticleView.hash_ip(f"2.2.3.{i}"),
                viewed_at   = timezone.now(),
                viewed_date = today,
            )

    def test_trending_returns_200(self):
        r = self.client.get("/api/v1/analytics/trending/")
        self.assertEqual(r.status_code, 200)

    def test_trending_returns_list(self):
        r = self.client.get("/api/v1/analytics/trending/")
        self.assertIsInstance(r.data, list)

    def test_trending_ordered_by_views_descending(self):
        r = self.client.get("/api/v1/analytics/trending/")
        self.assertGreaterEqual(len(r.data), 2)
        self.assertGreater(
            r.data[0]["view_count"],
            r.data[1]["view_count"],
        )

    def test_trending_rank_starts_at_one(self):
        r = self.client.get("/api/v1/analytics/trending/")
        self.assertEqual(r.data[0]["rank"], 1)

    def test_trending_week_period(self):
        r = self.client.get("/api/v1/analytics/trending/?period=week")
        self.assertEqual(r.status_code, 200)

    def test_trending_invalid_period_defaults_to_day(self):
        r = self.client.get("/api/v1/analytics/trending/?period=invalid")
        self.assertEqual(r.status_code, 200)

    def test_trending_most_viewed_is_first(self):
        r = self.client.get("/api/v1/analytics/trending/")
        first = r.data[0]
        self.assertEqual(first["view_count"], 5)
        self.assertEqual(first["article"]["slug"], self.a1.slug)
