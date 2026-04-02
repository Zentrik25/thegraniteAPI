from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from articles.models import Article, Category, PublishStatus

from .models import Comment, CommentStatus

User = get_user_model()


def make_user(username="reporter", role="author"):
    return User.objects.create_user(
        username=username,
        password="testpass123",
        email=f"{username}@granite.co.zw",
        role=role,
    )


def make_article(author, art_status=PublishStatus.PUBLISHED):
    return Article.objects.create(
        title="Test Article",
        body="Body content.",
        author=author,
        status=art_status,
    )


def make_comment(article, author_name="Reader", status=CommentStatus.APPROVED, parent=None):
    return Comment.objects.create(
        article     = article,
        author_name = author_name,
        author_email = f"{author_name.lower()}@reader.com",
        body        = "This is a test comment.",
        status      = status,
        parent      = parent,
    )


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class CommentModelTests(TestCase):

    def setUp(self):
        self.user    = make_user()
        self.article = make_article(self.user)

    def test_hash_ip_returns_64_char_hex(self):
        h = Comment.hash_ip("192.168.1.1")
        self.assertEqual(len(h), 64)

    def test_is_reply_false_for_top_level(self):
        c = make_comment(self.article)
        self.assertFalse(c.is_reply)

    def test_is_reply_true_for_reply(self):
        parent = make_comment(self.article)
        reply  = make_comment(self.article, parent=parent)
        self.assertTrue(reply.is_reply)

    def test_is_approved_true_for_approved(self):
        c = make_comment(self.article, status=CommentStatus.APPROVED)
        self.assertTrue(c.is_approved)

    def test_is_approved_false_for_pending(self):
        c = make_comment(self.article, status=CommentStatus.PENDING)
        self.assertFalse(c.is_approved)

    def test_default_status_is_pending(self):
        c = Comment.objects.create(
            article      = self.article,
            author_name  = "Reader",
            author_email = "reader@test.com",
            body         = "Test comment.",
        )
        self.assertEqual(c.status, CommentStatus.PENDING)


# ---------------------------------------------------------------------------
# API — public comment list
# ---------------------------------------------------------------------------

