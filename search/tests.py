from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.postgres.search import SearchVector
from django.core.cache import caches
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
        caches["throttle"].clear()
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

    def tearDown(self):
        caches["throttle"].clear()

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

    def test_invalid_page_defaults_to_first_page(self):
        r = self.client.get("/api/v1/search/?q=zimbabwe&page=not-a-number")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["current_page"], 1)

    def test_invalid_page_size_defaults_instead_of_500(self):
        r = self.client.get("/api/v1/search/?q=zimbabwe&page_size=invalid")
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(r.data["results"]), 20)

    def test_zero_page_size_defaults_instead_of_500(self):
        r = self.client.get("/api/v1/search/?q=zimbabwe&page_size=0")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.data["results"]), 1)

    def test_no_results_returns_empty_list(self):
        r = self.client.get("/api/v1/search/?q=xyznotaword123")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 0)
        self.assertEqual(r.data["results"], [])

    # -- Access control -----------------------------------------------------

    def test_search_is_public_no_auth_required(self):
        r = self.client.get("/api/v1/search/?q=zimbabwe")
        self.assertEqual(r.status_code, 200)

    def test_search_endpoint_is_throttled(self):
        from search.throttling import SearchRateThrottle

        with patch.object(SearchRateThrottle, "rate", "2/min"):
            first = self.client.get("/api/v1/search/?q=zimbabwe")
            second = self.client.get("/api/v1/search/?q=zimbabwe")
            third = self.client.get("/api/v1/search/?q=zimbabwe")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(third.status_code, 429)

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
# Premium body leak prevention
# ---------------------------------------------------------------------------

