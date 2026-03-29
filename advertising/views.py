import logging
import random

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Count, F
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.middleware import _get_client_ip
from core.pagination import StandardResultsPagination
from users.permissions import IsEditorOrAbove

from .models import (
    AdCampaign,
    AdCampaignStatus,
    AdClick,
    AdImpression,
    Advertiser,
    AdZone,
    make_zone_cache_key,
)
from .serializers import (
    AdCampaignReportSerializer,
    AdCampaignSerializer,
    AdCampaignWriteSerializer,
    AdClickResultSerializer,
    AdImpressionResultSerializer,
    AdZonePublicSerializer,
    AdvertiserSerializer,
    AdvertiserWriteSerializer,
)

logger = logging.getLogger("advertising.views")

ZONE_CACHE_TTL = 60


def _running_campaigns_queryset():
    today = timezone.localdate()
    return (
        AdCampaign.objects
        .filter(
            status=AdCampaignStatus.ACTIVE,
            start_date__lte=today,
            end_date__gte=today,
            zone__is_active=True,
            advertiser__is_active=True,
        )
        .select_related("advertiser", "zone")
    )


def _select_campaigns_for_zone(zone: AdZone):
    running = list(
        _running_campaigns_queryset()
        .filter(zone=zone)
        .order_by("name")
    )

    if not running:
        return []

    if len(running) <= zone.max_ads:
        return running

    return random.sample(running, k=zone.max_ads)


def _get_zone_payload(zone: AdZone):
    cache_key = make_zone_cache_key(zone.slug)
    payload   = cache.get(cache_key)
    if payload is not None:
        return payload

    zone.current_campaigns = _select_campaigns_for_zone(zone)
    payload = AdZonePublicSerializer(zone).data
    cache.set(cache_key, payload, timeout=ZONE_CACHE_TTL)
    return payload


def _invalidate_zone_cache(zone_slug: str) -> None:
    cache.delete(make_zone_cache_key(zone_slug))


def _page_url_from_request(request) -> str:
    return str(
        request.data.get("page_url")
        or request.META.get("HTTP_REFERER")
        or "/"
    )[:500]


class AdZoneListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        zones = AdZone.objects.filter(is_active=True).order_by("name")
        data  = [_get_zone_payload(zone) for zone in zones]
        return Response(data)


class AdZoneDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, slug):
        zone = get_object_or_404(AdZone, slug=slug, is_active=True)
        return Response(_get_zone_payload(zone))


class AdImpressionCreateView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, campaign_id):
        campaign = get_object_or_404(
            _running_campaigns_queryset().select_related("zone"),
            pk=campaign_id,
        )

        if request.user.is_authenticated and request.user.is_staff:
            return Response(
                AdImpressionResultSerializer({
                    "campaign_id":       campaign.pk,
                    "recorded":          False,
                    "total_impressions": campaign.total_impressions,
                    "status":            campaign.status,
                }).data
            )

        ip_hash      = AdImpression.hash_ip(_get_client_ip(request))
        session_hash = AdImpression.hash_session(
            getattr(request.session, "session_key", None) or ""
        )
        page_url = _page_url_from_request(request)
        today    = timezone.localdate()
        recorded = False

        try:
            with transaction.atomic():
                AdImpression.objects.create(
                    campaign     = campaign,
                    ip_hash      = ip_hash,
                    session_hash = session_hash,
                    page_url     = page_url,
                    viewed_at    = timezone.now(),
                    viewed_date  = today,
                )
            recorded = True
        except IntegrityError:
            pass

        if recorded:
            AdCampaign.objects.filter(pk=campaign.pk).update(
                total_impressions=F("total_impressions") + 1
            )
            logger.debug("Ad impression recorded: campaign_id=%s", campaign.pk)

        campaign.refresh_from_db(fields=["total_impressions", "status"])

        if (
            recorded
            and campaign.impression_cap
            and campaign.total_impressions >= campaign.impression_cap
            and campaign.status == AdCampaignStatus.ACTIVE
        ):
            AdCampaign.objects.filter(pk=campaign.pk).update(
                status=AdCampaignStatus.PAUSED,
                updated_at=timezone.now(),
            )
            campaign.refresh_from_db(fields=["status"])
            _invalidate_zone_cache(campaign.zone.slug)
            logger.info("Campaign auto-paused on impression cap: campaign_id=%s", campaign.pk)

        return Response(
            AdImpressionResultSerializer({
                "campaign_id":       campaign.pk,
                "recorded":          recorded,
                "total_impressions": campaign.total_impressions,
                "status":            campaign.status,
            }).data
        )


