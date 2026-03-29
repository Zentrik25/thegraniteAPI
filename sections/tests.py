from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from articles.models import Article, Category, PublishStatus

from .models import Section

User = get_user_model()


def make_user(username="reporter", role="author"):
    return User.objects.create_user(
        username=username,
        password="testpass123",
        email=f"{username}@granite.co.zw",
        role=role,
    )


def make_section(name="News", display_order=1, is_active=True):
    return Section.objects.create(
        name          = name,
        display_order = display_order,
        is_active     = is_active,
    )


def make_category(name="Zimbabwe News", section=None):
    return Category.objects.create(name=name, section=section)


def make_article(author, category=None, art_status=PublishStatus.PUBLISHED):
    return Article.objects.create(
        title    = "Test Article",
        body     = "Body content.",
        author   = author,
        status   = art_status,
        category = category,
    )


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class SectionModelTests(TestCase):

    def test_slug_auto_generated(self):
        s = make_section("Sport")
        self.assertEqual(s.slug, "sport")

    def test_slug_not_overwritten_on_update(self):
        s = make_section("Business")
        s.name = "Economy"
        s.save()
        self.assertEqual(s.slug, "business")

    def test_slug_collision_resolved(self):
        s1 = make_section("News")
        s2 = Section.objects.create(name="News Extra", display_order=2)
        s2.slug = ""
        s2.name = "News"
        s2.save()
        self.assertNotEqual(s1.slug, s2.slug)

    def test_str_returns_name(self):
        s = make_section("Politics")
        self.assertEqual(str(s), "Politics")

    def test_default_ordering_by_display_order(self):
        s2 = make_section("Sport",    display_order=2)
        s1 = make_section("News",     display_order=1)
        s3 = make_section("Business", display_order=3)
        sections = list(Section.objects.all())
        self.assertEqual(sections[0].name, "News")
        self.assertEqual(sections[1].name, "Sport")
        self.assertEqual(sections[2].name, "Business")

    def test_article_count_property(self):
        user     = make_user()
        section  = make_section("News")
        category = make_category(section=section)
        make_article(user, category=category)
        self.assertEqual(section.article_count, 1)

    def test_article_count_excludes_drafts(self):
        user     = make_user("reporter2")
        section  = make_section("Sport")
        category = make_category("Sport News", section=section)
        make_article(user, category=category, art_status=PublishStatus.DRAFT)
        self.assertEqual(section.article_count, 0)

    def test_category_count_property(self):
        section = make_section("Business")
        make_category("Local Business", section=section)
        make_category("International Business", section=section)
        self.assertEqual(section.category_count, 2)


# ---------------------------------------------------------------------------
# API — list
# ---------------------------------------------------------------------------

class SectionListAPITests(APITestCase):

    def setUp(self):
        self.news     = make_section("News",     display_order=1)
        self.sport    = make_section("Sport",    display_order=2)
        self.inactive = make_section("Inactive", display_order=3, is_active=False)

    def test_list_returns_200(self):
        self.assertEqual(self.client.get("/api/v1/sections/").status_code, 200)

    def test_list_returns_only_active_sections(self):
        r     = self.client.get("/api/v1/sections/")
        names = [s["name"] for s in r.data["results"]]
        self.assertIn("News",  names)
        self.assertIn("Sport", names)
        self.assertNotIn("Inactive", names)

    def test_list_ordered_by_display_order(self):
        r = self.client.get("/api/v1/sections/")
        names = [s["name"] for s in r.data["results"]]
        self.assertEqual(names.index("News"), 0)
        self.assertEqual(names.index("Sport"), 1)

    def test_list_returns_count(self):
        r = self.client.get("/api/v1/sections/")
        self.assertEqual(r.data["count"], 2)

    def test_list_returns_status_ok(self):
        r = self.client.get("/api/v1/sections/")
        self.assertEqual(r.data["status"], "ok")

    def test_list_is_public(self):
        self.assertEqual(self.client.get("/api/v1/sections/").status_code, 200)

    def test_list_response_has_required_fields(self):
        r      = self.client.get("/api/v1/sections/")
        first  = r.data["results"][0]
        for field in ("id", "name", "slug", "description", "display_order"):
            self.assertIn(field, first)


# ---------------------------------------------------------------------------
# API — detail
# ---------------------------------------------------------------------------

