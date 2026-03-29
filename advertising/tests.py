from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import (
    AdCampaign,
    AdCampaignStatus,
    AdClick,
    AdImpression,
    Advertiser,
    AdZone,
    AdZoneType,
)

User = get_user_model()


def make_user(username="editor", role="editor"):
    return User.objects.create_user(
        username=username,
        password="testpass123",
        email=f"{username}@granite.co.zw",
        role=role,
    )


def make_zone(
    name="Homepage Leaderboard",
    zone_type=AdZoneType.LEADERBOARD,
    max_ads=1,
):
    return AdZone.objects.create(
        name=name,
        zone_type=zone_type,
        width=728,
        height=90,
        max_ads=max_ads,
        is_active=True,
    )


def make_advertiser(company_name="Granite Sponsor"):
    return Advertiser.objects.create(
        company_name=company_name,
        contact_name="Sales Contact",
        contact_email="sales@example.com",
    )


def make_campaign(
    advertiser,
    zone,
    name="Campaign A",
    status=AdCampaignStatus.ACTIVE,
    start_date=None,
    end_date=None,
    impression_cap=None,
    click_cap=None,
):
    today = timezone.localdate()
    return AdCampaign.objects.create(
        advertiser=advertiser,
        name=name,
        zone=zone,
        status=status,
        creative_url="https://cdn.example.com/banner.jpg",
        click_url="https://advertiser.example.com",
        alt_text="Campaign banner",
        start_date=start_date or (today - timedelta(days=1)),
        end_date=end_date or (today + timedelta(days=7)),
        total_budget=Decimal("1000.00"),
        cost_per_impression=Decimal("0.0100"),
        cost_per_click=Decimal("2.50"),
        impression_cap=impression_cap,
        click_cap=click_cap,
    )


class AdvertisingModelTests(TestCase):

    def test_ctr_returns_zero_when_no_impressions(self):
        campaign = make_campaign(make_advertiser(), make_zone(), status=AdCampaignStatus.DRAFT)
        self.assertEqual(campaign.ctr, 0.0)

    def test_ctr_returns_percentage(self):
        campaign = make_campaign(make_advertiser(), make_zone())
        campaign.total_impressions = 100
        campaign.total_clicks      = 12
        self.assertEqual(campaign.ctr, 12.0)

    def test_hash_ip_returns_64_char_hex(self):
        h = AdImpression.hash_ip("192.168.1.10")
        self.assertEqual(len(h), 64)


class AdvertisingAPITests(APITestCase):

    def setUp(self):
        caches["default"].clear()
        caches["throttle"].clear()

        self.editor     = make_user("editor_user", role="editor")
        self.author     = make_user("author_user", role="author")
        self.zone       = make_zone(max_ads=5)
        self.advertiser = make_advertiser()
        self.campaign   = make_campaign(self.advertiser, self.zone, name="Running Campaign")

    def tearDown(self):
        caches["default"].clear()
        caches["throttle"].clear()

    def test_zone_returns_only_active_running_campaigns(self):
        today = timezone.localdate()
        make_campaign(
            self.advertiser,
            self.zone,
            name="Draft Campaign",
            status=AdCampaignStatus.DRAFT,
        )
        make_campaign(
            self.advertiser,
            self.zone,
            name="Expired Campaign",
            start_date=today - timedelta(days=10),
            end_date=today - timedelta(days=1),
        )
        make_campaign(
            self.advertiser,
            self.zone,
            name="Paused Campaign",
            status=AdCampaignStatus.PAUSED,
        )

        response = self.client.get(f"/api/v1/ads/zones/{self.zone.slug}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["campaigns"]), 1)
        self.assertEqual(str(response.data["campaigns"][0]["id"]), str(self.campaign.pk))

    def test_impression_recorded_and_deduplicated_per_ip_per_day(self):
        url = f"/api/v1/ads/{self.campaign.pk}/impression/"

        first = self.client.post(url, {"page_url": "/news/story-1/"}, format="json", REMOTE_ADDR="1.2.3.4")
        second = self.client.post(url, {"page_url": "/news/story-1/"}, format="json", REMOTE_ADDR="1.2.3.4")

        self.campaign.refresh_from_db()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(first.data["recorded"])
        self.assertFalse(second.data["recorded"])
        self.assertEqual(AdImpression.objects.filter(campaign=self.campaign).count(), 1)
        self.assertEqual(self.campaign.total_impressions, 1)

    def test_click_recorded_and_redirect_url_returned(self):
        url = f"/api/v1/ads/{self.campaign.pk}/click/"

        response = self.client.post(url, {"page_url": "/news/story-1/"}, format="json", REMOTE_ADDR="1.2.3.4")

        self.campaign.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["redirect_url"], self.campaign.click_url)
        self.assertEqual(AdClick.objects.filter(campaign=self.campaign).count(), 1)
        self.assertEqual(self.campaign.total_clicks, 1)

    def test_impression_cap_triggers_auto_pause(self):
        capped = make_campaign(
            self.advertiser,
            self.zone,
            name="Capped Campaign",
            impression_cap=1,
        )

        response = self.client.post(
            f"/api/v1/ads/{capped.pk}/impression/",
            {"page_url": "/news/capped/"},
            format="json",
            REMOTE_ADDR="5.6.7.8",
        )

        capped.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(capped.total_impressions, 1)
        self.assertEqual(capped.status, AdCampaignStatus.PAUSED)

    def test_staff_impressions_not_counted(self):
        self.client.force_authenticate(self.editor)

        response = self.client.post(
            f"/api/v1/ads/{self.campaign.pk}/impression/",
            {"page_url": "/news/staff-view/"},
            format="json",
            REMOTE_ADDR="9.9.9.9",
        )

        self.campaign.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["recorded"])
        self.assertEqual(self.campaign.total_impressions, 0)
        self.assertEqual(AdImpression.objects.filter(campaign=self.campaign).count(), 0)

    def test_campaign_management_requires_authentication(self):
        response = self.client.get("/api/v1/ads/campaigns/")
        self.assertEqual(response.status_code, 401)

    def test_campaign_management_requires_editor_or_above(self):
        self.client.force_authenticate(self.author)
        response = self.client.get("/api/v1/ads/campaigns/")
        self.assertEqual(response.status_code, 403)

    def test_campaign_management_allows_editor(self):
        self.client.force_authenticate(self.editor)
        response = self.client.get("/api/v1/ads/campaigns/")
        self.assertEqual(response.status_code, 200)
