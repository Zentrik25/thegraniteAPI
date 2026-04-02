# Next.js Frontend Build Guide

This is the main build document for the The Granite Post frontend.

Use this guide if you are building the web app in Next.js against the completed Django REST API in this repository.

Companion docs:
- [ADVERTISING_FRONTEND_GUIDE.md](C:/dev/thegraniteAPI/docs/ADVERTISING_FRONTEND_GUIDE.md)


## 1. What This Frontend Needs To Do

The frontend has three jobs:

1. Public news site
2. Reader account and subscription area
3. Staff CMS and newsroom dashboard

The backend already supports all three. The frontend should keep them clearly separated in code, auth handling, and route structure.


## 2. Backend Summary

Local backend:

```text
http://127.0.0.1:8000
```

Important backend URLs:

```text
GET  /health/
GET  /api/v1/
GET  /api/schema/
GET  /api/docs/
```

Main API prefix:

```text
/api/v1/
```

The frontend will usually talk only to:

- `/api/v1/articles/`
- `/api/v1/categories/`
- `/api/v1/tags/`
- `/api/v1/sections/`
- `/api/v1/users/`
- `/api/v1/search/`
- `/api/v1/comments/` via article comment routes
- `/api/v1/newsletter/`
- `/api/v1/accounts/`
- `/api/v1/subscriptions/`
- `/api/v1/media/`
- `/api/v1/staff/`
- `/api/v1/ads/`
- `/api/v1/notifications/`
- `/api/v1/analytics/`


## 3. Recommended Frontend Stack

Recommended stack:

- Next.js 15+ with App Router
- TypeScript
- Server Components for public content pages
- Client Components for forms, tracking, auth actions, comments, bookmarks, and polling
- Route handlers or server actions for secure token handling
- `zod` or similar for response validation if you want runtime safety

Recommended packages:

```bash
npm install zod clsx date-fns
```

Optional but useful:

```bash
npm install react-hook-form @hookform/resolvers
```


## 4. Frontend Environment Variables

Create frontend env vars like this:

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_SITE_URL=http://localhost:3000
```

Use them like this:

- `API_BASE_URL` for server-side fetches
- `NEXT_PUBLIC_API_BASE_URL` for browser-side requests
- `NEXT_PUBLIC_SITE_URL` for absolute frontend links if needed

If your frontend runs on another origin, make sure the backend includes that origin in `CORS_ALLOWED_ORIGINS`.


## 5. Non-Negotiable Frontend Rules

1. Treat staff auth and reader auth as different systems.
2. Do not assume draft or review content is available on public routes.
3. Prefer server-side fetching for public read endpoints.
4. Use client-side requests for interactive features only.
5. Prefer secure cookies over `localStorage` for JWT storage.
6. Public pages must handle `402` paywall responses on premium content.
7. Preserve backend HTML fields like article `body` and search `headline` carefully.


## 6. Recommended App Structure

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
      reset-password/page.tsx
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
      cms/subscriptions/page.tsx
      cms/ads/page.tsx
      cms/staff/page.tsx
  lib/
    api/
      public.ts
      reader.ts
      staff.ts
      types.ts
    auth/
      reader-session.ts
      staff-session.ts
    subscriptions/
      subscribe.ts
      poll.ts
    advertising/
      api.ts
      track-click.ts
      track-impression.ts
```

Recommended separation:

- `public.ts` for public GET requests
- `reader.ts` for `/accounts/*` and `/subscriptions/*` reader routes
- `staff.ts` for `/auth/*`, `/staff/*`, article writes, media, moderation, and ad management


## 7. API Conventions

### 7.1 Pagination

Shared paginated endpoints usually return:

```json
{
  "count": 120,
  "next": "http://127.0.0.1:8000/api/v1/articles/?page=2",
  "previous": null,
  "results": []
}
```

Some endpoints also include extra fields like:

- `status`
- `total_pages`
- `current_page`
- `page_size`

Do not hardcode one exact pagination envelope for every endpoint. Normalize it in the frontend.

### 7.2 Common status codes

Handle these consistently:

- `200` success
- `201` created
- `202` accepted
- `400` validation or bad token/query
- `401` unauthenticated
- `402` premium/paywall required
- `403` authenticated but not allowed
- `404` not found
- `409` duplicate/conflict
- `429` throttled
- `502` upstream payment initiation problem

### 7.3 Dates

The API uses ISO strings.

Examples:

```text
2026-04-01
2026-04-01T08:30:00Z
```

