from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from articles.models import Article, Category, PublishStatus

from .models import StaffRole, StaffUser
from .permissions import (
    CanEditArticle,
    CanManageStaff,
    CanPublish,
    IsAdmin,
    IsEditorOrAbove,
    IsSeniorEditorOrAbove,
)


def make_user(username, role=StaffRole.CONTRIBUTOR, **kwargs):
    kwargs.setdefault("first_name", username.capitalize())
    kwargs.setdefault("last_name", "Test")
    return StaffUser.objects.create_user(
        username=username,
        password="testpass123",
        email=f"{username}@granite.co.zw",
        role=role,
        **kwargs,
    )


def make_article(author, art_status=PublishStatus.DRAFT, **kwargs):
    return Article.objects.create(
        title=kwargs.pop("title", "Test Article"),
        body="Body.",
        author=author,
        status=art_status,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class StaffUserModelTests(TestCase):

    def test_slug_auto_generated_from_display_name(self):
        u = make_user("reporter", display_name="Chipo Moyo")
        self.assertEqual(u.slug, "chipo-moyo")

    def test_byline_uses_display_name(self):
        u = make_user("reporter", display_name="Chipo Moyo")
        self.assertEqual(u.byline, "Chipo Moyo")

    def test_byline_falls_back_to_full_name(self):
        u = make_user("reporter2", first_name="Tendai", last_name="Moyo")
        self.assertEqual(u.byline, "Tendai Moyo")

    def test_contributor_cannot_publish(self):
        self.assertFalse(make_user("c", role=StaffRole.CONTRIBUTOR).can_publish)

    def test_author_cannot_publish(self):
        self.assertFalse(make_user("a", role=StaffRole.AUTHOR).can_publish)

    def test_editor_can_publish(self):
        self.assertTrue(make_user("e", role=StaffRole.EDITOR).can_publish)

    def test_senior_editor_can_publish(self):
        self.assertTrue(make_user("se", role=StaffRole.SENIOR_EDITOR).can_publish)

    def test_admin_can_publish(self):
        self.assertTrue(make_user("ad", role=StaffRole.ADMIN).can_publish)

    def test_slug_collision_resolved(self):
        u1 = make_user("user1", display_name="John Doe")
        u2 = make_user("user2", display_name="John Doe")
        self.assertNotEqual(u1.slug, u2.slug)
        self.assertTrue(u2.slug.startswith("john-doe-"))


# ---------------------------------------------------------------------------
# RLS — can_edit_article
# ---------------------------------------------------------------------------

class ArticleRLSTests(TestCase):

    def setUp(self):
        self.author    = make_user("author1",  role=StaffRole.AUTHOR)
        self.editor    = make_user("editor1",  role=StaffRole.EDITOR)
        self.admin     = make_user("admin1",   role=StaffRole.ADMIN)
        self.other     = make_user("other1",   role=StaffRole.AUTHOR)

        self.draft     = make_article(self.author, art_status=PublishStatus.DRAFT)
        self.review    = make_article(self.author, art_status=PublishStatus.REVIEW)
        self.published = make_article(self.author, art_status=PublishStatus.PUBLISHED)
        self.archived  = make_article(self.author, art_status=PublishStatus.ARCHIVED)

    def test_author_can_edit_own_draft(self):
        self.assertTrue(self.author.can_edit_article(self.draft))

    def test_author_can_edit_own_review(self):
        self.assertTrue(self.author.can_edit_article(self.review))

    def test_author_cannot_edit_own_published(self):
        self.assertFalse(self.author.can_edit_article(self.published))

    def test_author_cannot_edit_own_archived(self):
        self.assertFalse(self.author.can_edit_article(self.archived))

    def test_author_cannot_edit_other_authors_article(self):
        self.assertFalse(self.other.can_edit_article(self.draft))

    def test_editor_can_edit_any_draft(self):
        self.assertTrue(self.editor.can_edit_article(self.draft))

    def test_editor_can_edit_any_published(self):
        self.assertTrue(self.editor.can_edit_article(self.published))

    def test_editor_cannot_edit_archived(self):
        self.assertFalse(self.editor.can_edit_article(self.archived))

    def test_admin_can_edit_archived(self):
        self.assertTrue(self.admin.can_edit_article(self.archived))

    def test_author_can_submit_own_draft(self):
        self.assertTrue(self.author.can_submit_for_review(self.draft))

    def test_author_cannot_submit_already_in_review(self):
        self.assertFalse(self.author.can_submit_for_review(self.review))

    def test_other_cannot_submit_someone_elses_draft(self):
        self.assertFalse(self.other.can_submit_for_review(self.draft))


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

class SignalSyncTests(TestCase):

    def test_contributor_not_staff(self):
        u = make_user("c2", role=StaffRole.CONTRIBUTOR)
        u.refresh_from_db()
        self.assertFalse(u.is_staff)
        self.assertFalse(u.is_superuser)

    def test_editor_is_staff(self):
        u = make_user("e2", role=StaffRole.EDITOR)
        u.refresh_from_db()
        self.assertTrue(u.is_staff)
        self.assertFalse(u.is_superuser)

    def test_admin_is_superuser(self):
        u = make_user("ad2", role=StaffRole.ADMIN)
        u.refresh_from_db()
        self.assertTrue(u.is_staff)
        self.assertTrue(u.is_superuser)

    def test_group_assigned_on_create(self):
        u = make_user("e3", role=StaffRole.EDITOR)
        self.assertIn("Editors", list(u.groups.values_list("name", flat=True)))

    def test_group_updated_on_role_change(self):
        u = make_user("a2", role=StaffRole.AUTHOR)
        u.role = StaffRole.EDITOR
        u.save()
        group_names = list(u.groups.values_list("name", flat=True))
        self.assertIn("Editors", group_names)
        self.assertNotIn("Authors", group_names)


# ---------------------------------------------------------------------------
# Permission classes
# ---------------------------------------------------------------------------

class PermissionClassTests(TestCase):

    def _check(self, permission_class, role, expected: bool):
        user    = make_user(f"p_{role}_{permission_class.__name__}", role=role)
        factory = APIRequestFactory()
        request = factory.get("/")
        request.user = user
        result  = permission_class().has_permission(request, None)
        self.assertEqual(
            result, expected,
            f"{permission_class.__name__} returned {result} for role {role}, expected {expected}",
        )

    def test_can_publish(self):
        self._check(CanPublish, StaffRole.CONTRIBUTOR,   False)
        self._check(CanPublish, StaffRole.AUTHOR,        False)
        self._check(CanPublish, StaffRole.EDITOR,        True)
        self._check(CanPublish, StaffRole.SENIOR_EDITOR, True)
        self._check(CanPublish, StaffRole.ADMIN,         True)

    def test_is_editor_or_above(self):
        self._check(IsEditorOrAbove, StaffRole.CONTRIBUTOR,   False)
        self._check(IsEditorOrAbove, StaffRole.AUTHOR,        False)
        self._check(IsEditorOrAbove, StaffRole.EDITOR,        True)
        self._check(IsEditorOrAbove, StaffRole.SENIOR_EDITOR, True)
        self._check(IsEditorOrAbove, StaffRole.ADMIN,         True)

    def test_can_manage_staff(self):
        self._check(CanManageStaff, StaffRole.CONTRIBUTOR,   False)
        self._check(CanManageStaff, StaffRole.AUTHOR,        False)
        self._check(CanManageStaff, StaffRole.EDITOR,        False)
        self._check(CanManageStaff, StaffRole.SENIOR_EDITOR, True)
        self._check(CanManageStaff, StaffRole.ADMIN,         True)

    def test_is_admin(self):
        self._check(IsAdmin, StaffRole.SENIOR_EDITOR, False)
        self._check(IsAdmin, StaffRole.ADMIN,         True)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class UserAPITests(APITestCase):

    def setUp(self):
        self.author = make_user("pub_author", role=StaffRole.AUTHOR, display_name="Chipo Moyo")
        self.cat    = Category.objects.create(name="News")
        make_article(self.author, art_status=PublishStatus.PUBLISHED, category=self.cat)

    def test_public_user_list(self):
        r = self.client.get("/api/v1/users/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        slugs = [u["slug"] for u in r.data["results"]]
        self.assertIn(self.author.slug, slugs)

    def test_public_user_detail(self):
        r = self.client.get(f"/api/v1/users/{self.author.slug}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["user"]["slug"], self.author.slug)
        self.assertIn("articles", r.data)

    def test_public_user_detail_404(self):
        r = self.client.get("/api/v1/users/does-not-exist/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)


class StaffManagementAPITests(APITestCase):

    def setUp(self):
        self.senior = make_user("senioreds", role=StaffRole.SENIOR_EDITOR)
        self.editor = make_user("eds",       role=StaffRole.EDITOR)
        self.contrib = make_user("contrib",  role=StaffRole.CONTRIBUTOR)

    def test_editor_can_view_staff_list(self):
        self.client.force_authenticate(self.editor)
        self.assertEqual(self.client.get("/api/v1/staff/").status_code, 200)

    def test_contributor_cannot_view_staff_list(self):
        self.client.force_authenticate(self.contrib)
        self.assertEqual(self.client.get("/api/v1/staff/").status_code, 403)

    def test_senior_editor_can_create_staff(self):
        self.client.force_authenticate(self.senior)
        r = self.client.post("/api/v1/staff/", {
            "username":   "newreporter",
            "email":      "newreporter@granite.co.zw",
            "password":   "Str0ng!Pass#99",
            "first_name": "New",
            "last_name":  "Reporter",
            "role":       StaffRole.AUTHOR,
        })
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)

    def test_editor_cannot_create_staff(self):
        self.client.force_authenticate(self.editor)
        r = self.client.post("/api/v1/staff/", {
            "username": "newreporter2",
            "email":    "nr2@granite.co.zw",
            "role":     StaffRole.CONTRIBUTOR,
        })
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_senior_editor_cannot_assign_admin_role(self):
        self.client.force_authenticate(self.senior)
        r = self.client.post("/api/v1/staff/", {
            "username": "newadmin",
            "email":    "na@granite.co.zw",
            "password": "Str0ng!Pass#99",
            "role":     StaffRole.ADMIN,
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_deactivate_instead_of_delete(self):
        self.client.force_authenticate(self.senior)
        target = make_user("target_user", role=StaffRole.CONTRIBUTOR)
        r = self.client.delete(f"/api/v1/staff/{target.pk}/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        target.refresh_from_db()
        self.assertFalse(target.is_active)


class MeAPITests(APITestCase):

    def setUp(self):
        self.author = make_user("me_author", role=StaffRole.AUTHOR)

    def test_me_returns_own_profile(self):
        self.client.force_authenticate(self.author)
        r = self.client.get("/api/v1/auth/me/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["username"], self.author.username)

    def test_me_role_is_read_only(self):
        self.client.force_authenticate(self.author)
        self.client.patch("/api/v1/auth/me/", {"role": StaffRole.ADMIN})
        self.author.refresh_from_db()
        self.assertEqual(self.author.role, StaffRole.AUTHOR)

    def test_change_password_success(self):
        self.client.force_authenticate(self.author)
        r = self.client.post("/api/v1/auth/change-password/", {
            "current_password": "testpass123",
            "new_password":     "N3wStr0ng!Pass#99",
        })
        self.assertEqual(r.status_code, 200)

    def test_change_password_wrong_current(self):
        self.client.force_authenticate(self.author)
        r = self.client.post("/api/v1/auth/change-password/", {
            "current_password": "wrongpassword",
            "new_password":     "N3wStr0ng!Pass#99",
        })
        self.assertEqual(r.status_code, 400)

    def test_unauthenticated_cannot_access_me(self):
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)