class SectionDetailAPITests(APITestCase):

    def setUp(self):
        self.user    = make_user("section_reporter")
        self.section = make_section("Politics")
        self.cat     = make_category("Zimbabwe Politics", section=self.section)
        self.article = make_article(self.user, category=self.cat)

    def test_detail_returns_200(self):
        r = self.client.get(f"/api/v1/sections/{self.section.slug}/")
        self.assertEqual(r.status_code, 200)

    def test_detail_returns_section_fields(self):
        r = self.client.get(f"/api/v1/sections/{self.section.slug}/")
        for field in ("id", "name", "slug", "articles", "categories"):
            self.assertIn(field, r.data)

    def test_detail_returns_articles(self):
        r        = self.client.get(f"/api/v1/sections/{self.section.slug}/")
        articles = r.data["articles"]
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["slug"], self.article.slug)

    def test_detail_excludes_drafts(self):
        make_article(
            self.user,
            category   = self.cat,
            art_status = PublishStatus.DRAFT,
        )
        r = self.client.get(f"/api/v1/sections/{self.section.slug}/")
        self.assertEqual(len(r.data["articles"]), 1)

    def test_detail_returns_categories(self):
        r = self.client.get(f"/api/v1/sections/{self.section.slug}/")
        self.assertEqual(len(r.data["categories"]), 1)

    def test_unknown_slug_returns_404(self):
        r = self.client.get("/api/v1/sections/does-not-exist/")
        self.assertEqual(r.status_code, 404)

    def test_inactive_section_returns_404(self):
        inactive = make_section("Inactive Section", is_active=False)
        r = self.client.get(f"/api/v1/sections/{inactive.slug}/")
        self.assertEqual(r.status_code, 404)

    def test_detail_is_public(self):
        r = self.client.get(f"/api/v1/sections/{self.section.slug}/")
        self.assertEqual(r.status_code, 200)


# ---------------------------------------------------------------------------
# API — create
# ---------------------------------------------------------------------------

class SectionCreateAPITests(APITestCase):

    def setUp(self):
        self.editor  = make_user("editor",  role="editor")
        self.author  = make_user("author",  role="author")

    def test_editor_can_create_section(self):
        self.client.force_authenticate(self.editor)
        r = self.client.post("/api/v1/sections/", {
            "name":          "Entertainment",
            "description":   "Entertainment news.",
            "display_order": 4,
        })
        self.assertEqual(r.status_code, 201)

    def test_author_cannot_create_section(self):
        self.client.force_authenticate(self.author)
        r = self.client.post("/api/v1/sections/", {
            "name": "Entertainment",
        })
        self.assertEqual(r.status_code, 403)

    def test_unauthenticated_cannot_create(self):
        r = self.client.post("/api/v1/sections/", {"name": "Entertainment"})
        self.assertEqual(r.status_code, 401)

    def test_create_generates_slug(self):
        self.client.force_authenticate(self.editor)
        r = self.client.post("/api/v1/sections/", {
            "name":          "Technology",
            "display_order": 5,
        })
        self.assertEqual(r.status_code, 201)
        self.assertTrue(
            Section.objects.filter(slug="technology").exists()
        )

    def test_duplicate_name_returns_400(self):
        make_section("Duplicate")
        self.client.force_authenticate(self.editor)
        r = self.client.post("/api/v1/sections/", {"name": "Duplicate"})
        self.assertEqual(r.status_code, 400)


# ---------------------------------------------------------------------------
# API — update and deactivate
# ---------------------------------------------------------------------------

class SectionUpdateAPITests(APITestCase):

    def setUp(self):
        self.editor  = make_user("editor2", role="editor")
        self.section = make_section("Health")

    def test_editor_can_update_section(self):
        self.client.force_authenticate(self.editor)
        r = self.client.patch(
            f"/api/v1/sections/{self.section.slug}/",
            {"description": "Health and wellness news."},
        )
        self.assertEqual(r.status_code, 200)
        self.section.refresh_from_db()
        self.assertEqual(self.section.description, "Health and wellness news.")

    def test_editor_can_deactivate_section(self):
        self.client.force_authenticate(self.editor)
        r = self.client.delete(f"/api/v1/sections/{self.section.slug}/")
        self.assertEqual(r.status_code, 200)
        self.section.refresh_from_db()
        self.assertFalse(self.section.is_active)

    def test_deactivate_preserves_record(self):
        self.client.force_authenticate(self.editor)
        self.client.delete(f"/api/v1/sections/{self.section.slug}/")
        self.assertTrue(Section.objects.filter(pk=self.section.pk).exists())

    def test_author_cannot_update(self):
        author = make_user("author2", role="author")
        self.client.force_authenticate(author)
        r = self.client.patch(
            f"/api/v1/sections/{self.section.slug}/",
            {"description": "Unauthorised update."},
        )
        self.assertEqual(r.status_code, 403)