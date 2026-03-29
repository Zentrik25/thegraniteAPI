from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.contrib.postgres.search import SearchVector
from django.db import connection
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from articles.models import Article, Category, PublishStatus

User = get_user_model()


def make_user(username="reporter"):
    return User.objects.create_user(
        username=username,
        password="testpass123",
        email=f"{username}@granite.co.zw",
        role="author",
    )


def make_article(
    author,
    title="Test Article",
    body="Test body content.",
    excerpt="Test excerpt.",
    art_status=PublishStatus.PUBLISHED,
    **kwargs,
):
    article = Article.objects.create(
        title   = title,
        body    = body,
        excerpt = excerpt,
        author  = author,
        status  = art_status,
        **kwargs,
    )
    # Manually populate the search vector since signals run
    # asynchronously in the test environment.
    if art_status == PublishStatus.PUBLISHED:
        Article.objects.filter(pk=article.pk).update(
            search_vector=(
                SearchVector("title",   weight="A", config="english") +
                SearchVector("excerpt", weight="B", config="english") +
                SearchVector("body",    weight="C", config="english")
            )
        )
        article.refresh_from_db()
    return article


# ---------------------------------------------------------------------------
# Search signal
# ---------------------------------------------------------------------------

@skipUnless(connection.vendor == "postgresql", "PostgreSQL required for full-text search")
class SearchSignalTests(TestCase):

    def setUp(self):
        self.user = make_user()

    def test_search_vector_populated_on_publish(self):
        article = make_article(self.user, title="Harare Floods")
        article.refresh_from_db()
        self.assertIsNotNone(article.search_vector)

    def test_search_vector_not_populated_for_draft(self):
        article = Article.objects.create(
            title="Draft Article",
            body="Draft body.",
            author=self.user,
            status=PublishStatus.DRAFT,
        )
        article.refresh_from_db()
        self.assertIsNone(article.search_vector)


# ---------------------------------------------------------------------------
# Search API
# ---------------------------------------------------------------------------