### 7.4 Auth header

When sending a token directly:

```http
Authorization: Bearer <token>
```


## 8. Auth Model

There are two completely separate auth systems.

### 8.1 Staff auth

Use for the newsroom and CMS.

Endpoints:

- `POST /api/v1/auth/token/`
- `POST /api/v1/auth/token/refresh/`
- `POST /api/v1/auth/token/blacklist/`
- `GET /api/v1/auth/me/`
- `POST /api/v1/auth/change-password/`

Staff login payload:

```json
{
  "username": "thegranite",
  "password": "your-password"
}
```

Staff login response contains:

- `access`
- `refresh`
- `user`

### 8.2 Reader auth

Use for the public account area.

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

Reader login payload:

```json
{
  "email": "reader@example.com",
  "password": "StrongPass123!"
}
```

### 8.3 Important warning

- Staff token does not work on reader endpoints.
- Reader token does not work on staff endpoints.

Keep them in different cookie namespaces.


## 9. Public Site Pages

### 9.1 Homepage

Recommended API calls:

- `GET /api/v1/sections/?primary=true`
- `GET /api/v1/articles/breaking/`
- `GET /api/v1/articles/top-stories/`
- `GET /api/v1/articles/featured/`
- `GET /api/v1/articles/`
- `GET /api/v1/ads/zones/homepage-leaderboard/`

Build this page mostly as a server-rendered page.

### 9.2 Article detail

Route example:

```text
/articles/[slug]
```

API calls:

- `GET /api/v1/articles/<slug>/`
- `GET /api/v1/articles/<slug>/comments/`
- `POST /api/v1/analytics/articles/<slug>/view/`
- optional ad zone calls for in-article inventory

Important behavior:

- Premium articles may return `402` to non-subscribers.
- The frontend should catch `402` and show a subscription CTA instead of a generic error page.

### 9.3 Categories

Routes:

```text
/categories/[slug]
```

API calls:

- `GET /api/v1/categories/`
- `GET /api/v1/categories/<slug>/`

### 9.4 Tags

Routes:

```text
/tags/[slug]
```

API calls:

- `GET /api/v1/tags/`
- `GET /api/v1/tags/<slug>/`

### 9.5 Sections

Routes:

```text
/sections/[slug]
```

API calls:

- `GET /api/v1/sections/?primary=true`
- `GET /api/v1/sections/?primary=false`
- `GET /api/v1/sections/<slug>/`
- `GET /api/v1/sections/<slug>/articles/`

Use section detail for hero plus initial articles, then section articles for paginated loads or category tabs.

### 9.6 Authors

Frontend route examples:

```text
/authors
/authors/[slug]
```

API calls:

- `GET /api/v1/users/`
- `GET /api/v1/users/<slug>/`

### 9.7 Search

Route example:

```text
/search?q=zimbabwe
```

API call:

- `GET /api/v1/search/?q=<query>&page=1&page_size=20`

Current rules:

- minimum query length: `2`
- maximum query length: `200`
- `page_size` max: `50`
- endpoint is throttled, so avoid keystroke-by-keystroke live firing without debounce

Important:

- search `headline` may contain `<mark>` tags
- premium article results are searchable, but premium body text is not exposed in the snippet


## 10. Comments, Newsletter, Analytics, Push, Ads

### 10.1 Comments

API calls:

- `GET /api/v1/articles/<slug>/comments/`
- `POST /api/v1/articles/<slug>/comments/`

Notes:

- public only sees approved comments
- new comments are pending by default
- replies are one level deep

### 10.2 Newsletter

API calls:

- `POST /api/v1/newsletter/subscribe/`
- `GET /api/v1/newsletter/confirm/?token=...`
- `POST /api/v1/newsletter/unsubscribe/`

Recommended placements:

- footer form
- article inline CTA
- homepage block

### 10.3 Analytics

API calls:

- `POST /api/v1/analytics/articles/<slug>/view/`
- `GET /api/v1/analytics/trending/`
- `GET /api/v1/analytics/articles/<slug>/stats/` for staff dashboards if needed

### 10.4 Push notifications

API calls:

- `GET /api/v1/notifications/vapid-public-key/`
- `POST /api/v1/notifications/subscribe/`
- `POST /api/v1/notifications/unsubscribe/`

Browser flow:

1. ask for permission
2. fetch VAPID key
3. call `pushManager.subscribe()`
4. POST subscription payload to backend

