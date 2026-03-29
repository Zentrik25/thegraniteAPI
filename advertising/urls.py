from django.urls import path

from .views import (
    AdCampaignDetailView,
    AdCampaignListCreateView,
    AdCampaignReportView,
    AdClickCreateView,
    AdImpressionCreateView,
    AdvertiserListCreateView,
    AdZoneDetailView,
    AdZoneListView,
)

app_name = "advertising"

urlpatterns = [
    path("ads/zones/",                  AdZoneListView.as_view(),            name="zone-list"),
    path("ads/zones/<slug:slug>/",      AdZoneDetailView.as_view(),          name="zone-detail"),
    path("ads/<uuid:campaign_id>/impression/", AdImpressionCreateView.as_view(), name="campaign-impression"),
    path("ads/<uuid:campaign_id>/click/",      AdClickCreateView.as_view(),      name="campaign-click"),
    path("ads/campaigns/",              AdCampaignListCreateView.as_view(),  name="campaign-list"),
    path("ads/campaigns/<uuid:pk>/",    AdCampaignDetailView.as_view(),      name="campaign-detail"),
    path("ads/advertisers/",            AdvertiserListCreateView.as_view(),  name="advertiser-list"),
    path("ads/report/<uuid:campaign_id>/", AdCampaignReportView.as_view(),   name="campaign-report"),
]