class ArticleCommentsGetTests(APITestCase):

    def setUp(self):
        self.user    = make_user()
        self.article = make_article(self.user)
        self.url     = f"/api/v1/articles/{self.article.slug}/comments/"

        self.approved = make_comment(
            self.article, "Approved Reader",
            status=CommentStatus.APPROVED,
        )
        self.pending = make_comment(
            self.article, "Pending Reader",
            status=CommentStatus.PENDING,
        )
        self.rejected = make_comment(
            self.article, "Rejected Reader",
            status=CommentStatus.REJECTED,
        )

    def test_get_returns_200(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_get_returns_only_approved(self):
        r = self.client.get(self.url)
        names = [c["author_name"] for c in r.data["results"]]
        self.assertIn("Approved Reader", names)
        self.assertNotIn("Pending Reader", names)
        self.assertNotIn("Rejected Reader", names)

    def test_get_does_not_expose_email(self):
        r = self.client.get(self.url)
        for comment in r.data["results"]:
            self.assertNotIn("author_email", comment)

    def test_get_returns_count(self):
        r = self.client.get(self.url)
        self.assertEqual(r.data["count"], 1)

    def test_approved_replies_included(self):
        reply = make_comment(
            self.article, "Replier",
            status=CommentStatus.APPROVED,
            parent=self.approved,
        )
        r = self.client.get(self.url)
        top_level = next(
            c for c in r.data["results"]
            if c["id"] == self.approved.pk
        )
        self.assertEqual(len(top_level["replies"]), 1)

    def test_draft_article_returns_404(self):
        draft = make_article(self.user, art_status=PublishStatus.DRAFT)
        r = self.client.get(f"/api/v1/articles/{draft.slug}/comments/")
        self.assertEqual(r.status_code, 404)


# ---------------------------------------------------------------------------
# API — submit comment
# ---------------------------------------------------------------------------

class SubmitCommentTests(APITestCase):

    def setUp(self):
        self.user    = make_user()
        self.article = make_article(self.user)
        self.url     = f"/api/v1/articles/{self.article.slug}/comments/"
        caches["throttle"].clear()

    def tearDown(self):
        caches["throttle"].clear()

    def test_post_creates_pending_comment(self):
        r = self.client.post(self.url, {
            "author_name":  "New Reader",
            "author_email": "reader@test.com",
            "body":         "Great article!",
        })
        self.assertEqual(r.status_code, 201)
        self.assertEqual(
            Comment.objects.filter(status=CommentStatus.PENDING).count(), 1
        )

    def test_post_returns_201_with_id(self):
        r = self.client.post(self.url, {
            "author_name":  "Reader",
            "author_email": "r@test.com",
            "body":         "Comment body.",
        })
        self.assertEqual(r.status_code, 201)
        self.assertIn("id", r.data)

    def test_post_comment_not_immediately_visible(self):
        self.client.post(self.url, {
            "author_name":  "Reader",
            "author_email": "r@test.com",
            "body":         "Comment body.",
        })
        r = self.client.get(self.url)
        self.assertEqual(r.data["count"], 0)

    def test_post_reply_to_approved_comment(self):
        parent = make_comment(self.article, status=CommentStatus.APPROVED)
        r = self.client.post(self.url, {
            "author_name":  "Replier",
            "author_email": "r@test.com",
            "body":         "Reply body.",
            "parent":       parent.pk,
        })
        self.assertEqual(r.status_code, 201)

    def test_post_reply_to_reply_rejected(self):
        parent = make_comment(self.article, status=CommentStatus.APPROVED)
        reply  = make_comment(
            self.article, status=CommentStatus.APPROVED, parent=parent
        )
        r = self.client.post(self.url, {
            "author_name":  "Replier",
            "author_email": "r@test.com",
            "body":         "Reply to reply.",
            "parent":       reply.pk,
        })
        self.assertEqual(r.status_code, 400)

    def test_post_reply_to_pending_comment_rejected(self):
        pending = make_comment(self.article, status=CommentStatus.PENDING)
        r = self.client.post(self.url, {
            "author_name":  "Replier",
            "author_email": "r@test.com",
            "body":         "Reply to pending.",
            "parent":       pending.pk,
        })
        self.assertEqual(r.status_code, 400)

    def test_post_missing_required_fields_returns_400(self):
        r = self.client.post(self.url, {"author_name": "Reader"})
        self.assertEqual(r.status_code, 400)

    def test_post_empty_body_returns_400(self):
        r = self.client.post(self.url, {
            "author_name":  "Reader",
            "author_email": "r@test.com",
            "body":         " ",
        })
        self.assertEqual(r.status_code, 400)


# ---------------------------------------------------------------------------
# API — moderation
# ---------------------------------------------------------------------------

class ModerationTests(APITestCase):

    def setUp(self):
        self.moderator = make_user("moderator", role="moderator")
        self.author    = make_user("author1",   role="author")
        self.user      = make_user("reporter",  role="contributor")
        self.article   = make_article(self.author)
        self.pending   = make_comment(
            self.article, "Pending Reader",
            status=CommentStatus.PENDING,
        )

    def test_moderation_list_requires_auth(self):
        r = self.client.get("/api/v1/moderation/comments/")
        self.assertEqual(r.status_code, 401)

    def test_contributor_cannot_access_moderation(self):
        self.client.force_authenticate(self.user)
        r = self.client.get("/api/v1/moderation/comments/")
        self.assertEqual(r.status_code, 403)

    def test_moderator_can_access_moderation_list(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.get("/api/v1/moderation/comments/")
        self.assertEqual(r.status_code, 200)

    def test_moderation_list_shows_pending_by_default(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.get("/api/v1/moderation/comments/")
        ids = [c["id"] for c in r.data["results"]]
        self.assertIn(self.pending.pk, ids)

    def test_moderation_list_includes_email(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.get("/api/v1/moderation/comments/")
        comment = r.data["results"][0]
        self.assertIn("author_email", comment)

    def test_approve_comment(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.patch(
            f"/api/v1/moderation/comments/{self.pending.pk}/",
            {"action": "approve"},
        )
        self.assertEqual(r.status_code, 200)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, CommentStatus.APPROVED)

    def test_reject_comment(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.patch(
            f"/api/v1/moderation/comments/{self.pending.pk}/",
            {"action": "reject"},
        )
        self.assertEqual(r.status_code, 200)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, CommentStatus.REJECTED)

    def test_approved_comment_appears_in_public_feed(self):
        self.client.force_authenticate(self.moderator)
        self.client.patch(
            f"/api/v1/moderation/comments/{self.pending.pk}/",
            {"action": "approve"},
        )
        self.client.logout()
        r = self.client.get(
            f"/api/v1/articles/{self.article.slug}/comments/"
        )
        ids = [c["id"] for c in r.data["results"]]
        self.assertIn(self.pending.pk, ids)

    def test_invalid_action_returns_400(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.patch(
            f"/api/v1/moderation/comments/{self.pending.pk}/",
            {"action": "delete"},
        )
        self.assertEqual(r.status_code, 400)


# ---------------------------------------------------------------------------
# Rate limiting — abuse prevention
# ---------------------------------------------------------------------------

class CommentRateLimitTests(APITestCase):
    """
    CommentRateThrottle allows 3 comments per hour per IP.
    The 4th request from the same IP must receive HTTP 429.
    """

    def setUp(self):
        self.user    = make_user("rllimit", role="author")
        self.article = make_article(self.user)
        self.url     = f"/api/v1/articles/{self.article.slug}/comments/"
        caches["throttle"].clear()

    def tearDown(self):
        caches["throttle"].clear()

    def _post_comment(self, n: int):
        return self.client.post(self.url, {
            "author_name":  f"Spammer{n}",
            "author_email": f"spam{n}@test.com",
            "body":         f"Comment number {n}.",
        })

    def test_first_three_comments_succeed(self):
        for i in range(1, 4):
            r = self._post_comment(i)
            self.assertEqual(r.status_code, 201, msg=f"Comment {i} should be 201, got {r.status_code}")

    def test_fourth_comment_returns_429(self):
        for i in range(1, 4):
            self._post_comment(i)
        r = self._post_comment(4)
        self.assertEqual(r.status_code, 429)

    def test_429_response_includes_retry_after(self):
        for i in range(1, 5):
            r = self._post_comment(i)
        # Last request should be 429; Retry-After header must be present
        self.assertEqual(r.status_code, 429)
        self.assertIn("Retry-After", r)


# ---------------------------------------------------------------------------
# Bulk moderation
# ---------------------------------------------------------------------------

class BulkModerationTests(APITestCase):
    """
    Approve or reject multiple comments in a single request via the
    moderation action endpoint called repeatedly, verifying state changes
    are independent and idempotent.
    """

    def setUp(self):
        self.moderator = make_user("bulkmod", role="moderator")
        self.author    = make_user("bulkauth", role="author")
        self.article   = make_article(self.author)
        self.c1 = make_comment(self.article, "Alpha", status=CommentStatus.PENDING)
        self.c2 = make_comment(self.article, "Beta",  status=CommentStatus.PENDING)
        self.c3 = make_comment(self.article, "Gamma", status=CommentStatus.PENDING)
        self.client.force_authenticate(self.moderator)

    def test_approve_multiple_comments_independently(self):
        for pk in (self.c1.pk, self.c2.pk):
            r = self.client.patch(
                f"/api/v1/moderation/comments/{pk}/",
                {"action": "approve"},
            )
            self.assertEqual(r.status_code, 200)

        self.c1.refresh_from_db()
        self.c2.refresh_from_db()
        self.c3.refresh_from_db()

        self.assertEqual(self.c1.status, CommentStatus.APPROVED)
        self.assertEqual(self.c2.status, CommentStatus.APPROVED)
        self.assertEqual(self.c3.status, CommentStatus.PENDING)

    def test_reject_one_does_not_affect_others(self):
        self.client.patch(
            f"/api/v1/moderation/comments/{self.c1.pk}/",
            {"action": "reject"},
        )
        self.c2.refresh_from_db()
        self.assertEqual(self.c2.status, CommentStatus.PENDING)

    def test_re_approve_already_approved_is_idempotent(self):
        # Approve twice — second call must still return 200 and leave status APPROVED.
        self.client.patch(
            f"/api/v1/moderation/comments/{self.c1.pk}/",
            {"action": "approve"},
        )
        r = self.client.patch(
            f"/api/v1/moderation/comments/{self.c1.pk}/",
            {"action": "approve"},
        )
        self.assertEqual(r.status_code, 200)
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.status, CommentStatus.APPROVED)
