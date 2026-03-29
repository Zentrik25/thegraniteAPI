# Advertising API Frontend Guide

This document is for the Next.js frontend developer integrating the `advertising` app from the Granite API backend.

It covers:
- public ad-serving endpoints for the news site
- staff-only campaign management endpoints
- expected request and response shapes
- recommended Next.js integration patterns
- important behavior notes like caching, deduplication, and click tracking


## 1. Base URL

For local development:

```text
http://127.0.0.1:8000
```

All advertising endpoints are mounted under:

```text
/api/v1/ads/
```

Examples:

```text
GET  http://127.0.0.1:8000/api/v1/ads/zones/
POST http://127.0.0.1:8000/api/v1/ads/<campaign-id>/impression/
POST http://127.0.0.1:8000/api/v1/ads/<campaign-id>/click/
```


## 2. Auth Rules

### Public endpoints

These do **not** require authentication:

- `GET /api/v1/ads/zones/`
- `GET /api/v1/ads/zones/<slug>/`
- `POST /api/v1/ads/<campaign-id>/impression/`
- `POST /api/v1/ads/<campaign-id>/click/`

### Staff endpoints

These require a **staff JWT** from:

```text
POST /api/v1/auth/token/
```

And the user must be **Editor or above**.

Use:

```http
Authorization: Bearer <staff_access_token>
```

Protected endpoints:

- `GET /api/v1/ads/campaigns/`
- `POST /api/v1/ads/campaigns/`
- `GET /api/v1/ads/campaigns/<id>/`
- `PATCH /api/v1/ads/campaigns/<id>/`
- `GET /api/v1/ads/advertisers/`
- `POST /api/v1/ads/advertisers/`
- `GET /api/v1/ads/report/<campaign-id>/`


## 3. Public Ad Serving Flow

The recommended frontend flow is:

1. Fetch zone data from `GET /api/v1/ads/zones/<slug>/`
2. Render the returned campaign creatives
3. When an ad becomes visible, call the returned `impression_tracking_url`
4. When an ad is clicked, call the returned `click_tracking_url`
5. Read `redirect_url` from the click response and then navigate the browser there

Important:
- The public zone response does **not** expose the raw `click_url`
- The frontend should use the click tracking endpoint first, then redirect
- Tracking URLs in the response are **relative paths**, not absolute URLs


## 4. Public Endpoint Reference

### 4.1 List all active zones

```http
GET /api/v1/ads/zones/
```

Response:

```json
[
  {
    "id": "4b8dcb86-7d4a-4a10-a269-9b45e5e48d1c",
    "name": "Homepage Leaderboard",
    "slug": "homepage-leaderboard",
    "zone_type": "leaderboard",
    "description": "Top ad slot on the homepage.",
    "width": 728,
    "height": 90,
    "max_ads": 1,
    "campaigns": [
      {
        "id": "a18bc0c0-9930-46d8-b4e5-f5cdbf24a785",
        "name": "Econet Launch Campaign",
        "advertiser_name": "Econet",
        "creative_url": "https://cdn.example.com/banner.jpg",
        "alt_text": "Econet campaign banner",
        "click_tracking_url": "/api/v1/ads/a18bc0c0-9930-46d8-b4e5-f5cdbf24a785/click/",
        "impression_tracking_url": "/api/v1/ads/a18bc0c0-9930-46d8-b4e5-f5cdbf24a785/impression/"
      }
    ]
  }
]
```

Notes:
- only **active zones** are returned
- only **currently running campaigns** are returned
- if a zone has more running campaigns than `max_ads`, the backend randomly selects which ones appear
- zone results are cached for **60 seconds**


### 4.2 Get one zone by slug

```http
GET /api/v1/ads/zones/<slug>/
```

Example:

```http
GET /api/v1/ads/zones/homepage-leaderboard/
```

Response shape is the same as the list endpoint, but for one zone only.


### 4.3 Record an impression

```http
POST /api/v1/ads/<campaign-id>/impression/
Content-Type: application/json
```

Request body:

```json
{
  "page_url": "/business/zimbabwe-budget-analysis"
}
```

Response:

