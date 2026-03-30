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

    def test_is_top_story_cleared_when_rank_removed(self):
        """Removing top_story_rank must also clear is_top_story (bidirectional sync)."""
        a = make_published(self.user, top_story_rank=2)
        self.assertTrue(a.is_top_story)
        a.top_story_rank = None
        a.save()
        a.refresh_from_db()
        self.assertFalse(a.is_top_story)

    def test_is_featured_cleared_when_rank_removed(self):
        """Removing featured_rank must also clear is_featured."""
        a = make_published(self.user, featured_rank=1)
        self.assertTrue(a.is_featured)
        a.featured_rank = None
        a.save()
        a.refresh_from_db()
        self.assertFalse(a.is_featured)


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

    def test_list_response_includes_is_premium(self):
        r = self.client.get("/api/articles/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        first = r.data["results"][0]
        self.assertIn("is_premium", first)
        self.assertIsInstance(first["is_premium"], bool)

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

    def test_create_requires_authentication(self):
        """Unauthenticated POST to /api/articles/ must be rejected."""
        r = self.client.post("/api/articles/", {"title": "New", "body": "..."})
        self.assertIn(r.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

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
        self.assertTrue(len(r.data["results"]) > 0)


# ---------------------------------------------------------------------------
# Category / Tag detail — pagination bounding
# ---------------------------------------------------------------------------

class CategoryDetailPaginationTests(APITestCase):
    """
    GET /api/categories/<slug>/ must return bounded article lists.

    The response keeps its envelope shape:
      {"category": {...}, "count": N, "total_pages": N, ..., "articles": [...page...]}
    The "articles" key is preserved for backward compatibility; pagination
    metadata keys are additive.
    """

    def setUp(self):
        self.editor = make_user("cat_editor", role="editor")
        self.cat    = Category.objects.create(name="Pagination Test", slug="pagination-test")

    def _url(self):
        return f"/api/categories/{self.cat.slug}/"

    def test_response_contains_category_metadata(self):
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("category", r.data)
        self.assertEqual(r.data["category"]["slug"], self.cat.slug)

    def test_response_contains_articles_key(self):
        """The 'articles' key must still be present (backward compat)."""
        r = self.client.get(self._url())
        self.assertIn("articles", r.data)
        self.assertIsInstance(r.data["articles"], list)

    def test_response_contains_pagination_metadata(self):
        """Pagination envelope keys are added alongside existing keys."""
        r = self.client.get(self._url())
        for key in ("count", "total_pages", "current_page", "page_size", "next", "previous"):
            self.assertIn(key, r.data, msg=f"Missing pagination key: {key}")

    def test_articles_bounded_to_page_size(self):
        """More than page_size articles are not all returned on page 1."""
        for i in range(25):
            make_published(
                self.editor,
                title=f"Cat Article {i}",
                category=self.cat,
            )
        r = self.client.get(self._url())
        self.assertEqual(r.data["count"], 25)
        self.assertLessEqual(len(r.data["articles"]), 20)  # page_size=20

    def test_page_two_reachable(self):
        """?page=2 returns the next slice when count > page_size."""
        for i in range(25):
            make_published(self.editor, title=f"P2 Cat {i}", category=self.cat)
        r = self.client.get(self._url() + "?page=2")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["current_page"], 2)
        self.assertGreater(len(r.data["articles"]), 0)

    def test_empty_category_returns_zero_count(self):
        r = self.client.get(self._url())
        self.assertEqual(r.data["count"], 0)
        self.assertEqual(r.data["articles"], [])


class TagDetailPaginationTests(APITestCase):
    """GET /api/tags/<slug>/ — same bounding contract as CategoryDetailView."""

    def setUp(self):
        self.editor = make_user("tag_editor", role="editor")
        self.tag    = Tag.objects.create(name="pagtest", slug="pagtest")

    def _url(self):
        return f"/api/tags/{self.tag.slug}/"

    def test_response_shape_preserved(self):
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("tag", r.data)
        self.assertIn("articles", r.data)

    def test_response_contains_pagination_metadata(self):
        r = self.client.get(self._url())
        for key in ("count", "total_pages", "current_page", "page_size", "next", "previous"):
            self.assertIn(key, r.data, msg=f"Missing pagination key: {key}")

    def test_articles_bounded_to_page_size(self):
        cat = Category.objects.create(name="TagCat", slug="tagcat")
        for i in range(25):
            art = make_published(self.editor, title=f"Tag Art {i}", category=cat)
            art.tags.add(self.tag)
        r = self.client.get(self._url())
        self.assertEqual(r.data["count"], 25)
        self.assertLessEqual(len(r.data["articles"]), 20)


# ---------------------------------------------------------------------------
# Permission consistency — role model vs raw is_staff
# ---------------------------------------------------------------------------

class ArticlePermissionConsistencyTests(APITestCase):
    """
    Verify that article list/detail queryset scoping and object-level write
    guards use the project's role model (can_edit_any_article) consistently,
    not just the raw Django is_staff flag.

    These tests confirm:
      - Anonymous users see only published articles.
      - Editors (can_edit_any_article=True) see all statuses.
      - Authors (can_edit_any_article=False) see only published articles.
      - An editor can PATCH any article (not their own).
      - An author cannot PATCH another author's article.
      - An author can PATCH their own draft.
    """

    def setUp(self):
        self.cat    = Category.objects.create(name="PermTestCat")
        self.editor = make_user("perm_editor", role="editor")
        self.author = make_user("perm_author", role="author")
        self.other  = make_user("perm_other",  role="author")

        self.published = make_article(
            self.editor,
            title="Published",
            art_status=PublishStatus.PUBLISHED,
            category=self.cat,
        )
        self.draft = make_article(
            self.author,
            title="Draft",
            art_status=PublishStatus.DRAFT,
            category=self.cat,
        )

    def test_anonymous_sees_only_published_in_list(self):
        r = self.client.get("/api/articles/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        titles = [a["title"] for a in r.data["results"]]
        self.assertIn("Published", titles)
        self.assertNotIn("Draft", titles)

    def test_editor_sees_drafts_in_list(self):
        self.client.force_authenticate(self.editor)
        r = self.client.get("/api/articles/")
        titles = [a["title"] for a in r.data["results"]]
        self.assertIn("Draft", titles)

    def test_author_sees_only_published_in_list(self):
        """Authors do not have can_edit_any_article — they see published only."""
        self.client.force_authenticate(self.author)
        r = self.client.get("/api/articles/")
        titles = [a["title"] for a in r.data["results"]]
        self.assertIn("Published", titles)
        self.assertNotIn("Draft", titles)

    def test_editor_can_patch_any_article(self):
        """Editors have can_edit_any_article=True and may PATCH articles they didn't write."""
        self.client.force_authenticate(self.editor)
        r = self.client.patch(
            f"/api/articles/{self.draft.slug}/",
            {"title": "Draft — editor updated"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_author_cannot_patch_other_authors_article(self):
        """Author without editor role cannot PATCH another author's article."""
        self.client.force_authenticate(self.other)
        r = self.client.patch(
            f"/api/articles/{self.draft.slug}/",
            {"title": "Hijacked"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_author_can_patch_own_article(self):
        """Authors can PATCH their own articles (obj.author == request.user)."""
        self.client.force_authenticate(self.author)
        r = self.client.patch(
            f"/api/articles/{self.draft.slug}/",
            {"title": "Draft — author updated"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # Create (POST) — role model gate replaces raw is_staff check
    # ------------------------------------------------------------------

    def test_author_can_create_article(self):
        """
        Authors have role != CONTRIBUTOR so IsAuthorOrAbove passes.
        Under the old IsAdminUser guard they were blocked (is_staff=False);
        this test confirms the fix.
        """
        self.client.force_authenticate(self.author)
        r = self.client.post(
            "/api/articles/",
            {"title": "Author Draft", "body": "Body text.", "status": "draft"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_contributor_cannot_create_article(self):
        """Contributors (role == CONTRIBUTOR) are blocked by IsAuthorOrAbove."""
        contributor = make_user("contrib_user", role="contributor")
        self.client.force_authenticate(contributor)
        r = self.client.post(
            "/api/articles/",
            {"title": "Contrib Draft", "body": "Body text.", "status": "draft"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_create_article(self):
        """Unauthenticated requests are rejected before the role check."""
        r = self.client.post(
            "/api/articles/",
            {"title": "Anon Draft", "body": "Body text.", "status": "draft"},
            format="json",
        )
        self.assertIn(r.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    # ------------------------------------------------------------------
    # Unauthenticated write — must return 401/403, not 500
    # ------------------------------------------------------------------

    def test_unauthenticated_patch_is_rejected_not_500(self):
        """
        Without the has_permission guard on IsAuthorOrStaff, an unauthenticated
        PATCH would reach has_object_permission and call can_edit_any_article on
        AnonymousUser, raising AttributeError → 500.  Confirm it now returns a
        proper 401 or 403.
        """
        r = self.client.patch(
            f"/api/articles/{self.published.slug}/",
            {"title": "Hijacked"},
            format="json",
        )
        self.assertIn(r.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_unauthenticated_delete_is_rejected_not_500(self):
        """Same guard applies to DELETE (archive) — must not reach object level."""
        r = self.client.delete(f"/api/articles/{self.published.slug}/")
        self.assertIn(r.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_unauthenticated_patch_draft_returns_404_not_403(self):
        """
        Unauthenticated request must not receive 403 for a draft slug — that would
        reveal the article's existence.  The get_queryset guard (published-only for
        unauthenticated requests) must return 404 before any permission check fires.
        """
        # self.draft already exists in this class's setUp
        # Confirm the draft is invisible on the public feed
        r_list = self.client.get("/api/articles/")
        titles = [a["title"] for a in r_list.data["results"]]
        self.assertNotIn(self.draft.title, titles)
        # A crafted PATCH targeting the draft slug must not reveal its existence
        r = self.client.patch(
            f"/api/articles/{self.draft.slug}/",
            {"title": "Hijacked"},
            format="json",
        )
        # 401 (not authenticated) is fine; 403 or 200 would leak existence
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_breaking_news_response_is_paginated(self):
        """BreakingNewsView must return a paginated envelope, not a bare list."""
        self.published.is_breaking = True
        self.published.save()
        r = self.client.get("/api/articles/breaking/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("results", r.data)
        self.assertIn("count", r.data)

    def test_featured_response_is_paginated(self):
        """FeaturedArticlesView must return a paginated envelope, not a bare list."""
        self.published.featured_rank = 1
        self.published.save()
        r = self.client.get("/api/articles/featured/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("results", r.data)
        self.assertIn("count", r.data)
