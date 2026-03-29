from django.db import models
from django.utils import timezone


class Redirect(models.Model):
    """
    A permanent 301 redirect from an old URL path to a new one.

    Created automatically when an Article slug changes.
    Can also be created manually in the admin for any path change.

    old_path   The path that triggers the redirect.
               Always starts with /. Example: /articles/old-slug/

    new_path   The path the browser is redirected to.
               Always starts with /. Example: /articles/new-slug/

    is_active  Inactive redirects are ignored by the middleware.

    hits       How many times this redirect has been followed.

    created_by Who created this: "signal" or "manual".
    """

    old_path = models.CharField(
        max_length=500,
        unique=True,
        db_index=True,
        help_text="The old URL path. Must start with /.",
    )
    new_path = models.CharField(
        max_length=500,
        help_text="The new URL path to redirect to. Must start with /.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Inactive redirects are ignored by the middleware.",
    )
    hits = models.PositiveIntegerField(
        default=0,
        help_text="Number of times this redirect has been followed.",
    )
    created_by = models.CharField(
        max_length=50,
        default="manual",
        help_text="Who created this redirect: 'signal' or 'manual'.",
    )
    note = models.TextField(
        blank=True,
        help_text="Optional note explaining why this redirect exists.",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes  = [
            models.Index(
                fields=["is_active", "old_path"],
                name="redirects_active_path_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.old_path} → {self.new_path}"

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if self.old_path and not self.old_path.startswith("/"):
            self.old_path = f"/{self.old_path}"
        if self.new_path and not self.new_path.startswith("/"):
            self.new_path = f"/{self.new_path}"

        if self.old_path == self.new_path:
            raise ValidationError(
                "Old path and new path cannot be the same. "
                "This would create an infinite redirect loop."
            )

    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)

    def record_hit(self) -> None:
        from django.db.models import F
        Redirect.objects.filter(pk=self.pk).update(hits=F("hits") + 1)