```json
{
  "campaign_id": "a18bc0c0-9930-46d8-b4e5-f5cdbf24a785",
  "recorded": true,
  "total_impressions": 57,
  "status": "active"
}
```

Behavior notes:
- one impression is counted per **IP + campaign + day**
- if the same user triggers the same impression again that day, the API still returns `200`, but:

```json
{
  "recorded": false
}
```

- if the campaign reaches its `impression_cap`, the backend auto-pauses it
- if the request is made by an authenticated staff user, it is **not counted**


### 4.4 Record a click

```http
POST /api/v1/ads/<campaign-id>/click/
Content-Type: application/json
```

Request body:

```json
{
  "page_url": "/business/zimbabwe-budget-analysis"
}
```

Response:

```json
{
  "campaign_id": "a18bc0c0-9930-46d8-b4e5-f5cdbf24a785",
  "redirect_url": "https://advertiser.example.com",
  "total_clicks": 13,
  "status": "active"
}
```

Frontend behavior:

1. `POST` to the click endpoint
2. read `redirect_url`
3. redirect the browser to that URL

Example:

```ts
const res = await fetch(`${API_BASE}${campaign.click_tracking_url}`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ page_url: router.asPath }),
});

const data = await res.json();
window.location.href = data.redirect_url;
```

Behavior notes:
- clicks are always logged when the campaign is running
- if the campaign reaches its `click_cap`, the backend auto-pauses it


## 5. Staff Endpoint Reference

### 5.1 List campaigns

```http
GET /api/v1/ads/campaigns/
Authorization: Bearer <staff_token>
```

Paginated response:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "a18bc0c0-9930-46d8-b4e5-f5cdbf24a785",
      "advertiser": {
        "id": "13f22129-9ba1-46f5-b931-664f68fcb0bd",
        "company_name": "Econet",
        "contact_name": "Jane Dube",
        "contact_email": "sales@econet.example",
        "is_active": true
      },
      "name": "Econet Launch Campaign",
      "zone": {
        "id": "4b8dcb86-7d4a-4a10-a269-9b45e5e48d1c",
        "name": "Homepage Leaderboard",
        "slug": "homepage-leaderboard",
        "zone_type": "leaderboard",
        "width": 728,
        "height": 90,
        "is_active": true,
        "max_ads": 1
      },
      "status": "active",
      "creative_url": "https://cdn.example.com/banner.jpg",
      "click_url": "https://advertiser.example.com",
      "alt_text": "Econet campaign banner",
      "start_date": "2026-03-29",
      "end_date": "2026-04-15",
      "total_budget": "1000.00",
      "cost_per_impression": "0.0100",
      "cost_per_click": "2.50",
      "impression_cap": 10000,
      "click_cap": 500,
      "total_impressions": 57,
      "total_clicks": 13,
      "ctr": 22.81,
      "is_running": true,
      "created_at": "2026-03-29T12:00:00Z",
      "updated_at": "2026-03-29T12:30:00Z"
    }
  ]
}
```


### 5.2 Create a campaign

```http
POST /api/v1/ads/campaigns/
Authorization: Bearer <staff_token>
Content-Type: application/json
```

Request body:

```json
{
  "advertiser": "13f22129-9ba1-46f5-b931-664f68fcb0bd",
  "name": "Econet Launch Campaign",
  "zone": "4b8dcb86-7d4a-4a10-a269-9b45e5e48d1c",
  "status": "draft",
  "creative_url": "https://cdn.example.com/banner.jpg",
  "click_url": "https://advertiser.example.com",
  "alt_text": "Econet campaign banner",
  "start_date": "2026-03-29",
  "end_date": "2026-04-15",
  "total_budget": "1000.00",
  "cost_per_impression": "0.0100",
  "cost_per_click": "2.50",
  "impression_cap": 10000,
  "click_cap": 500
}
```

Important:
- create and patch use the **write serializer**
- that means the POST/PATCH response is the submitted write payload, not the full nested read payload
- after creating, call `GET /api/v1/ads/campaigns/<id>/` if the UI needs the nested campaign record


### 5.3 Campaign detail

```http
GET /api/v1/ads/campaigns/<id>/
Authorization: Bearer <staff_token>
```

This returns the full nested campaign payload shown in the list example.


### 5.4 Update a campaign

```http
PATCH /api/v1/ads/campaigns/<id>/
Authorization: Bearer <staff_token>
Content-Type: application/json
```

Example:

```json
{
  "status": "active",
  "impression_cap": 25000
}
```

Validation rules:
- `end_date` must be on or after `start_date`
- a campaign cannot be activated if the zone is inactive
- a campaign cannot be activated if the advertiser is inactive


### 5.5 List advertisers

```http
GET /api/v1/ads/advertisers/
Authorization: Bearer <staff_token>
```

Paginated response:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "13f22129-9ba1-46f5-b931-664f68fcb0bd",
      "company_name": "Econet",
      "contact_name": "Jane Dube",
      "contact_email": "sales@econet.example",
      "contact_phone": "+263771000000",
      "website_url": "https://econet.example",
      "is_active": true,
      "campaign_count": 3,
      "created_at": "2026-03-29T10:00:00Z",
      "updated_at": "2026-03-29T10:00:00Z"
    }
  ]
}
```