### 10.5 Advertising

API calls:

- `GET /api/v1/ads/zones/`
- `GET /api/v1/ads/zones/<slug>/`
- `POST /api/v1/ads/<campaign-id>/impression/`
- `POST /api/v1/ads/<campaign-id>/click/`

Read the full ad contract here:

- [ADVERTISING_FRONTEND_GUIDE.md](C:/dev/thegraniteAPI/docs/ADVERTISING_FRONTEND_GUIDE.md)


## 11. Reader Features

### 11.1 Registration and login

Pages to build:

- `/register`
- `/login`
- `/verify-email`
- `/forgot-password`
- `/reset-password`

### 11.2 Profile

API calls:

- `GET /api/v1/accounts/me/`
- `PATCH /api/v1/accounts/me/`
- `POST /api/v1/accounts/change-password/`

### 11.3 Bookmarks

API calls:

- `GET /api/v1/accounts/bookmarks/`
- `POST /api/v1/accounts/bookmarks/`
- `DELETE /api/v1/accounts/bookmarks/<slug>/`

Duplicate bookmark behavior:

- returns `409`

### 11.4 Reading history

API calls:

- `GET /api/v1/accounts/history/`
- `POST /api/v1/accounts/history/`
- `DELETE /api/v1/accounts/history/`


## 12. Subscription and Paywall Flow

Main endpoints:

- `GET /api/v1/subscriptions/plans/`
- `GET /api/v1/subscriptions/my-subscription/`
- `POST /api/v1/subscriptions/subscribe/`
- `POST /api/v1/subscriptions/cancel/`
- `GET /api/v1/subscriptions/payments/`
- `GET /api/v1/subscriptions/paynow-poll/<payment-id>/`

### 12.1 Plan listing

Use `GET /api/v1/subscriptions/plans/` for the pricing page.

### 12.2 Starting a subscription

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
- paid plan creates a `trialing` subscription
- response includes subscription fields plus `redirect_url` and `poll_url`

### 12.3 Important implementation note for polling

The current subscribe response does **not** include the `payment_id` needed by:

```text
GET /api/v1/subscriptions/paynow-poll/<payment-id>/
```

So the safest frontend flow today is:

1. `POST /api/v1/subscriptions/subscribe/`
2. if `redirect_url` exists, send the reader there
3. immediately call `GET /api/v1/subscriptions/payments/`
4. pick the newest pending payment for the current reader
5. use that `payment.id` for polling `/subscriptions/paynow-poll/<payment-id>/`

Do not assume `subscription.id` is the same as `payment.id`. It is not.

### 12.4 Generic payment errors

The backend now returns stable generic payment messages.

Examples:

- `Unable to initiate payment right now. Please try again.`
- `Unable to verify payment status right now. Please refresh and try again.`

Do not build UI that depends on provider-specific error text.

### 12.5 Paywall behavior

Premium article requests may return `402` with upgrade information.

The frontend should:

- show a paywall panel
- link to subscription plans
- preserve the article URL so the user can return after subscribing


## 13. Staff CMS

### 13.1 Staff session bootstrap

At CMS login:

1. `POST /api/v1/auth/token/`
2. store `access` and `refresh`
3. store returned `user`
4. optionally refresh with `GET /api/v1/auth/me/`

### 13.2 CMS pages to build

Recommended pages:

- `/cms`
- `/cms/articles`
- `/cms/articles/[slug]`
- `/cms/media`
- `/cms/comments`
- `/cms/newsletter`
- `/cms/subscriptions`
- `/cms/ads`
- `/cms/staff`

### 13.3 Article management

API calls:

- `GET /api/v1/articles/`
- `POST /api/v1/articles/`
- `GET /api/v1/articles/<slug>/`
- `PATCH /api/v1/articles/<slug>/`
- `DELETE /api/v1/articles/<slug>/`

Notes:

- delete archives the article instead of hard deleting it
- categories and tags do not currently have create/update API endpoints
- media uploads produce URLs that are pasted into article image fields

### 13.4 Media library

API calls:

- `GET /api/v1/media/`
- `POST /api/v1/media/`
- `GET /api/v1/media/<id>/`
- `DELETE /api/v1/media/<id>/`

Upload as `multipart/form-data`.

### 13.5 Comment moderation

API calls:

- `GET /api/v1/moderation/comments/?status=pending`
- `PATCH /api/v1/moderation/comments/<id>/`

### 13.6 Staff management

API calls:

