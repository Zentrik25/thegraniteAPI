# Next.js Frontend Integration Guide

This document is the frontend-facing handbook for building the The Granite Post web app against this Django REST API.

It is written for a Next.js App Router frontend and covers:

- base URLs and environment variables
- API conventions shared across apps
- staff auth vs reader auth
- page-to-endpoint mapping
- public site flows
- reader account and subscription flows
- staff dashboard and CMS flows
- advertising and push notification integration
- recommended Next.js structure and implementation order


## 1. Project Context

The backend is a Django 6 + DRF newsroom CMS for The Granite Post.

- Local backend URL: `http://127.0.0.1:8000`
- Local frontend URL: `http://localhost:3000`
- Public API prefix: `/api/v1/`
- OpenAPI schema: `/api/schema/`
- Swagger docs: `/api/docs/`
- Health check: `/health/`

The backend serves both:

- the public news site
- authenticated reader features
- authenticated staff CMS features


## 2. Frontend Environment Variables

Recommended frontend env vars:

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_SITE_URL=http://localhost:3000
```

Recommended usage:

- `API_BASE_URL` for server-side fetches
- `NEXT_PUBLIC_API_BASE_URL` for browser-side tracking or auth calls
- `NEXT_PUBLIC_SITE_URL` for absolute frontend links when needed

If the frontend runs on a different origin, make sure the backend has that origin in `CORS_ALLOWED_ORIGINS`.


## 3. Non-Negotiable Frontend Rules

1. Treat staff auth and reader auth as two separate systems.
2. Public pages must never assume draft or review content is available.
3. Use server-side data fetching for public GET endpoints wherever possible.
4. Use client-side requests only for interactive behavior like comments, tracking, login, logout, bookmarks, notifications, and payment polling.
5. Prefer secure `httpOnly` cookies managed by Next.js route handlers or server actions instead of storing JWTs in `localStorage`.


## 4. API Conventions

### 4.1 Pagination

Most list endpoints that use shared pagination return this envelope:

```json
{
  "status": "ok",
  "count": 120,
  "total_pages": 6,
  "current_page": 1,
  "page_size": 20,
  "next": "http://127.0.0.1:8000/api/v1/articles/?page=2",
  "previous": null,
  "results": []
}
```

Default page size is `20`.

Common query params:

- `page`
- `page_size`


### 4.2 Error Shape

Most DRF errors are normalized by the shared exception handler into this shape:

```json
{
  "status": "error",
  "code": "validation_error",
  "message": "Validation failed. Please correct the errors below.",
  "errors": {
    "email": "This field is required."
  }
}
```

Possible `code` values you should handle in the UI include:

- `authentication_required`
- `authentication_failed`
- `permission_denied`
- `not_found`
- `rate_limit_exceeded`
- `validation_error`
- `internal_server_error`

Some throttled responses may also include:

```json
{
  "retry_after_seconds": 30
}
```


### 4.3 Date and Time

API dates are usually ISO strings:

- `DateField`: `2026-03-29`
- `DateTimeField`: `2026-03-29T14:47:59Z`

Display in the frontend using the site locale and timezone rules you want, but preserve the raw values from the API.


### 4.4 Authorization Header

When sending JWTs directly to the backend:

```http
Authorization: Bearer <token>
```


## 5. Auth Model

There are two auth systems in this backend.

### 5.1 Staff JWT

Use for newsroom/CMS/admin UI.

Endpoints:

- `POST /api/v1/auth/token/`
- `POST /api/v1/auth/token/refresh/`
- `POST /api/v1/auth/token/blacklist/`
- `GET /api/v1/auth/me/`
- `POST /api/v1/auth/change-password/`

Login request:

```json
{
  "username": "thegranite",
  "password": "Strive@3934#"
}
```

Login response shape:

```json
{
  "refresh": "<jwt>",
  "access": "<jwt>",
  "user": {
    "id": 1,
    "username": "thegranite",
    "display_name": "The Granite",
    "slug": "thegranite",
    "role": "admin",
    "role_display": "Admin",
    "avatar_url": "",
    "title": "",
    "can_publish": true,
    "can_edit_any_article": true,
    "can_manage_staff": true,
    "is_editorial_admin": true
  }
}
```

Staff roles:

- `contributor`
- `author`
- `moderator`
- `editor`
- `senior_editor`
- `admin`


### 5.2 Reader JWT

Use for the consumer-facing account area.

Endpoints:

- `POST /api/v1/accounts/register/`
- `GET /api/v1/accounts/verify-email/?token=...`
- `POST /api/v1/accounts/login/`
- `POST /api/v1/accounts/logout/`
- `POST /api/v1/accounts/token/refresh/`
- `GET /api/v1/accounts/me/`
- `PATCH /api/v1/accounts/me/`
- `POST /api/v1/accounts/change-password/`
- `POST /api/v1/accounts/forgot-password/`
- `POST /api/v1/accounts/reset-password/`

Reader login request:

```json
{
  "email": "reader@example.com",
  "password": "StrongPass123!"
}
```

Reader login response shape:

```json
{
  "refresh": "<jwt>",
  "access": "<jwt>",
  "reader": {
    "id": "uuid",
    "email": "reader@example.com",
    "username": "reader1",
    "display_name": "Reader One",
    "public_name": "Reader One",
    "avatar_url": "",
    "bio": "",
    "is_email_verified": true,
    "date_joined": "2026-03-29T12:00:00Z",
    "last_login": "2026-03-29T12:30:00Z",
    "bookmark_count": 0
  }
}
```


### 5.3 Important Auth Warning

Staff and reader tokens are not interchangeable.

- Staff token != reader token
- `/api/v1/auth/*` is for staff
- `/api/v1/accounts/*` is for readers

Keep them in separate cookie namespaces if the frontend supports both.


## 6. Suggested Next.js Architecture

Recommended route groups:

```text
src/
  app/
    (site)/
      page.tsx
      articles/[slug]/page.tsx
      categories/[slug]/page.tsx
      tags/[slug]/page.tsx
      sections/[slug]/page.tsx
      authors/page.tsx
      authors/[slug]/page.tsx
      search/page.tsx
      subscribe/page.tsx
    (reader)/
      login/page.tsx
      register/page.tsx
      verify-email/page.tsx
      account/page.tsx
      account/bookmarks/page.tsx
      account/history/page.tsx
      account/subscription/page.tsx
    (staff)/
      cms/login/page.tsx
      cms/page.tsx
      cms/articles/page.tsx
      cms/articles/[slug]/page.tsx
      cms/media/page.tsx
      cms/comments/page.tsx
      cms/newsletter/page.tsx
      cms/ads/page.tsx
      cms/subscriptions/page.tsx
  lib/
    api/
      public.ts
      reader.ts
      staff.ts
      types.ts
    auth/
      reader-session.ts
      staff-session.ts
    advertising/
      api.ts
      track-click.ts
      track-impression.ts
```

Recommended separation:

- `public.ts` for unauthenticated GETs
- `reader.ts` for account/subscription calls
- `staff.ts` for CMS/editorial calls
- separate cookie/session helpers for reader and staff auth


## 7. Public Site: Page-to-Endpoint Map

### 7.1 Homepage

Recommended homepage data sources:

- `GET /api/v1/sections/?primary=true`
- `GET /api/v1/articles/breaking/`
- `GET /api/v1/articles/top-stories/`
- `GET /api/v1/articles/featured/`
- `GET /api/v1/articles/`
- `GET /api/v1/ads/zones/homepage-leaderboard/`
- `GET /api/v1/ads/zones/homepage-hero/` if configured

Rendering guidance:

- render most homepage data in server components
- render ads in a component that can trigger client-side impression tracking
- render newsletter signup as a client form


### 7.2 Article Detail Page

Route example:

```text
/articles/[slug]
```

Required backend calls:

- `GET /api/v1/articles/<slug>/`
- `GET /api/v1/articles/<slug>/comments/`
- `POST /api/v1/analytics/articles/<slug>/view/`
- `GET /api/v1/ads/zones/in-article/` if used
- `POST /api/v1/ads/<campaign-id>/impression/`
- `POST /api/v1/ads/<campaign-id>/click/`

Frontend split:

- fetch article data on the server
- record article view in a client effect
- lazy-load or client-fetch comments if you want faster first paint
- fire ad impressions only when the creative is actually visible


### 7.3 Category Pages

Route example:

```text
/categories/[slug]
```

Backend calls:

- `GET /api/v1/categories/`
- `GET /api/v1/categories/<slug>/`

Category detail response shape:

```json
{
  "category": {
    "id": 1,
    "name": "Politics",
    "slug": "politics",
    "description": "",
    "og_image_url": ""
  },
  "articles": []
}
```

Note: category detail is currently not paginated. The frontend should handle full-array responses.


### 7.4 Tag Pages

Route example:

```text
/tags/[slug]
```

Backend calls:

- `GET /api/v1/tags/`
- `GET /api/v1/tags/<slug>/`

Tag detail response shape:

```json
{
  "tag": {
    "id": 1,
    "name": "elections",
    "slug": "elections"
  },
  "articles": []
}
```


### 7.5 Section Pages

Use sections for top-level site navigation.

Backend calls:

- `GET /api/v1/sections/?primary=true`
- `GET /api/v1/sections/?primary=false`
- `GET /api/v1/sections/<slug>/`
- `GET /api/v1/sections/<slug>/articles/`

Section detail returns:

- section metadata
- `hero_article`
- section categories
- latest 20 articles

`/api/v1/sections/<slug>/articles/` is paginated and supports:

- `?category=<category-slug>`


### 7.6 Author Pages

Frontend route example:

```text
/authors
/authors/[slug]
```

API calls:

- `GET /api/v1/users/`
- `GET /api/v1/users/<slug>/`

Important:

- the frontend route can be `/authors/*`
- the API route is `/users/*`

Author detail response shape:

```json
{
  "user": {
    "id": 1,
    "byline": "Jane Dube",
    "slug": "jane-dube",
    "title": "Senior Reporter",
    "bio": "",
    "avatar_url": "",
    "beat": "Politics",
    "twitter_handle": "",
    "linkedin_url": "",
    "email_public": "",
    "article_count": 12
  },
  "articles": []
}
```

Note: author detail is also not paginated right now.


### 7.7 Search Page

Frontend route example:

```text
/search?q=zimbabwe
```

API call:

- `GET /api/v1/search/?q=<query>&page=1&page_size=20`

Search response shape:

```json
{
  "status": "ok",
  "query": "zimbabwe",
  "count": 18,
  "total_pages": 1,
  "current_page": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "rank": 0.8432,
      "headline": "The latest <mark>Zimbabwe</mark> update...",
      "article": {}
    }
  ]
}
```

Search rules:

- minimum query length: 2
- maximum query length: 200
- `page_size` max: 50

Frontend note:

- `headline` contains `<mark>` tags from the backend for highlighting
- render as trusted backend HTML or strip tags before display


## 8. Public Content Types

These are the core public article payloads.

```ts
export type Category = {
  id: number;
  name: string;
  slug: string;
  description: string;
  og_image_url: string;
};

export type Tag = {
  id: number;
  name: string;
  slug: string;
};

export type ArticleListItem = {
  id: number;
  title: string;
  slug: string;
  excerpt: string;
  status: string;
  author_name: string;
  category: Category | null;
  tags: Tag[];
  is_breaking: boolean;
  top_story_rank: number | null;
  is_top_story: boolean;
  is_featured: boolean;
  featured_rank: number | null;
  is_live: boolean;
  needs_banner: boolean;
  image_url: string;
  image_alt: string;
  published_at: string | null;
  created_at: string;
  view_count: number;
};

export type ArticleDetail = ArticleListItem & {
  body: string;
  image_caption: string;
  image_credit: string;
  og_title: string;
  og_description: string;
  og_image_url: string;
  canonical_url: string;
  seo_title: string;
  seo_description: string;
  resolved_og_image: string;
  updated_at: string;
};

export type TopStorySlot = {
  rank: number;
  article: ArticleListItem | null;
};
```


## 9. Comments, Newsletter, Analytics, Ads, Notifications

### 9.1 Comments

Endpoints:

- `GET /api/v1/articles/<slug>/comments/`
- `POST /api/v1/articles/<slug>/comments/`

Read response:

```json
{
  "count": 2,
  "results": [
    {
      "id": 1,
      "author_name": "Reader",
      "body": "Great story",
      "created_at": "2026-03-29T10:00:00Z",
      "is_reply": false,
      "parent": null,
      "replies": []
    }
  ]
}
```

Create request:

```json
{
  "author_name": "Reader",
  "author_email": "reader@example.com",
  "body": "Great story",
  "parent": null
}
```

Create response:

```json
{
  "detail": "Your comment has been submitted and is awaiting moderation.",
  "id": 12
}
```

Important:

- public only sees approved comments
- new comments are submitted as pending
- replies are only one level deep
- POST is rate-limited


### 9.2 Newsletter

Endpoints:

- `POST /api/v1/newsletter/subscribe/`
- `GET /api/v1/newsletter/confirm/?token=...`
- `POST /api/v1/newsletter/unsubscribe/`

Subscribe request:

```json
{
  "email": "reader@example.com",
  "source": "footer"
}
```

Subscribe response:

```json
{
  "detail": "Thank you for subscribing. Please check your email for a confirmation link."
}
```

Recommended use:

- footer form
- article inline CTA
- exit-intent or homepage modal if desired


### 9.3 Article View Analytics

Endpoint:

- `POST /api/v1/analytics/articles/<slug>/view/`

Response:

```json
{
  "article_slug": "granite-story",
  "view_count": 124,
  "recorded": true
}
```

Behavior:

- one count per IP per article per day
- staff views are not counted
- fire this in a client effect once per page view


### 9.4 Advertising

Use these endpoints for ad rendering and tracking:

- `GET /api/v1/ads/zones/`
- `GET /api/v1/ads/zones/<slug>/`
- `POST /api/v1/ads/<campaign-id>/impression/`
- `POST /api/v1/ads/<campaign-id>/click/`

Important ad behavior:

- zone results are cached for 60 seconds
- only currently running campaigns are returned
- click tracking returns the redirect URL
- staff impressions are not counted

Read the deeper ad-specific guide here:

- `docs/ADVERTISING_FRONTEND_GUIDE.md`


### 9.5 Push Notifications

Endpoints:

- `GET /api/v1/notifications/vapid-public-key/`
- `POST /api/v1/notifications/subscribe/`
- `POST /api/v1/notifications/unsubscribe/`

The browser flow is:

1. Request notification permission
2. Fetch VAPID public key from backend
3. Call `pushManager.subscribe()`
4. POST the resulting `endpoint`, `p256dh`, `auth`, and `user_agent` to the backend

Subscribe request:

```json
{
  "endpoint": "https://push.example/...",
  "p256dh": "base64-key",
  "auth": "base64-auth",
  "user_agent": "Mozilla/5.0 ..."
}
```

If the server is not configured for push, `GET /notifications/vapid-public-key/` returns `503`.


## 10. Reader Area

### 10.1 Registration and Verification

Endpoints:

- `POST /api/v1/accounts/register/`
- `GET /api/v1/accounts/verify-email/?token=...`

Register request:

```json
{
  "email": "reader@example.com",
  "username": "reader1",
  "password": "StrongPass123!",
  "display_name": "Reader One"
}
```

Registration returns the reader profile, but login is blocked until email verification succeeds.


### 10.2 Profile

Endpoints:

- `GET /api/v1/accounts/me/`
- `PATCH /api/v1/accounts/me/`

Patchable fields:

- `display_name`
- `avatar_url`
- `bio`


### 10.3 Bookmarks

Endpoints:

- `GET /api/v1/accounts/bookmarks/`
- `POST /api/v1/accounts/bookmarks/`
- `DELETE /api/v1/accounts/bookmarks/<article-slug>/`

Create bookmark request:

```json
{
  "article_slug": "granite-story"
}
```

Duplicate bookmark response:

- HTTP `409`
- `{"detail": "You have already bookmarked this article."}`


### 10.4 Reading History

Endpoints:

- `GET /api/v1/accounts/history/`
- `POST /api/v1/accounts/history/`
- `DELETE /api/v1/accounts/history/`

Record history request:

```json
{
  "article_slug": "granite-story"
}
```


## 11. Subscriptions and Paywall

The active subscription API lives under `/api/v1/subscriptions/`.

Ignore the separate `subscription` app in the repo. Its URL config is empty.

### 11.1 Public Plans

Endpoint:

- `GET /api/v1/subscriptions/plans/`

Plan fields:

- `id`
- `name`
- `slug`
- `description`
- `price_usd`
- `billing_period`
- `billing_period_label`
- `features`
- `article_access`
- `article_access_label`

Useful enum values:

- billing periods: `monthly`, `annual`
- article access: `free_only`, `premium`, `all`


### 11.2 Reader Subscription Status

Endpoint:

- `GET /api/v1/subscriptions/my-subscription/`

Returns the latest subscription or `404` if none exists.


### 11.3 Start Subscription

Endpoint:

- `POST /api/v1/subscriptions/subscribe/`

Request:

```json
{
  "plan_slug": "premium",
  "payment_method": "ecocash",
  "phone_number": "+263771234567"
}
```

Payment methods:

- `ecocash`
- `onemoney`
- `bank_card`
- `bank_transfer`

Behavior:

- free plan activates immediately
- paid plan creates a subscription in `trialing`
- response includes subscription data plus `redirect_url` and `poll_url`

Frontend flow for paid plans:

1. POST subscribe
2. redirect reader to `redirect_url` if present
3. poll `GET /api/v1/subscriptions/paynow-poll/<payment-id>/`
4. update paywall state once `paid: true`


### 11.4 Cancel Subscription

Endpoint:

- `POST /api/v1/subscriptions/cancel/`

Request:

```json
{
  "cancel_immediately": false
}
```


### 11.5 Payment History

Endpoint:

- `GET /api/v1/subscriptions/payments/`

Paginated response with fields like:

- `id`
- `amount_usd`
- `currency`
- `payment_method`
- `payment_method_label`
- `status`
- `status_label`
- `paynow_reference`
- `created_at`
- `updated_at`


## 12. Staff Dashboard and CMS

### 12.1 Staff Session Bootstrap

At login:

1. `POST /api/v1/auth/token/`
2. store `access` and `refresh`
3. store the returned `user`
4. optionally refresh session data with `GET /api/v1/auth/me/`


### 12.2 Articles

Endpoints:

- `GET /api/v1/articles/`
- `POST /api/v1/articles/`
- `GET /api/v1/articles/<slug>/`
- `PATCH /api/v1/articles/<slug>/`
- `DELETE /api/v1/articles/<slug>/`

Important editorial behavior:

- public only sees published content
- staff sees all statuses
- delete archives the article instead of hard-deleting it

Write payload fields:

- `title`
- `excerpt`
- `body`
- `status`
- `category`
- `tags`
- `is_breaking`
- `top_story_rank`
- `featured_rank`
- `image_url`
- `image_alt`
- `image_caption`
- `image_credit`
- `og_title`
- `og_description`
- `og_image_url`
- `canonical_url`

Article statuses:

- `draft`
- `review`
- `published`
- `archived`


### 12.3 Categories and Tags

Read endpoints:

- `GET /api/v1/categories/`
- `GET /api/v1/categories/<slug>/`
- `GET /api/v1/tags/`
- `GET /api/v1/tags/<slug>/`

There is no create/update API for categories or tags in the current codebase. Those are currently managed through Django admin or shell tooling.


### 12.4 Media Library

Endpoints:

- `GET /api/v1/media/`
- `POST /api/v1/media/`
- `GET /api/v1/media/<id>/`
- `DELETE /api/v1/media/<id>/`

Upload format:

- `multipart/form-data`

Fields:

- `file`
- `alt_text`
- `caption`
- `credit`

Validation:

- JPEG, PNG, WebP only
- max 10MB
- min width 800px


### 12.5 Comments Moderation

Endpoints:

- `GET /api/v1/moderation/comments/?status=pending`
- `PATCH /api/v1/moderation/comments/<id>/`

Patch request:

```json
{
  "action": "approve"
}
```

Allowed actions:

- `approve`
- `reject`


### 12.6 Staff Management

Endpoints:

- `GET /api/v1/staff/`
- `POST /api/v1/staff/`
- `GET /api/v1/staff/<id>/`
- `PATCH /api/v1/staff/<id>/`
- `DELETE /api/v1/staff/<id>/`

Frontend use:

- staff directory
- invite/create staff account
- edit role/profile
- deactivate staff


### 12.7 Newsletter Dashboard

Endpoint:

- `GET /api/v1/newsletter/subscribers/?confirmed=all`

Filter options:

- `confirmed=true`
- `confirmed=false`
- `confirmed=all`


### 12.8 Advertising Dashboard

Staff ad endpoints:

- `GET /api/v1/ads/campaigns/`
- `POST /api/v1/ads/campaigns/`
- `GET /api/v1/ads/campaigns/<id>/`
- `PATCH /api/v1/ads/campaigns/<id>/`
- `GET /api/v1/ads/advertisers/`
- `POST /api/v1/ads/advertisers/`
- `GET /api/v1/ads/report/<campaign-id>/`

Use `docs/ADVERTISING_FRONTEND_GUIDE.md` for the deeper contract details.


### 12.9 Subscription Admin

Endpoints:

- `GET /api/v1/subscriptions/all/`
- `GET /api/v1/subscriptions/revenue/`

This is useful for a revenue dashboard or membership operations panel.


### 12.10 Notification Admin

Endpoints:

- `GET /api/v1/notifications/history/`
- `POST /api/v1/notifications/test/`

Use only in authenticated staff/admin views.


## 13. Shared TypeScript Utilities

Recommended shared types:

```ts
export type PaginatedResponse<T> = {
  status: string;
  count: number;
  total_pages: number;
  current_page: number;
  page_size: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export type ApiError = {
  status: "error";
  code: string;
  message: string;
  errors?: Record<string, string>;
  retry_after_seconds?: number;
  request_id?: string;
};
```

Recommended fetch wrappers:

- `getPublic<T>(path: string, init?: RequestInit)`
- `getReader<T>(path: string, accessToken: string, init?: RequestInit)`
- `getStaff<T>(path: string, accessToken: string, init?: RequestInit)`
- `postJson<T>(...)`
- `patchJson<T>(...)`


## 14. Recommended Rendering Strategy

Use server components for:

- homepage content
- article detail
- section/category/tag/author pages
- plan listing
- staff list/detail pages that are mostly data views

Use client components for:

- login/register/password forms
- comments submission
- bookmark buttons
- reading history writes
- analytics view tracking
- ad impression and click tracking
- Paynow payment polling
- notification permission and push subscription


## 15. Build Order

Recommended implementation order:

1. Set up shared API client, error handler, and TypeScript models.
2. Build the public site shell with sections-based navigation.
3. Build homepage using breaking, top stories, featured, and latest articles.
4. Build article detail pages with analytics and comments.
5. Build category, tag, section, author, and search pages.
6. Add newsletter signup.
7. Add ad slot rendering and tracking.
8. Build reader auth, profile, bookmarks, and history.
9. Build subscriptions and Paynow polling.
10. Build the staff CMS login and session handling.
11. Build article/media/comments/newsletter/ads dashboards.
12. Add push notifications if needed for launch.


## 16. Recommended First-Release Pages

If the frontend team wants the fastest path to a usable release, build these first:

- homepage
- article detail
- category pages
- search
- author profiles
- comments
- newsletter signup
- reader login/register
- bookmarks
- subscription plans and subscribe flow


## 17. Source of Truth

When in doubt, use these in this order:

1. `http://127.0.0.1:8000/api/docs/`
2. `http://127.0.0.1:8000/api/schema/`
3. `postman/TheGraniteAPI.postman_collection.json`
4. `docs/ADVERTISING_FRONTEND_GUIDE.md` for ad-specific integration
5. the serializer and view files in the backend repo

This guide is meant to accelerate frontend development, but the live schema and implemented views are the final contract.