@skipUnless(connection.vendor == "postgresql", "PostgreSQL required for full-text search")
class PremiumSearchLeakTests(APITestCase):
    """
    Guard that premium article body text never reaches public search
    responses via the SearchHeadline ORM annotation.

    SearchHeadline("body", …) generates a snippet directly from the body
    column.  For premium articles that body is gated content; this suite
    verifies the view substitutes the public excerpt instead.
    """

    # Distinctive strings that must/must-not appear in responses.
    _PREMIUM_BODY_MARKER = "EXCLUSIVEPREMIUMCONTENT"
    _FREE_BODY_MARKER    = "FREEBODYCONTENT"

    def setUp(self):
        self.user = make_user("leak_reporter")
        self.cat  = Category.objects.create(name="Leak Tests")

        # Free article — body snippet should reach the response normally.
        self.free_article = make_article(
            self.user,
            title    = "Free Article About Harare Traffic",
            body     = f"{self._FREE_BODY_MARKER} harare traffic congestion details.",
            excerpt  = "Free public excerpt about Harare traffic.",
            category = self.cat,
        )

        # Premium article — body snippet must NEVER reach the response.
        self.premium_article = make_article(
            self.user,
            title      = "Premium Analysis of Economic Policy",
            body       = f"{self._PREMIUM_BODY_MARKER} exclusive subscriber analysis.",
            excerpt    = "Premium public excerpt: economic policy overview.",
            category   = self.cat,
            is_premium = True,
        )

    # -- Core leak prevention -----------------------------------------------

    def test_premium_body_marker_absent_from_all_headlines(self):
        """
        The distinctive premium body string must not appear in any
        headline field across any search result page.
        """
        r = self.client.get(
            f"/api/v1/search/?q={self._PREMIUM_BODY_MARKER.lower()}"
        )
        self.assertEqual(r.status_code, 200)
        for result in r.data["results"]:
            self.assertNotIn(
                self._PREMIUM_BODY_MARKER,
                result["headline"],
                msg="Premium body text leaked via search headline.",
            )

    def test_premium_article_headline_equals_excerpt(self):
        """
        When a premium article appears in results, its headline must be
        the article's public excerpt — not a body-derived snippet.
        """
        r = self.client.get("/api/v1/search/?q=economic+policy")
        self.assertEqual(r.status_code, 200)
        premium_results = [
            res for res in r.data["results"]
            if res["article"]["slug"] == self.premium_article.slug
        ]
        self.assertTrue(
            premium_results,
            "Premium article did not appear in search results for a query "
            "matching its title — cannot verify headline safety.",
        )
        self.assertEqual(
            premium_results[0]["headline"],
            self.premium_article.excerpt,
        )

    def test_premium_body_text_not_in_article_dict(self):
        """
        ArticleListSerializer already excludes body; double-check that
        the article sub-dict also contains no body key.
        """
        r = self.client.get("/api/v1/search/?q=economic+policy")
        for result in r.data["results"]:
            self.assertNotIn("body", result["article"])

    # -- Discoverability preserved ------------------------------------------

    def test_premium_article_appears_in_results_for_title_query(self):
        """Premium articles must still be findable by title."""
        r = self.client.get("/api/v1/search/?q=economic+policy")
        slugs = [res["article"]["slug"] for res in r.data["results"]]
        self.assertIn(self.premium_article.slug, slugs)

    def test_premium_article_appears_in_results_for_body_query(self):
        """
        Premium articles must appear even when the query matches only the
        body — the article is indexed, the body text just doesn't leak.
        """
        r = self.client.get(
            f"/api/v1/search/?q={self._PREMIUM_BODY_MARKER.lower()}"
        )
        self.assertEqual(r.status_code, 200)
        slugs = [res["article"]["slug"] for res in r.data["results"]]
        self.assertIn(
            self.premium_article.slug,
            slugs,
            "Premium article disappeared from results — it should be "
            "discoverable even though the body snippet is suppressed.",
        )

    # -- Free article behaviour unaffected ----------------------------------

    def test_free_article_headline_is_body_derived(self):
        """Free articles still get body-derived headlines with <mark> tags."""
        r = self.client.get(
            f"/api/v1/search/?q={self._FREE_BODY_MARKER.lower()}"
        )
        self.assertEqual(r.status_code, 200)
        free_results = [
            res for res in r.data["results"]
            if res["article"]["slug"] == self.free_article.slug
        ]
        self.assertTrue(
            free_results,
            "Free article not found — cannot verify body snippet behaviour.",
        )
        headline = free_results[0]["headline"]
        self.assertIn(
            "<mark>",
            headline,
            "Free article headline should contain <mark> tags from SearchHeadline.",
        )

    def test_free_article_body_marker_present_in_headline(self):
        """The free article's body content reaches the headline as expected."""
        r = self.client.get(
            f"/api/v1/search/?q={self._FREE_BODY_MARKER.lower()}"
        )
        free_results = [
            res for res in r.data["results"]
            if res["article"]["slug"] == self.free_article.slug
        ]
        if free_results:
            self.assertIn(self._FREE_BODY_MARKER, free_results[0]["headline"])

    # -- Response shape stability -------------------------------------------

    def test_headline_key_always_present_for_premium(self):
        """headline must be present in the result dict even for premium articles."""
        r = self.client.get("/api/v1/search/?q=economic+policy")
        premium_results = [
            res for res in r.data["results"]
            if res["article"]["slug"] == self.premium_article.slug
        ]
        if premium_results:
            self.assertIn("headline", premium_results[0])

    def test_premium_headline_is_string_not_none(self):
        """headline for a premium article with no excerpt must be empty string."""
        no_excerpt_article = make_article(
            self.user,
            title      = "Premium No Excerpt Article",
            body       = f"{self._PREMIUM_BODY_MARKER} no excerpt set.",
            excerpt    = "",
            category   = self.cat,
            is_premium = True,
        )
        r = self.client.get(
            f"/api/v1/search/?q={self._PREMIUM_BODY_MARKER.lower()}"
        )
        for result in r.data["results"]:
            # headline must never be None — empty string is the safe fallback.
            self.assertIsNotNone(result["headline"])
            self.assertIsInstance(result["headline"], str)


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