- `GET /api/v1/staff/`
- `POST /api/v1/staff/`
- `GET /api/v1/staff/<id>/`
- `PATCH /api/v1/staff/<id>/`
- `DELETE /api/v1/staff/<id>/`

### 13.7 Newsletter dashboard

API call:

- `GET /api/v1/newsletter/subscribers/?confirmed=all`

### 13.8 Subscription dashboard

API calls:

- `GET /api/v1/subscriptions/all/`
- `GET /api/v1/subscriptions/revenue/`

### 13.9 Advertising dashboard

API calls:

- `GET /api/v1/ads/campaigns/`
- `POST /api/v1/ads/campaigns/`
- `GET /api/v1/ads/campaigns/<id>/`
- `PATCH /api/v1/ads/campaigns/<id>/`
- `GET /api/v1/ads/advertisers/`
- `POST /api/v1/ads/advertisers/`
- `GET /api/v1/ads/report/<campaign-id>/`


## 14. Starter TypeScript Shapes

```ts
export type ApiError = {
  status?: string;
  code?: string;
  message?: string;
  detail?: string;
  errors?: Record<string, string | string[]>;
  retry_after_seconds?: number;
};

export type PaginatedResponse<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export type ArticleListItem = {
  id: number;
  title: string;
  slug: string;
  excerpt: string;
  image_url: string;
  image_alt: string;
  published_at: string | null;
  created_at: string;
  is_breaking: boolean;
  is_premium: boolean;
  is_featured: boolean;
  featured_rank: number | null;
  top_story_rank: number | null;
  category: {
    id: number;
    name: string;
    slug: string;
  } | null;
  tags: Array<{
    id: number;
    name: string;
    slug: string;
  }>;
};

export type StaffSession = {
  access: string;
  refresh: string;
  user: {
    id: number;
    username: string;
    display_name: string;
    slug: string;
    role: string;
    role_display: string;
    can_publish: boolean;
    can_edit_any_article: boolean;
    can_manage_staff: boolean;
    is_editorial_admin: boolean;
  };
};

export type ReaderSession = {
  access: string;
  refresh: string;
  reader: {
    id: string;
    email: string;
    username: string;
    display_name: string;
    public_name: string;
    avatar_url: string;
    bio: string;
    is_email_verified: boolean;
    date_joined: string;
    last_login: string | null;
    bookmark_count: number;
  };
};
```


## 15. Suggested Fetch Helpers

```ts
const API_BASE = process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL!;

export async function getPublic<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!res.ok) throw await res.json();
  return res.json();
}

export async function getWithBearer<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init?.headers ?? {}),
    },
  });

  if (!res.ok) throw await res.json();
  return res.json();
}
```


## 16. Recommended Rendering Strategy

Use server components for:

- homepage
- article detail page shell
- category, tag, section, author, and search result pages
- plans page
- staff dashboard list pages

Use client components for:

- login/register/change-password/reset forms
- comment submission
- bookmark and history writes
- article view analytics
- ad impression and click tracking
- Paynow polling
- push notification permission flow


## 17. Build Order

Recommended order:

1. Set up env vars, API helpers, and shared TypeScript types
2. Build the site shell and navigation from sections
3. Build homepage
4. Build article detail page
5. Build category, tag, section, author, and search pages
6. Add comments and newsletter subscription
7. Add reader auth and account pages
8. Add bookmarks and history
9. Add subscriptions and paywall handling
10. Add advertising slots and tracking
11. Build staff login and CMS shell
12. Build CMS article, media, comments, subscriptions, newsletter, ads, and staff pages


## 18. Launch Checklist

Before calling the frontend ready, verify:

- homepage loads with sections, breaking, top stories, and featured content
- article detail works for free and premium articles
- `402` premium responses show a paywall UI, not a generic crash page
- search works with debounce and pagination
- comments submit and approved comments render
- newsletter subscribe and confirm flows work
- reader register, verify, login, logout, bookmarks, and history work
- paid subscription flow works end to end with redirect plus polling
- staff login and core CMS pages work
- ads render and tracking calls succeed
- push notification setup degrades cleanly if unavailable


## 19. Source Of Truth

When building, use these in this order:

1. `http://127.0.0.1:8000/api/docs/`
2. `http://127.0.0.1:8000/api/schema/`
3. `postman/TheGraniteAPI.postman_collection.json`
4. this guide
5. the backend serializer and view files

If the schema and this document ever disagree, trust the live schema and the implemented view code.
