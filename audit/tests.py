from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APITestCase

from articles.models import Article, PublishStatus

from .models import AuditAction, AuditLog
from .utils import log_action

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
        body="Body content.",
        author=author,
        status=PublishStatus.PUBLISHED,
    )


class AuditLogModelTests(TestCase):

    def setUp(self):
        self.user = make_user()

    def test_str_includes_action_and_actor(self):
        log = AuditLog.objects.create(
            actor  = self.user,
            action = AuditAction.ARTICLE_PUBLISHED,
        )
        self.assertIn("article.published", str(log))

    def test_str_shows_system_for_no_actor(self):
        log = AuditLog.objects.create(
            action = AuditAction.ARTICLE_PUBLISHED,
        )
        self.assertIn("system", str(log))

    def test_metadata_defaults_to_empty_dict(self):
        log = AuditLog.objects.create(
            action=AuditAction.ARTICLE_CREATED,
        )
        self.assertEqual(log.metadata, {})


class LogActionUtilTests(TestCase):

    def setUp(self):
        self.user    = make_user("util_reporter")
        self.article = make_article(self.user)

    def test_log_action_creates_record(self):
        count_before = AuditLog.objects.count()
        log_action(
            action = AuditAction.ARTICLE_PUBLISHED,
            actor  = self.user,
            obj    = self.article,
        )
        self.assertEqual(AuditLog.objects.count(), count_before + 1)

    def test_log_action_stores_actor(self):
        log_action(
            action = AuditAction.ARTICLE_PUBLISHED,
            actor  = self.user,
            obj    = self.article,
        )
        log = AuditLog.objects.filter(
            action=AuditAction.ARTICLE_PUBLISHED
        ).latest("created_at")
        self.assertEqual(log.actor, self.user)

    def test_log_action_stores_metadata(self):
        log_action(
            action   = AuditAction.ARTICLE_PUBLISHED,
            actor    = self.user,
            obj      = self.article,
            metadata = {"slug": self.article.slug},
        )
        log = AuditLog.objects.filter(
            action=AuditAction.ARTICLE_PUBLISHED
        ).latest("created_at")
        self.assertEqual(log.metadata["slug"], self.article.slug)

    def test_log_action_stores_object_repr(self):
        log_action(
            action      = AuditAction.ARTICLE_PUBLISHED,
            obj         = self.article,
            object_repr = "Test repr",
        )
        log = AuditLog.objects.filter(
            action=AuditAction.ARTICLE_PUBLISHED
        ).latest("created_at")
        self.assertEqual(log.object_repr, "Test repr")

    def test_log_action_never_raises(self):
        try:
            log_action(action="invalid.action")
        except Exception:
            self.fail("log_action raised an exception")

    def test_log_action_with_no_object(self):
        count_before = AuditLog.objects.count()
        log_action(
            action = AuditAction.USER_LOGIN,
            actor  = self.user,
        )
        self.assertEqual(AuditLog.objects.count(), count_before + 1)


class AuditSignalTests(TestCase):

    def setUp(self):
        self.user = make_user("signal_reporter")

    def test_article_created_logged(self):
        article = make_article(self.user, title="Signal Created Article")
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditAction.ARTICLE_CREATED,
                object_id=str(article.pk),
            ).exists()
        )

    def test_article_published_logged(self):
        article        = make_article(self.user)
        article.status = "archived"
        article.save()
        article.status = "published"
        article.save()
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditAction.ARTICLE_PUBLISHED,
                object_id=str(article.pk),
            ).exists()
        )

    def test_user_created_logged(self):
        new_user = make_user("new_signal_user")
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditAction.USER_CREATED,
                object_id=str(new_user.pk),
            ).exists()
        )


class AuditAPITests(APITestCase):

    def setUp(self):
        self.admin        = make_user("audit_admin",   role="admin")
        self.senior       = make_user("audit_senior",  role="senior_editor")
        self.editor       = make_user("audit_editor",  role="editor")
        self.author       = make_user("audit_author",  role="author")

        log_action(
            action      = AuditAction.ARTICLE_PUBLISHED,
            actor       = self.author,
            object_repr = "Test Article",
            metadata    = {"slug": "test-article"},
        )

    def test_list_requires_auth(self):
        r = self.client.get("/api/v1/audit/")
        self.assertEqual(r.status_code, 401)

    def test_author_cannot_access(self):
        self.client.force_authenticate(self.author)
        r = self.client.get("/api/v1/audit/")
        self.assertEqual(r.status_code, 403)

    def test_editor_cannot_access(self):
        self.client.force_authenticate(self.editor)
        r = self.client.get("/api/v1/audit/")
        self.assertEqual(r.status_code, 403)

    def test_senior_editor_can_access(self):
        self.client.force_authenticate(self.senior)
        r = self.client.get("/api/v1/audit/")
        self.assertEqual(r.status_code, 200)

    def test_admin_can_access(self):
        self.client.force_authenticate(self.admin)
        r = self.client.get("/api/v1/audit/")
        self.assertEqual(r.status_code, 200)

    def test_filter_by_action(self):
        self.client.force_authenticate(self.admin)
        r = self.client.get(
            f"/api/v1/audit/?action={AuditAction.ARTICLE_PUBLISHED}"
        )
        self.assertEqual(r.status_code, 200)
        for entry in r.data["results"]:
            self.assertEqual(entry["action"], AuditAction.ARTICLE_PUBLISHED)

    def test_filter_by_actor(self):
        self.client.force_authenticate(self.admin)
        r = self.client.get(f"/api/v1/audit/?actor={self.author.username}")
        self.assertEqual(r.status_code, 200)
        for entry in r.data["results"]:
            self.assertEqual(entry["actor_username"], self.author.username)

    def test_response_has_required_fields(self):
        self.client.force_authenticate(self.admin)
        r = self.client.get("/api/v1/audit/")
        self.assertEqual(r.status_code, 200)
        if r.data["results"]:
            entry = r.data["results"][0]
            for field in (
                "id", "actor_username", "action",
                "action_display", "object_repr",
                "metadata", "created_at",
            ):
                self.assertIn(field, entry)

    def test_object_history_endpoint(self):
        user    = make_user("history_author", role="author")
        article = make_article(user, title="History Test Article")
        log_action(
            action   = AuditAction.ARTICLE_PUBLISHED,
            actor    = user,
            obj      = article,
            metadata = {"slug": article.slug},
        )
        self.client.force_authenticate(self.admin)
        r = self.client.get(f"/api/v1/audit/article/{article.pk}/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("results", r.data)


class PruneAuditLogCommandTests(TestCase):

    def test_prune_command_runs(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command("prune_audit_log", "--dry-run", stdout=out)
        self.assertIn("DRY RUN", out.getvalue())

    def test_prune_deletes_old_records(self):
        from datetime import timedelta
        from django.utils import timezone
        from django.core.management import call_command

        old_log = AuditLog.objects.create(
            action     = AuditAction.ARTICLE_CREATED,
            created_at = timezone.now() - timedelta(days=800),
        )
        call_command("prune_audit_log", "--days=730")
        self.assertFalse(AuditLog.objects.filter(pk=old_log.pk).exists())

    def test_prune_keeps_recent_records(self):
        from django.core.management import call_command

        recent_log = AuditLog.objects.create(
            action = AuditAction.ARTICLE_CREATED,
        )
        call_command("prune_audit_log", "--days=730")
        self.assertTrue(AuditLog.objects.filter(pk=recent_log.pk).exists())