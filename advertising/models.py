"""
models.py - Advertising models for The Granite Post.

This app powers ad zone configuration, campaign management, and lightweight
analytics for impressions and clicks.
"""

import hashlib
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

ZONE_CACHE_KEY = "ads:zone:{slug}"

STANDARD_ZONE_SIZES = {
    "leaderboard":   (728, 90),
    "sidebar":       (300, 250),
    "in_article":    (300, 250),
    "sticky_footer": (320, 50),
    "hero":          (970, 250),
    "interstitial":  (320, 480),
}


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AdZoneType(models.TextChoices):
    LEADERBOARD   = "leaderboard",   "Leaderboard"
    SIDEBAR       = "sidebar",       "Sidebar"
    IN_ARTICLE    = "in_article",    "In Article"
    STICKY_FOOTER = "sticky_footer", "Sticky Footer"
    HERO          = "hero",          "Hero"
    INTERSTITIAL  = "interstitial",  "Interstitial"


class AdCampaignStatus(models.TextChoices):
    DRAFT     = "draft",     "Draft"
    ACTIVE    = "active",    "Active"
    PAUSED    = "paused",    "Paused"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


def make_zone_cache_key(slug: str) -> str:
    return ZONE_CACHE_KEY.format(slug=slug)


def _unique_slug(model_class, base_text: str, fallback: str, max_length: int, current_pk=None) -> str:
    base_slug = slugify(base_text)[:max_length] or fallback
    slug      = base_slug
    counter   = 1

    while model_class.objects.filter(slug=slug).exclude(pk=current_pk).exists():
        suffix = f"-{counter}"
        slug   = f"{base_slug[:max_length - len(suffix)]}{suffix}"
        counter += 1

    return slug


def _hash_value(raw_value: str) -> str:
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()


class AdZone(TimeStampedModel):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    zone_type = models.CharField(
        max_length=20,
        choices=AdZoneType.choices,
        db_index=True,
    )
    description = models.TextField(blank=True)
    width       = models.PositiveIntegerField(help_text="Width in pixels.")
    height      = models.PositiveIntegerField(help_text="Height in pixels.")
    is_active   = models.BooleanField(default=True, db_index=True)
    max_ads     = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["name"]
        indexes  = [
            models.Index(fields=["zone_type", "is_active"], name="ads_zone_type_active_idx"),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        super().clean()
        expected = STANDARD_ZONE_SIZES.get(self.zone_type)
        if expected is None:
            return

        expected_width, expected_height = expected
        errors = {}

        if self.width != expected_width:
            errors["width"] = f"{self.get_zone_type_display()} width must be {expected_width}px."
        if self.height != expected_height:
            errors["height"] = f"{self.get_zone_type_display()} height must be {expected_height}px."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = _unique_slug(AdZone, self.name, "ad-zone", 110, self.pk)
        super().save(*args, **kwargs)


class Advertiser(TimeStampedModel):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    company_name  = models.CharField(max_length=200)
    contact_name  = models.CharField(max_length=100)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=20, blank=True)
    website_url   = models.URLField(blank=True)
    is_active     = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["company_name"]

    def __str__(self) -> str:
        return self.company_name


class AdCampaign(TimeStampedModel):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    advertiser = models.ForeignKey(
        Advertiser,
        on_delete=models.CASCADE,
        related_name="campaigns",
    )
    name = models.CharField(max_length=200)
    zone = models.ForeignKey(
        AdZone,
        on_delete=models.CASCADE,
        related_name="campaigns",
    )
    status = models.CharField(
        max_length=20,
        choices=AdCampaignStatus.choices,
        default=AdCampaignStatus.DRAFT,
        db_index=True,
    )
    creative_url = models.URLField()
    click_url    = models.URLField()
    alt_text     = models.CharField(max_length=255)
    start_date   = models.DateField()
    end_date     = models.DateField()
    total_budget = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    cost_per_impression = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    cost_per_click = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    impression_cap = models.PositiveIntegerField(null=True, blank=True)
    click_cap      = models.PositiveIntegerField(null=True, blank=True)
    total_impressions = models.PositiveIntegerField(default=0)
    total_clicks      = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes  = [
            models.Index(fields=["zone", "status"], name="ads_campaign_zone_status_idx"),
            models.Index(fields=["status", "start_date", "end_date"], name="ads_campaign_dates_idx"),
            models.Index(fields=["advertiser", "status"], name="ads_campaign_adv_status_idx"),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        super().clean()
        if self.end_date < self.start_date:
            raise ValidationError({"end_date": "end_date must be on or after start_date."})

    @property
    def ctr(self) -> float:
        if self.total_impressions == 0:
            return 0.0
        return round((self.total_clicks / self.total_impressions) * 100, 2)

    @property
    def is_running(self) -> bool:
        today = timezone.localdate()
        return (
            self.status == AdCampaignStatus.ACTIVE
            and self.start_date <= today <= self.end_date
        )


class AdImpression(models.Model):
    id = models.BigAutoField(primary_key=True)
    campaign = models.ForeignKey(
        AdCampaign,
        on_delete=models.CASCADE,
        related_name="impressions",
    )
    ip_hash      = models.CharField(max_length=64)
    session_hash = models.CharField(max_length=64, blank=True)
    page_url     = models.CharField(max_length=500)
    viewed_at    = models.DateTimeField(default=timezone.now, db_index=True)
    viewed_date  = models.DateField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "ip_hash", "viewed_date"],
                name="ads_one_impression_per_ip_day",
            ),
        ]
        indexes = [
            models.Index(fields=["campaign", "viewed_at"], name="ads_impression_time_idx"),
            models.Index(fields=["viewed_date"], name="ads_impression_date_idx"),
        ]

    def __str__(self) -> str:
        return f"Impression campaign_id={self.campaign_id} on {self.viewed_date}"

    @staticmethod
    def hash_ip(ip: str) -> str:
        return _hash_value(ip)

    @staticmethod
    def hash_session(session_key: str) -> str:
        if not session_key:
            return ""
        return _hash_value(session_key)


class AdClick(models.Model):
    id = models.BigAutoField(primary_key=True)
    campaign = models.ForeignKey(
        AdCampaign,
        on_delete=models.CASCADE,
        related_name="clicks",
    )
    ip_hash    = models.CharField(max_length=64)
    clicked_at = models.DateTimeField(default=timezone.now, db_index=True)
    page_url   = models.CharField(max_length=500)
    referrer   = models.CharField(max_length=500, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["campaign", "clicked_at"], name="ads_click_time_idx"),
        ]

    def __str__(self) -> str:
        return f"Click campaign_id={self.campaign_id} at {self.clicked_at:%Y-%m-%d %H:%M:%S}"

    @staticmethod
    def hash_ip(ip: str) -> str:
        return _hash_value(ip)