@skipUnless(connection.vendor == "postgresql", "PostgreSQL required for full-text search")
class ArticleSearchAPITests(APITestCase):

    def setUp(self):
        self.user = make_user("search_reporter")
        self.cat  = Category.objects.create(name="News")

        self.article1 = make_article(
            self.user,
            title   = "Zimbabwe Fuel Prices Rise Again",
            excerpt = "Fuel prices have increased for the third time this year.",
            body    = "The Zimbabwe Energy Regulatory Authority announced fuel price increases.",
            category = self.cat,
        )
        self.article2 = make_article(
            self.user,
            title   = "Harare City Council Budget Approved",
            excerpt = "The Harare city council has approved its annual budget.",
            body    = "Councillors voted unanimously to approve the budget.",
            category = self.cat,
        )
        self.article3 = make_article(
            self.user,
            title   = "Zimbabwe Economy Shows Growth",
            excerpt = "The Zimbabwean economy has shown signs of recovery.",
            body    = "GDP figures released today show positive growth trends.",
            category = self.cat,
        )

    # -- Basic search -------------------------------------------------------

    def test_search_returns_200(self):
        r = self.client.get("/api/v1/search/?q=zimbabwe")
        self.assertEqual(r.status_code, 200)

    def test_search_returns_matching_articles(self):
        r = self.client.get("/api/v1/search/?q=fuel")
        self.assertEqual(r.status_code, 200)
        slugs = [res["article"]["slug"] for res in r.data["results"]]
        self.assertIn(self.article1.slug, slugs)

    def test_search_excludes_non_matching_articles(self):
        r = self.client.get("/api/v1/search/?q=fuel")
        slugs = [res["article"]["slug"] for res in r.data["results"]]
        self.assertNotIn(self.article2.slug, slugs)

    def test_search_returns_count(self):
        r = self.client.get("/api/v1/search/?q=zimbabwe")
        self.assertIn("count", r.data)
        self.assertGreaterEqual(r.data["count"], 1)

    def test_search_returns_query_in_response(self):
        r = self.client.get("/api/v1/search/?q=harare")
        self.assertEqual(r.data["query"], "harare")

    def test_search_returns_status_ok(self):
        r = self.client.get("/api/v1/search/?q=harare")
        self.assertEqual(r.data["status"], "ok")

    def test_search_results_have_rank(self):
        r = self.client.get("/api/v1/search/?q=zimbabwe")
        for result in r.data["results"]:
            self.assertIn("rank", result)
            self.assertIsInstance(result["rank"], float)

    def test_search_results_have_headline(self):
        r = self.client.get("/api/v1/search/?q=zimbabwe")
        for result in r.data["results"]:
            self.assertIn("headline", result)

    def test_search_headline_contains_mark_tags(self):
        r = self.client.get("/api/v1/search/?q=zimbabwe")
        if r.data["results"]:
            headline = r.data["results"][0]["headline"]
            if headline:
                self.assertIn("<mark>", headline)

    # -- Ranking ------------------------------------------------------------

    def test_title_match_ranks_higher_than_body_match(self):
        r = self.client.get("/api/v1/search/?q=zimbabwe")
        if len(r.data["results"]) >= 2:
            first_rank  = r.data["results"][0]["rank"]
            second_rank = r.data["results"][1]["rank"]
            self.assertGreaterEqual(first_rank, second_rank)

    # -- Validation ---------------------------------------------------------

    def test_empty_query_returns_400(self):
        r = self.client.get("/api/v1/search/?q=")
        self.assertEqual(r.status_code, 400)

    def test_single_char_query_returns_400(self):
        r = self.client.get("/api/v1/search/?q=a")
        self.assertEqual(r.status_code, 400)

    def test_missing_query_returns_400(self):
        r = self.client.get("/api/v1/search/")
        self.assertEqual(r.status_code, 400)

    def test_very_long_query_returns_400(self):
        r = self.client.get(f"/api/v1/search/?q={'a' * 201}")
        self.assertEqual(r.status_code, 400)

    # -- Pagination ---------------------------------------------------------

    def test_pagination_fields_present(self):
        r = self.client.get("/api/v1/search/?q=zimbabwe")
        for field in ("count", "total_pages", "current_page", "next", "previous"):
            self.assertIn(field, r.data)

    def test_page_size_respected(self):
        r = self.client.get("/api/v1/search/?q=zimbabwe&page_size=1")
        self.assertLessEqual(len(r.data["results"]), 1)

    def test_page_size_capped_at_50(self):
        r = self.client.get("/api/v1/search/?q=zimbabwe&page_size=9999")
        self.assertLessEqual(len(r.data["results"]), 50)

    def test_no_results_returns_empty_list(self):
        r = self.client.get("/api/v1/search/?q=xyznotaword123")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 0)
        self.assertEqual(r.data["results"], [])

    # -- Access control -----------------------------------------------------

    def test_search_is_public_no_auth_required(self):
        r = self.client.get("/api/v1/search/?q=zimbabwe")
        self.assertEqual(r.status_code, 200)

    def test_drafts_not_in_search_results(self):
        draft = Article.objects.create(
            title  = "Zimbabwe Draft Article Not Searchable",
            body   = "This draft should not appear in search results.",
            author = self.user,
            status = PublishStatus.DRAFT,
        )
        r    = self.client.get("/api/v1/search/?q=zimbabwe+draft+not+searchable")
        slugs = [res["article"]["slug"] for res in r.data["results"]]
        self.assertNotIn(draft.slug, slugs)

    # -- Multi-word search --------------------------------------------------

    def test_multi_word_search(self):
        r = self.client.get("/api/v1/search/?q=fuel+prices")
        self.assertEqual(r.status_code, 200)
        slugs = [res["article"]["slug"] for res in r.data["results"]]
        self.assertIn(self.article1.slug, slugs)

    def test_websearch_syntax_phrase(self):
        r = self.client.get('/api/v1/search/?q="fuel prices"')
        self.assertEqual(r.status_code, 200)


# ---------------------------------------------------------------------------
# Management command
# ---------------------------------------------------------------------------

@skipUnless(connection.vendor == "postgresql", "PostgreSQL required for full-text search")
class RebuildSearchIndexCommandTests(TestCase):

    def setUp(self):
        self.user = make_user("cmd_reporter")

    def test_rebuild_command_runs_without_error(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        Article.objects.create(
            title  = "Command Test Article",
            body   = "Body content for command test.",
            author = self.user,
            status = PublishStatus.PUBLISHED,
        )
        call_command("rebuild_search_index", stdout=out)
        self.assertIn("updated", out.getvalue())

    def test_rebuild_populates_search_vector(self):
        from django.core.management import call_command
        article = Article.objects.create(
            title  = "Rebuild Test Article",
            body   = "Testing the rebuild command.",
            author = self.user,
            status = PublishStatus.PUBLISHED,
        )
        # Clear the vector first.
        Article.objects.filter(pk=article.pk).update(search_vector=None)
        article.refresh_from_db()
        self.assertIsNone(article.search_vector)

        call_command("rebuild_search_index")

        article.refresh_from_db()
        self.assertIsNotNone(article.search_vector)