### 5.6 Create an advertiser

```http
POST /api/v1/ads/advertisers/
Authorization: Bearer <staff_token>
Content-Type: application/json
```

Request body:

```json
{
  "company_name": "Econet",
  "contact_name": "Jane Dube",
  "contact_email": "sales@econet.example",
  "contact_phone": "+263771000000",
  "website_url": "https://econet.example",
  "is_active": true
}
```


### 5.7 Campaign report

```http
GET /api/v1/ads/report/<campaign-id>/
Authorization: Bearer <staff_token>
```

Response:

```json
{
  "campaign": {
    "id": "a18bc0c0-9930-46d8-b4e5-f5cdbf24a785",
    "advertiser": {
      "id": "13f22129-9ba1-46f5-b931-664f68fcb0bd",
      "company_name": "Econet",
      "contact_name": "Jane Dube",
      "contact_email": "sales@econet.example",
      "is_active": true
    },
    "name": "Econet Launch Campaign",
    "zone": {
      "id": "4b8dcb86-7d4a-4a10-a269-9b45e5e48d1c",
      "name": "Homepage Leaderboard",
      "slug": "homepage-leaderboard",
      "zone_type": "leaderboard",
      "width": 728,
      "height": 90,
      "is_active": true,
      "max_ads": 1
    },
    "status": "active",
    "creative_url": "https://cdn.example.com/banner.jpg",
    "click_url": "https://advertiser.example.com",
    "alt_text": "Econet campaign banner",
    "start_date": "2026-03-29",
    "end_date": "2026-04-15",
    "total_budget": "1000.00",
    "cost_per_impression": "0.0100",
    "cost_per_click": "2.50",
    "impression_cap": 10000,
    "click_cap": 500,
    "total_impressions": 57,
    "total_clicks": 13,
    "ctr": 22.81,
    "is_running": true,
    "created_at": "2026-03-29T12:00:00Z",
    "updated_at": "2026-03-29T12:30:00Z"
  },
  "daily_impressions": [
    { "date": "2026-03-29", "count": 34 },
    { "date": "2026-03-30", "count": 23 }
  ],
  "daily_clicks": [
    { "date": "2026-03-29", "count": 8 },
    { "date": "2026-03-30", "count": 5 }
  ],
  "generated_at": "2026-03-30T10:15:00Z"
}
```


## 6. Suggested TypeScript Types

```ts
export type PublicAdCampaign = {
  id: string;
  name: string;
  advertiser_name: string;
  creative_url: string;
  alt_text: string;
  click_tracking_url: string;
  impression_tracking_url: string;
};

export type AdZone = {
  id: string;
  name: string;
  slug: string;
  zone_type: "leaderboard" | "sidebar" | "in_article" | "sticky_footer" | "hero" | "interstitial";
  description: string;
  width: number;
  height: number;
  max_ads: number;
  campaigns: PublicAdCampaign[];
};

export type ImpressionResponse = {
  campaign_id: string;
  recorded: boolean;
  total_impressions: number;
  status: string;
};

export type ClickResponse = {
  campaign_id: string;
  redirect_url: string;
  total_clicks: number;
  status: string;
};
```


