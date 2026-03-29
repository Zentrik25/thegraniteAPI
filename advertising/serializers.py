"""
serializers.py - DRF serializers for the advertising app.
"""

from rest_framework import serializers

from .models import AdCampaign, Advertiser, AdZone


class PublicAdCampaignSerializer(serializers.ModelSerializer):
    advertiser_name         = serializers.CharField(source="advertiser.company_name", read_only=True)
    click_tracking_url      = serializers.SerializerMethodField()
    impression_tracking_url = serializers.SerializerMethodField()

    class Meta:
        model  = AdCampaign
        fields = (
            "id",
            "name",
            "advertiser_name",
            "creative_url",
            "alt_text",
            "click_tracking_url",
            "impression_tracking_url",
        )

    def get_click_tracking_url(self, obj) -> str:
        return f"/api/v1/ads/{obj.pk}/click/"

    def get_impression_tracking_url(self, obj) -> str:
        return f"/api/v1/ads/{obj.pk}/impression/"


class AdZonePublicSerializer(serializers.ModelSerializer):
    campaigns = serializers.SerializerMethodField()

    class Meta:
        model  = AdZone
        fields = (
            "id",
            "name",
            "slug",
            "zone_type",
            "description",
            "width",
            "height",
            "max_ads",
            "campaigns",
        )

    def get_campaigns(self, obj):
        campaigns = getattr(obj, "current_campaigns", [])
        return PublicAdCampaignSerializer(campaigns, many=True).data


class AdZoneSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model  = AdZone
        fields = (
            "id",
            "name",
            "slug",
            "zone_type",
            "width",
            "height",
            "is_active",
            "max_ads",
        )


class AdvertiserSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model  = Advertiser
        fields = (
            "id",
            "company_name",
            "contact_name",
            "contact_email",
            "is_active",
        )


class AdvertiserSerializer(serializers.ModelSerializer):
    campaign_count = serializers.SerializerMethodField()

    class Meta:
        model  = Advertiser
        fields = (
            "id",
            "company_name",
            "contact_name",
            "contact_email",
            "contact_phone",
            "website_url",
            "is_active",
            "campaign_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("campaign_count", "created_at", "updated_at")

    def get_campaign_count(self, obj) -> int:
        return getattr(obj, "_campaign_count", obj.campaigns.count())


class AdvertiserWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Advertiser
        fields = (
            "company_name",
            "contact_name",
            "contact_email",
            "contact_phone",
            "website_url",
            "is_active",
        )


class AdCampaignSerializer(serializers.ModelSerializer):
    advertiser = AdvertiserSummarySerializer(read_only=True)
    zone       = AdZoneSummarySerializer(read_only=True)
    ctr        = serializers.ReadOnlyField()
    is_running = serializers.ReadOnlyField()

    class Meta:
        model  = AdCampaign
        fields = (
            "id",
            "advertiser",
            "name",
            "zone",
            "status",
            "creative_url",
            "click_url",
            "alt_text",
            "start_date",
            "end_date",
            "total_budget",
            "cost_per_impression",
            "cost_per_click",
            "impression_cap",
            "click_cap",
            "total_impressions",
            "total_clicks",
            "ctr",
            "is_running",
            "created_at",
            "updated_at",
        )


class AdCampaignWriteSerializer(serializers.ModelSerializer):
    advertiser = serializers.PrimaryKeyRelatedField(queryset=Advertiser.objects.all())
    zone       = serializers.PrimaryKeyRelatedField(queryset=AdZone.objects.all())

    class Meta:
        model  = AdCampaign
        fields = (
            "advertiser",
            "name",
            "zone",
            "status",
            "creative_url",
            "click_url",
            "alt_text",
            "start_date",
            "end_date",
            "total_budget",
            "cost_per_impression",
            "cost_per_click",
            "impression_cap",
            "click_cap",
        )

    def validate(self, attrs):
        instance   = getattr(self, "instance", None)
        start_date = attrs.get("start_date", getattr(instance, "start_date", None))
        end_date   = attrs.get("end_date", getattr(instance, "end_date", None))
        status     = attrs.get("status", getattr(instance, "status", None))
        zone       = attrs.get("zone", getattr(instance, "zone", None))
        advertiser = attrs.get("advertiser", getattr(instance, "advertiser", None))

        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError(
                {"end_date": "end_date must be on or after start_date."}
            )

        if status == "active" and zone and not zone.is_active:
            raise serializers.ValidationError(
                {"zone": "Campaigns cannot be activated in an inactive zone."}
            )

        if status == "active" and advertiser and not advertiser.is_active:
            raise serializers.ValidationError(
                {"advertiser": "Campaigns cannot be activated for an inactive advertiser."}
            )

        return attrs


class AdImpressionResultSerializer(serializers.Serializer):
    campaign_id       = serializers.UUIDField()
    recorded          = serializers.BooleanField()
    total_impressions = serializers.IntegerField()
    status            = serializers.CharField()


class AdClickResultSerializer(serializers.Serializer):
    campaign_id  = serializers.UUIDField()
    redirect_url = serializers.URLField()
    total_clicks = serializers.IntegerField()
    status       = serializers.CharField()


class DailyAdMetricSerializer(serializers.Serializer):
    date  = serializers.DateField()
    count = serializers.IntegerField()


class AdCampaignReportSerializer(serializers.Serializer):
    campaign          = AdCampaignSerializer()
    daily_impressions = DailyAdMetricSerializer(many=True)
    daily_clicks      = DailyAdMetricSerializer(many=True)
    generated_at      = serializers.DateTimeField()