class AdClickCreateView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, campaign_id):
        campaign = get_object_or_404(
            _running_campaigns_queryset().select_related("zone"),
            pk=campaign_id,
        )

        AdClick.objects.create(
            campaign   = campaign,
            ip_hash    = AdClick.hash_ip(_get_client_ip(request)),
            clicked_at = timezone.now(),
            page_url   = _page_url_from_request(request),
            referrer   = str(request.META.get("HTTP_REFERER", ""))[:500],
        )

        AdCampaign.objects.filter(pk=campaign.pk).update(
            total_clicks=F("total_clicks") + 1
        )
        campaign.refresh_from_db(fields=["total_clicks", "status", "click_url"])

        if (
            campaign.click_cap
            and campaign.total_clicks >= campaign.click_cap
            and campaign.status == AdCampaignStatus.ACTIVE
        ):
            AdCampaign.objects.filter(pk=campaign.pk).update(
                status=AdCampaignStatus.PAUSED,
                updated_at=timezone.now(),
            )
            campaign.refresh_from_db(fields=["status"])
            _invalidate_zone_cache(campaign.zone.slug)
            logger.info("Campaign auto-paused on click cap: campaign_id=%s", campaign.pk)

        logger.debug("Ad click recorded: campaign_id=%s", campaign.pk)

        return Response(
            AdClickResultSerializer({
                "campaign_id":  campaign.pk,
                "redirect_url": campaign.click_url,
                "total_clicks": campaign.total_clicks,
                "status":       campaign.status,
            }).data
        )


class AdCampaignListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsEditorOrAbove]
    pagination_class   = StandardResultsPagination
    http_method_names  = ["get", "post", "head", "options"]

    def get_queryset(self):
        return (
            AdCampaign.objects
            .select_related("advertiser", "zone")
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        return AdCampaignWriteSerializer if self.request.method == "POST" else AdCampaignSerializer

    def perform_create(self, serializer):
        campaign = serializer.save()
        logger.info("Ad campaign created: pk=%s name=%s", campaign.pk, campaign.name)


class AdCampaignDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, IsEditorOrAbove]
    queryset           = AdCampaign.objects.select_related("advertiser", "zone")
    http_method_names  = ["get", "patch", "head", "options"]

    def get_serializer_class(self):
        return AdCampaignWriteSerializer if self.request.method == "PATCH" else AdCampaignSerializer

    def perform_update(self, serializer):
        campaign = serializer.save()
        logger.info("Ad campaign updated: pk=%s name=%s", campaign.pk, campaign.name)


class AdvertiserListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsEditorOrAbove]
    pagination_class   = StandardResultsPagination
    http_method_names  = ["get", "post", "head", "options"]

    def get_queryset(self):
        return (
            Advertiser.objects
            .annotate(_campaign_count=Count("campaigns", distinct=True))
            .order_by("company_name")
        )

    def get_serializer_class(self):
        return AdvertiserWriteSerializer if self.request.method == "POST" else AdvertiserSerializer

    def perform_create(self, serializer):
        advertiser = serializer.save()
        logger.info("Advertiser created: pk=%s company=%s", advertiser.pk, advertiser.company_name)


class AdCampaignReportView(APIView):
    permission_classes = [IsAuthenticated, IsEditorOrAbove]

    def get(self, request, campaign_id):
        campaign = get_object_or_404(
            AdCampaign.objects.select_related("advertiser", "zone"),
            pk=campaign_id,
        )

        impression_rows = (
            AdImpression.objects
            .filter(campaign=campaign)
            .values("viewed_date")
            .annotate(count=Count("id"))
            .order_by("viewed_date")
        )
        click_rows = (
            AdClick.objects
            .filter(campaign=campaign)
            .annotate(day=TruncDate("clicked_at"))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )

        serializer = AdCampaignReportSerializer({
            "campaign": campaign,
            "daily_impressions": [
                {"date": row["viewed_date"], "count": row["count"]}
                for row in impression_rows
            ],
            "daily_clicks": [
                {"date": row["day"], "count": row["count"]}
                for row in click_rows
            ],
            "generated_at": timezone.now(),
        })
        return Response(serializer.data)