## 7. Recommended Next.js Usage

### 7.1 Fetch zone data on the server

For pages like the homepage or article detail page, fetch zone data in a server component or route handler.

Example:

```ts
export async function getZoneAds(slug: string): Promise<AdZone | null> {
  const res = await fetch(`${process.env.API_BASE_URL}/api/v1/ads/zones/${slug}/`, {
    next: { revalidate: 60 },
  });

  if (!res.ok) return null;
  return res.json();
}
```

Why:
- the backend already caches zone payloads for 60 seconds
- matching that with Next.js `revalidate: 60` is a clean default


### 7.2 Fire impression tracking in a client component

Only fire the impression when the ad is actually visible, not just when the page HTML is rendered.

Use:
- `IntersectionObserver`
- one request per visible ad creative

Example:

```ts
await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}${campaign.impression_tracking_url}`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ page_url: window.location.pathname }),
});
```


### 7.3 Click handling

Do not use `<a href={externalUrl}>` directly for tracked ads.

Instead:

1. intercept click
2. `POST` to the click endpoint
3. read `redirect_url`
4. navigate

Example:

```ts
async function handleAdClick(campaign: PublicAdCampaign) {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_BASE_URL}${campaign.click_tracking_url}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page_url: window.location.pathname }),
    }
  );

  if (!res.ok) return;

  const data: ClickResponse = await res.json();
  window.location.href = data.redirect_url;
}
```


## 8. Rendering Strategy by Zone

Suggested mapping:

- `leaderboard`: full-width horizontal banner near top of page
- `sidebar`: 300x250 block in desktop side rail
- `in_article`: insert between paragraphs or after paragraph 3/5
- `sticky_footer`: mobile fixed bottom banner
- `hero`: homepage feature billboard
- `interstitial`: mobile takeover or between-page transition

Use `width` and `height` from the API to reserve layout space and reduce CLS.


## 9. Error Handling Notes

### Public zone endpoints

- `404` if zone slug does not exist or zone is inactive

### Impression and click endpoints

- `404` if the campaign is not currently running
- still handle `200` with `recorded: false` as a successful impression call

### Staff endpoints

- `401` if no token is sent
- `403` if the user is authenticated but below Editor


## 10. Frontend Gotchas

1. Staff testing impressions in the browser will not increase impression totals.

2. Zone responses are cached for 60 seconds, so campaign changes are not guaranteed to appear instantly.

3. Public zone responses return relative tracking URLs like:

```text
/api/v1/ads/<campaign-id>/click/
```

If the Next.js app is on another origin, prefix them with your API base URL.

4. If a campaign hits its impression or click cap, it auto-pauses. The next zone fetch may return fewer ads or no ads for that slot.

5. Create and patch endpoints for campaigns and advertisers return write payloads, not the full nested detail payload. If the UI needs the full object after saving, follow up with a GET request.


## 11. Recommended Frontend File Layout

Example structure:

```text
src/
  lib/
    advertising/
      api.ts
      types.ts
      track-impression.ts
      track-click.ts
  components/
    ads/
      ad-slot.tsx
      ad-banner.tsx
      ad-sidebar.tsx
      ad-sticky-footer.tsx
  app/
    (site)/
      page.tsx
      articles/[slug]/page.tsx
    (staff)/
      ads/campaigns/page.tsx
      ads/campaigns/[id]/page.tsx
      ads/advertisers/page.tsx
      ads/reports/[id]/page.tsx
```


## 12. Minimum Build Order

If the frontend developer wants the fastest path:

1. Build `lib/advertising/types.ts`
2. Build `lib/advertising/api.ts`
3. Build a reusable `<AdSlot zoneSlug="homepage-leaderboard" />`
4. Add impression tracking with `IntersectionObserver`
5. Add click tracking and redirect
6. Add staff campaign list page
7. Add campaign detail/report page
8. Add advertiser management page


## 13. Quick Checklist

- Fetch zone by slug
- Render returned creative(s)
- Record impression only when visible
- Track click before redirect
- Prefix relative tracking URLs with API base URL
- Use staff JWT for management pages
- Expect paginated responses on list endpoints
- Expect 60-second cache behavior on public zone results

