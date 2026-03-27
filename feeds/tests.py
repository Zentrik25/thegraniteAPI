from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from articles.models import Article, Category, PublishStatus

User = get_user_model()


def make_user(username="reporter"):
    return User.objects.create_user(
        username=username,
        password="testpass123",
        email=f"{username}@granite.co.zw",
        role="author",
    )


def make_article(author, title="Test Article", status=PublishStatus.PUBLISHED, **kwargs):
    return Article.objects.create(
        title=title,
        body="Body content.",
        author=author,
        status=status,
        **kwargs,
    )


class LatestRSSFeedTests(TestCase):

    def setUp(self):
        self.user    = make_user()
        self.cat     = Category.objects.create(name="News")
        self.article = make_article(self.user, title="Latest Article", category=self.cat)

    def test_returns_200(self):
        self.assertEqual(self.client.get("/rss/").status_code, 200)

    def test_content_type_is_xml(self):
        self.assertIn("xml", self.client.get("/rss/")["Content-Type"])

    def test_contains_published_article(self):
        self.assertContains(self.client.get("/rss/"), "Latest Article")

    def test_excludes_draft_articles(self):
        make_article(self.user, title="Draft Article", status=PublishStatus.DRAFT)
        self.assertNotContains(self.client.get("/rss/"), "Draft Article")

    def test_excludes_archived_articles(self):
        make_article(self.user, title="Archived Article", status=PublishStatus.ARCHIVED)
        self.assertNotContains(self.client.get("/rss/"), "Archived Article")

    def test_contains_author_byline(self):
        self.assertContains(self.client.get("/rss/"), self.user.byline)


class CategoryRSSFeedTests(TestCase):

    def setUp(self):
        self.user    = make_user("reporter2")
        self.cat     = Category.objects.create(name="Sport")
        self.other   = Category.objects.create(name="Business")
        self.article = make_article(self.user, title="Sport Article", category=self.cat)
        make_article(self.user, title="Business Article", category=self.other)

    def test_returns_200(self):
        self.assertEqual(self.client.get(f"/rss/{self.cat.slug}/").status_code, 200)

    def test_contains_category_article(self):
        self.assertContains(self.client.get(f"/rss/{self.cat.slug}/"), "Sport Article")

    def test_excludes_other_category_articles(self):
        self.assertNotContains(self.client.get(f"/rss/{self.cat.slug}/"), "Business Article")

    def test_unknown_category_returns_404(self):
        self.assertEqual(self.client.get("/rss/does-not-exist/").status_code, 404)

    def test_title_includes_category_name(self):
        self.assertContains(self.client.get(f"/rss/{self.cat.slug}/"), "Sport")


class SitemapTests(TestCase):

    def setUp(self):
        self.user    = make_user("reporter3")
        self.cat     = Category.objects.create(name="Politics")
        self.article = make_article(self.user, title="Sitemap Article", category=self.cat)

    def test_sitemap_returns_200(self):
        self.assertEqual(self.client.get("/sitemap.xml").status_code, 200)

    def test_sitemap_is_xml(self):
        self.assertIn("xml", self.client.get("/sitemap.xml")["Content-Type"])

    def test_sitemap_contains_article_slug(self):
        self.assertContains(self.client.get("/sitemap.xml"), self.article.slug)

    def test_sitemap_contains_category_slug(self):
        self.assertContains(self.client.get("/sitemap.xml"), self.cat.slug)

    def test_sitemap_excludes_drafts(self):
        draft = make_article(self.user, title="Draft", status=PublishStatus.DRAFT)
        self.assertNotContains(self.client.get("/sitemap.xml"), draft.slug)


class GoogleNewsSitemapTests(TestCase):

    def setUp(self):
        self.user = make_user("reporter4")
        self.cat  = Category.objects.create(name="Economy")

    def test_news_sitemap_returns_200(self):
        self.assertEqual(self.client.get("/news-sitemap.xml").status_code, 200)

    def test_news_sitemap_contains_recent_article(self):
        recent = make_article(self.user, title="Recent News", category=self.cat)
        self.assertContains(self.client.get("/news-sitemap.xml"), recent.slug)

    def test_news_sitemap_excludes_old_articles(self):
        old = make_article(self.user, title="Old News", category=self.cat)
        old.published_at = timezone.now() - timedelta(hours=49)
        Article.objects.filter(pk=old.pk).update(published_at=old.published_at)
        self.assertNotContains(self.client.get("/news-sitemap.xml"), "old-news")
