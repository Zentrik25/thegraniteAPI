from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.text import slugify


class StaffRole(models.TextChoices):
    CONTRIBUTOR   = "contributor",   "Contributor"
    AUTHOR        = "author",        "Author"
    MODERATOR     = "moderator",     "Moderator"  
    EDITOR        = "editor",        "Editor"
    SENIOR_EDITOR = "senior_editor", "Senior Editor"
    ADMIN         = "admin",         "Admin"


PUBLISH_ROLES      = frozenset({StaffRole.EDITOR, StaffRole.SENIOR_EDITOR, StaffRole.ADMIN})
EDIT_ANY_ROLES     = frozenset({StaffRole.EDITOR, StaffRole.SENIOR_EDITOR, StaffRole.ADMIN})
MANAGE_STAFF_ROLES = frozenset({StaffRole.SENIOR_EDITOR, StaffRole.ADMIN})


class StaffUser(AbstractUser):
    """
    Custom user model for The Granite Post CMS staff.

    is_staff / is_superuser are managed automatically by
    users.signals.sync_role_to_django_permissions — do not set them directly.
    Set `role` instead.
    """

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    display_name = models.CharField(
        max_length=120,
        blank=True,
        help_text="Public byline shown on articles. Falls back to full name then username.",
    )
    slug = models.SlugField(
        max_length=120,
        unique=True,
        blank=True,
        help_text="Auto-generated from username. Used in author profile URLs.",
    )
    title = models.CharField(
        max_length=120,
        blank=True,
        help_text="Job title, e.g. 'Senior Reporter' or 'Photo Editor'.",
    )

    # ------------------------------------------------------------------
    # Role
    # ------------------------------------------------------------------
    role = models.CharField(
        max_length=20,
        choices=StaffRole.choices,
        default=StaffRole.AUTHOR,
        db_index=True,
    )

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------
    bio        = models.TextField(blank=True)
    avatar_url = models.URLField(blank=True)
    beat       = models.CharField(
        max_length=120,
        blank=True,
        help_text="Editorial beat, e.g. 'Politics', 'Sport', 'Business'.",
    )

    # ------------------------------------------------------------------
    # Contact / social
    # ------------------------------------------------------------------
    email_public    = models.EmailField(
        blank=True,
        help_text="Public contact email shown on the author profile page.",
    )
    twitter_handle  = models.CharField(max_length=60, blank=True)
    linkedin_url    = models.URLField(blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = "Staff User"
        verbose_name_plural = "Staff Users"

    def __str__(self):
        return self.byline

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.display_name or self.username)
            slug = base
            n = 1
            while StaffUser.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def byline(self) -> str:
        return self.display_name or self.get_full_name() or self.username

    @property
    def can_publish(self) -> bool:
        """Editors and above may publish articles."""
        return self.role in (
            StaffRole.EDITOR,
            StaffRole.SENIOR_EDITOR,
            StaffRole.ADMIN,
        ) or self.is_superuser

    @property
    def can_edit_any_article(self) -> bool:
        """Editors and above may edit any article, not just their own."""
        return self.role in (
            StaffRole.EDITOR,
            StaffRole.SENIOR_EDITOR,
            StaffRole.ADMIN,
        ) or self.is_superuser

    @property
    def can_manage_staff(self) -> bool:
        """Senior editors and admins may create / edit staff accounts."""
        return self.role in (
            StaffRole.SENIOR_EDITOR,
            StaffRole.ADMIN,
        ) or self.is_superuser

    @property
    def is_editorial_admin(self) -> bool:
        """Full editorial control — admin role or Django superuser."""
        return self.role == StaffRole.ADMIN or self.is_superuser

    def can_edit_article(self, article) -> bool:
        """Editors and above can edit any article; authors only their own draft/review."""
        if self.is_superuser or self.role == StaffRole.ADMIN:
            return True
        if self.role in (StaffRole.EDITOR, StaffRole.SENIOR_EDITOR):
            return article.status != "archived"
        return article.author == self and article.status in ("draft", "review")

    def can_submit_for_review(self, article) -> bool:
        """Authors can submit their own draft articles for editorial review."""
        return article.author == self and article.status == "draft"
