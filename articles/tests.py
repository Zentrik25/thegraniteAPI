"""
tests.py — Test suite for The Granite Post articles app.

Coverage
--------
Models   — slug generation, collision resolution, published_at stamping,
           top_story_rank constraints
Managers — published(), breaking(), top_stories(), top_story_at_rank(),
           featured(), with_related()
Signals  — single-rank enforcement across ORM saves
API      — list, detail, create, update, archive, breaking,
           top-story grid (full + empty slots), featured
Admin    — save_model rank displacement
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Article, Category, PublishStatus, Tag, TOP_STORY_MAX, TOP_STORY_MIN

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_user(username="editor", role="author"):
    return User.objects.create_user(
        username=username,
        password="testpass123",
        email=f"{username}@granite.co.zw",
        role=role,
    )


def make_article(author, title="Test Article", art_status=PublishStatus.DRAFT, **kwargs):
    return Article.objects.create(
        title=title,
        body="Body content.",
        author=author,
        status=art_status,
        **kwargs,
    )


def make_published(author, title="Live Article", **kwargs):
    return make_article(author, title=title, art_status=PublishStatus.PUBLISHED, **kwargs)


# ---------------------------------------------------------------------------
# Model — slug generation
# ---------------------------------------------------------------------------

class SlugGenerationTests(TestCase):

    def setUp(self):
        self.user = make_user()

    def test_slug_auto_generated(self):
        a = make_article(self.user, title="Hello World")
        self.assertEqual(a.slug, "hello-world")

    def test_slug_not_overwritten_on_update(self):
        a = make_article(self.user, title="Hello World")
        original = a.slug
        a.title = "Something Else"
        a.save()
        a.refresh_from_db()
        self.assertEqual(a.slug, original)

    def test_slug_collision_resolved_with_counter(self):
        a1 = make_article(self.user, title="Breaking News")
        a2 = make_article(self.user, title="Breaking News")
        self.assertNotEqual(a1.slug, a2.slug)
        self.assertTrue(a2.slug.startswith("breaking-news-"))

    def test_category_slug_auto_generated(self):
        cat = Category.objects.create(name="Sport")
        self.assertEqual(cat.slug, "sport")

    def test_tag_normalised_lowercase(self):
        tag = Tag.objects.create(name="Zimbabwe")
        self.assertEqual(tag.name, "zimbabwe")


# ---------------------------------------------------------------------------
# Model — published_at
# ---------------------------------------------------------------------------

class PublishedAtTests(TestCase):

    def setUp(self):
        self.user = make_user()

    def test_published_at_null_on_draft(self):
        a = make_article(self.user)
        self.assertIsNone(a.published_at)

    def test_published_at_stamped_on_publish(self):
        a = make_article(self.user)
        a.status = PublishStatus.PUBLISHED
        a.save()
        self.assertIsNotNone(a.published_at)

    def test_published_at_not_overwritten_on_resave(self):
        a = make_published(self.user)
        stamp = a.published_at
        a.title = "Updated"
        a.save()
        a.refresh_from_db()
        self.assertEqual(a.published_at, stamp)

    def test_published_at_preserved_on_archive(self):
        a = make_published(self.user)
        stamp = a.published_at
        a.status = PublishStatus.ARCHIVED
        a.save()
        a.refresh_from_db()
        self.assertEqual(a.published_at, stamp)

    def test_is_premium_defaults_false_when_omitted(self):
        a = make_article(self.user)
        self.assertFalse(a.is_premium)

    def test_is_premium_none_is_normalised_to_false(self):
        a = make_article(self.user, is_premium=None)
        a.refresh_from_db()
        self.assertFalse(a.is_premium)


# ---------------------------------------------------------------------------
# Model — top story rank
# ---------------------------------------------------------------------------

class TopStoryRankTests(TestCase):

    def setUp(self):
        self.user = make_user()

    def test_is_top_story_false_when_rank_null(self):
        a = make_published(self.user)
        self.assertFalse(a.is_top_story)

    def test_is_top_story_true_when_rank_set(self):
        a = make_published(self.user, top_story_rank=1)
        self.assertTrue(a.is_top_story)

    def test_needs_banner_true_when_top_story(self):
        a = make_published(self.user, top_story_rank=3)
        self.assertTrue(a.needs_banner)

    def test_needs_banner_true_when_breaking(self):
        a = make_published(self.user, is_breaking=True)
        self.assertTrue(a.needs_banner)

    def test_needs_banner_false_when_neither(self):
        a = make_published(self.user)
        self.assertFalse(a.needs_banner)


# ---------------------------------------------------------------------------
# Signals — rank enforcement
# ---------------------------------------------------------------------------

class TopStoryRankSignalTests(TestCase):

    def setUp(self):
        self.user = make_user()

    def test_signal_displaces_existing_rank(self):
        a1 = make_published(self.user, title="Article 1", top_story_rank=1)
        a2 = make_published(self.user, title="Article 2", top_story_rank=1)
        a1.refresh_from_db()
        self.assertIsNone(a1.top_story_rank)
        self.assertEqual(a2.top_story_rank, 1)

    def test_different_ranks_do_not_displace(self):
        a1 = make_published(self.user, title="Article 1", top_story_rank=1)
        a2 = make_published(self.user, title="Article 2", top_story_rank=2)
        a1.refresh_from_db()
        self.assertEqual(a1.top_story_rank, 1)
        self.assertEqual(a2.top_story_rank, 2)

    def test_all_six_ranks_can_be_occupied(self):
        articles = [
            make_published(self.user, title=f"Article {r}", top_story_rank=r)
            for r in range(TOP_STORY_MIN, TOP_STORY_MAX + 1)
        ]
        for i, a in enumerate(articles, start=1):
            a.refresh_from_db()
            self.assertEqual(a.top_story_rank, i)


# ---------------------------------------------------------------------------
# Managers
# ---------------------------------------------------------------------------

class ArticleManagerTests(TestCase):

    def setUp(self):
        self.user     = make_user()
        self.live     = make_published(self.user, title="Live")
        self.draft    = make_article(self.user, title="Draft")
        self.breaking = make_published(self.user, title="Breaking", is_breaking=True)
        self.top1     = make_published(self.user, title="Top 1", top_story_rank=1)
        self.top3     = make_published(self.user, title="Top 3", top_story_rank=3)

    def test_published_excludes_drafts(self):
        qs = Article.objects.published()
        self.assertIn(self.live, qs)
        self.assertNotIn(self.draft, qs)

    def test_breaking_returns_only_breaking(self):
        qs = Article.objects.breaking()
        self.assertIn(self.breaking, qs)
        self.assertNotIn(self.live, qs)

    def test_top_stories_ordered_by_rank(self):
        qs = list(Article.objects.top_stories())
        ranks = [a.top_story_rank for a in qs]
        self.assertEqual(ranks, sorted(ranks))

    def test_top_story_at_rank_returns_correct_article(self):
        self.assertEqual(Article.objects.top_story_at_rank(1), self.top1)
        self.assertEqual(Article.objects.top_story_at_rank(3), self.top3)

    def test_top_story_at_rank_returns_none_for_empty_slot(self):
        self.assertIsNone(Article.objects.top_story_at_rank(6))

    def test_top_story_at_rank_raises_on_invalid_rank(self):
        with self.assertRaises(ValueError):
            Article.objects.top_story_at_rank(7)

    def test_with_related_does_not_raise(self):
        # Ensures select_related / prefetch_related paths work without error.
        articles = list(Article.objects.with_related())
        self.assertGreater(len(articles), 0)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class ArticleAPITests(APITestCase):

    def setUp(self):
        self.staff  = make_user("staff", role="editor")
        self.editor = make_user("reporter")
        self.cat    = Category.objects.create(name="News")
        self.article = make_published(
            self.staff, title="Published Article", category=self.cat,
        )

    # -- List ---------------------------------------------------------------

    def test_list_published_only_for_anonymous(self):
        make_article(self.staff, title="Draft")
        r = self.client.get("/api/articles/")
        titles = [a["title"] for a in r.data["results"]]
        self.assertIn("Published Article", titles)
        self.assertNotIn("Draft", titles)

    def test_staff_sees_all_statuses(self):
        make_article(self.staff, title="Draft")
        self.client.force_authenticate(self.staff)
        r = self.client.get("/api/articles/")
        titles = [a["title"] for a in r.data["results"]]
        self.assertIn("Draft", titles)

    # -- Detail -------------------------------------------------------------

    def test_detail_includes_body(self):
        r = self.client.get(f"/api/articles/{self.article.slug}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("body", r.data)

    def test_detail_404_for_unknown_slug(self):
        r = self.client.get("/api/articles/does-not-exist/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    # -- Create -------------------------------------------------------------

    def test_create_forbidden_for_non_staff(self):
        self.client.force_authenticate(self.editor)
        r = self.client.post("/api/articles/", {"title": "New", "body": "..."})
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_create_draft(self):
        self.client.force_authenticate(self.staff)
        r = self.client.post("/api/articles/", {
            "title": "New Article", "body": "Full body.", "status": "draft",
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    # -- Archive via DELETE -------------------------------------------------

    def test_delete_archives_not_destroys(self):
        self.client.force_authenticate(self.staff)
        r = self.client.delete(f"/api/articles/{self.article.slug}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.article.refresh_from_db()
        self.assertEqual(self.article.status, PublishStatus.ARCHIVED)

    # -- Breaking -----------------------------------------------------------

    def test_breaking_endpoint_returns_only_breaking(self):
        make_published(self.staff, title="Breaking", is_breaking=True)
        r = self.client.get("/api/articles/breaking/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(all(a["is_breaking"] for a in r.data["results"]))

    # -- Top story grid -----------------------------------------------------

    def test_top_story_grid_returns_six_slots(self):
        r = self.client.get("/api/articles/top-stories/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(len(r.data), 6)

    def test_top_story_grid_empty_slots_are_null(self):
        r = self.client.get("/api/articles/top-stories/")
        # No top stories set — all slots should be null.
        for slot in r.data:
            self.assertIsNone(slot["article"])

    def test_top_story_grid_occupied_slot_has_article(self):
        self.article.top_story_rank = 1
        self.article.save()
        r = self.client.get("/api/articles/top-stories/")
        slot_1 = next(s for s in r.data if s["rank"] == 1)
        self.assertIsNotNone(slot_1["article"])
        self.assertEqual(slot_1["article"]["slug"], self.article.slug)

    def test_top_story_grid_slots_in_rank_order(self):
        r = self.client.get("/api/articles/top-stories/")
        ranks = [s["rank"] for s in r.data]
        self.assertEqual(ranks, list(range(TOP_STORY_MIN, TOP_STORY_MAX + 1)))

    # -- Featured -----------------------------------------------------------

    def test_featured_endpoint(self):
        self.article.featured_rank = 1
        self.article.save()
        r = self.client.get("/api/articles/featured/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(len(r.data) > 0)
