from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from articles.models import Article, PublishStatus

from .models import Redirect

User = get_user_model()


def make_user(username="reporter", role="author"):
    return User.objects.create_user(
        username=username,
        password="testpass123",
        email=f"{username}@granite.co.zw",
        role=role,
    )


def make_article(author, title="Test Article"):
    return Article.objects.create(
        title=title,
        body="Body.",
        author=author,
        status=PublishStatus.PUBLISHED,
    )


def make_redirect(
    old_path="/articles/old/",
    new_path="/articles/new/",
    is_active=True,
):
    return Redirect.objects.create(
        old_path   = old_path,
        new_path   = new_path,
        is_active  = is_active,
        created_by = "manual",
    )


class RedirectModelTests(TestCase):

    def test_str_shows_paths(self):
        r = make_redirect()
        self.assertIn("old", str(r))
        self.assertIn("new", str(r))

    def test_loop_detection_raises(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            Redirect.objects.create(
                old_path="/articles/same/",
                new_path="/articles/same/",
            )

    def test_path_normalised_to_start_with_slash(self):
        r = Redirect.objects.create(
            old_path="articles/no-slash/",
            new_path="articles/new-no-slash/",
        )
        self.assertTrue(r.old_path.startswith("/"))
        self.assertTrue(r.new_path.startswith("/"))

    def test_record_hit_increments_counter(self):
        r = make_redirect()
        r.record_hit()
        r.refresh_from_db()
        self.assertEqual(r.hits, 1)

    def test_unique_old_path_enforced(self):
        from django.db import IntegrityError
        make_redirect("/articles/unique/", "/articles/target/")
        with self.assertRaises(IntegrityError):
            Redirect.objects.create(
                old_path="/articles/unique/",
                new_path="/articles/other/",
            )


class RedirectSignalTests(TestCase):

    def setUp(self):
        self.user = make_user()

    def test_redirect_created_on_slug_change(self):
        article      = make_article(self.user)
        old_slug     = article.slug
        article.slug = "brand-new-slug"
        article.save()
        self.assertTrue(
            Redirect.objects.filter(
                old_path=f"/articles/{old_slug}/",
                new_path="/articles/brand-new-slug/",
            ).exists()
        )

    def test_no_redirect_on_new_article(self):
        count_before = Redirect.objects.count()
        make_article(self.user, title="New Article No Redirect")
        self.assertEqual(Redirect.objects.count(), count_before)

    def test_no_redirect_when_slug_unchanged(self):
        article      = make_article(self.user)
        count_before = Redirect.objects.count()
        article.title = "Updated Title Only"
        article.save()
        self.assertEqual(Redirect.objects.count(), count_before)

    def test_redirect_chain_resolved(self):
        article  = make_article(self.user, title="Chain Test")
        old_slug = article.slug

        article.slug = "mid-slug"
        article.save()

        article.slug = "final-slug"
        article.save()

        first = Redirect.objects.get(old_path=f"/articles/{old_slug}/")
        self.assertEqual(first.new_path, "/articles/final-slug/")

    def test_redirect_created_by_signal(self):
        article      = make_article(self.user, title="Signal Test")
        article.slug = "signal-test-new"
        article.save()
        r = Redirect.objects.get(new_path="/articles/signal-test-new/")
        self.assertEqual(r.created_by, "signal")


@override_settings(
    MIDDLEWARE=[
        "django.middleware.security.SecurityMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "redirects.middleware.RedirectMiddleware",
    ]
)
class RedirectMiddlewareTests(TestCase):

    def test_active_redirect_returns_301(self):
        make_redirect("/articles/old-article/", "/articles/new-article/")
        r = self.client.get("/articles/old-article/")
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r["Location"], "/articles/new-article/")

    def test_inactive_redirect_returns_404(self):
        make_redirect(
            "/articles/inactive-old/",
            "/articles/inactive-new/",
            is_active=False,
        )
        r = self.client.get("/articles/inactive-old/")
        self.assertEqual(r.status_code, 404)

    def test_unknown_path_returns_404(self):
        r = self.client.get("/articles/does-not-exist/")
        self.assertEqual(r.status_code, 404)

    def test_redirect_normalises_missing_trailing_slash(self):
        make_redirect("/articles/no-slash/", "/articles/target/")
        r = self.client.get("/articles/no-slash")
        self.assertEqual(r.status_code, 301)


class RedirectAPITests(APITestCase):

    def setUp(self):
        self.editor = make_user("redir_editor", role="editor")
        self.author = make_user("redir_author", role="author")

    def test_list_requires_auth(self):
        r = self.client.get("/api/v1/redirects/")
        self.assertEqual(r.status_code, 401)

    def test_author_cannot_access(self):
        self.client.force_authenticate(self.author)
        r = self.client.get("/api/v1/redirects/")
        self.assertEqual(r.status_code, 403)

    def test_editor_can_list(self):
        self.client.force_authenticate(self.editor)
        r = self.client.get("/api/v1/redirects/")
        self.assertEqual(r.status_code, 200)

    def test_editor_can_create(self):
        self.client.force_authenticate(self.editor)
        r = self.client.post("/api/v1/redirects/", {
            "old_path": "/articles/manual-old/",
            "new_path": "/articles/manual-new/",
        })
        self.assertEqual(r.status_code, 201)

    def test_loop_returns_400(self):
        self.client.force_authenticate(self.editor)
        r = self.client.post("/api/v1/redirects/", {
            "old_path": "/articles/loop/",
            "new_path": "/articles/loop/",
        })
        self.assertEqual(r.status_code, 400)

    def test_editor_can_update(self):
        redirect = make_redirect("/articles/upd-old/", "/articles/upd-new/")
        self.client.force_authenticate(self.editor)
        r = self.client.patch(
            f"/api/v1/redirects/{redirect.pk}/",
            {"new_path": "/articles/updated-target/"},
        )
        self.assertEqual(r.status_code, 200)

    def test_editor_can_delete(self):
        redirect = make_redirect("/articles/del-old/", "/articles/del-new/")
        self.client.force_authenticate(self.editor)
        r = self.client.delete(f"/api/v1/redirects/{redirect.pk}/")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Redirect.objects.filter(pk=redirect.pk).exists())

    def test_filter_active_only(self):
        make_redirect("/articles/active-p/",   "/articles/t1/", is_active=True)
        make_redirect("/articles/inactive-p/", "/articles/t2/", is_active=False)
        self.client.force_authenticate(self.editor)
        r     = self.client.get("/api/v1/redirects/?active=true")
        paths = [red["old_path"] for red in r.data["results"]]
        self.assertIn("/articles/active-p/",      paths)
        self.assertNotIn("/articles/inactive-p/", paths)

    def test_search_by_path(self):
        make_redirect("/articles/searchable-xyz/", "/articles/target/")
        self.client.force_authenticate(self.editor)
        r     = self.client.get("/api/v1/redirects/?search=searchable-xyz")
        paths = [red["old_path"] for red in r.data["results"]]
        self.assertIn("/articles/searchable-xyz/", paths)