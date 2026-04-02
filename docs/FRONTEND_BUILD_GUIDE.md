# The Granite Post — Next.js Frontend Build Guide

> **Status:** API backend is complete. This document is the implementation blueprint for the Next.js frontend.
>
> **Backend base URL (local):** `http://127.0.0.1:8000`
> **Frontend base URL (local):** `http://localhost:3000`
> **API prefix:** `/api/v1/`
> **Live Swagger docs:** `http://127.0.0.1:8000/api/docs/`

---

## Table of Contents

1. [Tech Stack](#1-tech-stack)
2. [Environment Setup](#2-environment-setup)
3. [Project Scaffold](#3-project-scaffold)
4. [Folder Structure](#4-folder-structure)
5. [API Client Layer](#5-api-client-layer)
6. [TypeScript Types](#6-typescript-types)
7. [Auth Architecture](#7-auth-architecture)
8. [Public Site Pages](#8-public-site-pages)
9. [Reader Account Area](#9-reader-account-area)
10. [Subscription & Paywall](#10-subscription--paywall)
11. [Staff CMS](#11-staff-cms)
12. [Shared Components](#12-shared-components)
13. [SEO & Meta](#13-seo--meta)
14. [Advertising Integration](#14-advertising-integration)
15. [Push Notifications](#15-push-notifications)
16. [Build Order](#16-build-order)
17. [Deployment Checklist](#17-deployment-checklist)

---

## 1. Tech Stack

| Layer | Choice |
|---|---|
| Framework | Next.js 15+ (App Router) |
| Language | TypeScript |
| Styling | Tailwind CSS v4 |
| Auth (server) | `httpOnly` cookies via Route Handlers |
| Forms | React Hook Form + Zod |
| Data fetching | Native fetch (server components) + SWR (client components) |
| Date formatting | `date-fns` |
| Notifications | Web Push API (browser-native) |
| Deployment | Vercel |

---

## 2. Environment Setup

Create `.env.local` at the project root:

```bash
# Backend API (server-side fetches — never exposed to browser)
API_BASE_URL=http://127.0.0.1:8000

# Frontend public URL
NEXT_PUBLIC_SITE_URL=http://localhost:3000

# Backend API (browser-side calls only: analytics, auth refresh, ad tracking)
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000

# Cookie secrets (generate with: openssl rand -hex 32)
READER_SESSION_SECRET=replace_this_with_32_byte_hex
STAFF_SESSION_SECRET=replace_this_with_32_byte_hex
```

Rules:
- Use `API_BASE_URL` (no `NEXT_PUBLIC_`) for all server component fetches.
- Use `NEXT_PUBLIC_API_BASE_URL` only for browser-side calls (analytics, comments, auth).
- Never expose `READER_SESSION_SECRET` or `STAFF_SESSION_SECRET` to the browser.

---

## 3. Project Scaffold

```bash
npx create-next-app@latest granite-post \
  --typescript \
  --tailwind \
  --app \
  --src-dir \
  --import-alias "@/*"

cd granite-post
npm install swr react-hook-form zod @hookform/resolvers date-fns
```

---

## 4. Folder Structure

```
src/
  app/
    (site)/                        # Public-facing news site
      layout.tsx                   # Site shell: header, nav, footer
      page.tsx                     # Homepage
      articles/
        [slug]/
          page.tsx                 # Article detail
      categories/
        [slug]/
          page.tsx
      tags/
        [slug]/
          page.tsx
      sections/
        [slug]/
          page.tsx
      authors/
        page.tsx
        [slug]/
          page.tsx
      search/
        page.tsx
      subscribe/
        page.tsx                   # Subscription plans
    (reader)/                      # Reader account area
      layout.tsx
      login/
        page.tsx
      register/
        page.tsx
      verify-email/
        page.tsx
      account/
        page.tsx                   # Profile
        bookmarks/
          page.tsx
        history/
          page.tsx
        subscription/
          page.tsx
    (staff)/                       # Staff CMS
      layout.tsx                   # CMS shell: sidebar, top bar
      cms/
        login/
          page.tsx
        page.tsx                   # Dashboard
        articles/
          page.tsx                 # Article list
          new/
            page.tsx
          [slug]/
            page.tsx               # Edit article
        media/
          page.tsx
        comments/
          page.tsx
        newsletter/
          page.tsx
        ads/
          page.tsx
        subscriptions/
          page.tsx
        staff/
          page.tsx
    api/                           # Next.js Route Handlers (server-side only)
      auth/
        login/route.ts             # Staff login → set httpOnly cookie
        logout/route.ts
        refresh/route.ts
      reader/
        login/route.ts
        logout/route.ts
        refresh/route.ts
  lib/
    api/
      public.ts                    # Unauthenticated GET helpers
      reader.ts                    # Reader-authed request helpers
      staff.ts                     # Staff-authed request helpers
      types.ts                     # All shared TypeScript types
      errors.ts                    # ApiError handler
    auth/
      reader-session.ts            # Read/write reader httpOnly cookie
      staff-session.ts             # Read/write staff httpOnly cookie
    advertising/
      api.ts
      track-click.ts
      track-impression.ts
  components/
    site/
      Header.tsx
      Footer.tsx
      NavBar.tsx
      ArticleCard.tsx
      ArticleDetail.tsx
      BreakingBanner.tsx
      TopStoriesGrid.tsx
      CommentThread.tsx
      CommentForm.tsx
      NewsletterSignup.tsx
      SearchBox.tsx
      Pagination.tsx
      AdSlot.tsx
    reader/
      LoginForm.tsx
      RegisterForm.tsx
      BookmarkButton.tsx
    staff/
      Sidebar.tsx
      ArticleEditor.tsx
      MediaPicker.tsx
      StatusBadge.tsx
      RoleBadge.tsx
  middleware.ts                    # Protect /cms/* routes
```

---

## 5. API Client Layer

### `src/lib/api/errors.ts`

```ts
export type ApiError = {
  status: "error";
  code: string;
  message: string;
  errors?: Record<string, string>;
  retry_after_seconds?: number;
};

export class GraniteApiError extends Error {
  code: string;
  errors?: Record<string, string>;
  retryAfter?: number;

  constructor(payload: ApiError) {
    super(payload.message);
    this.code = payload.code;
    this.errors = payload.errors;
    this.retryAfter = payload.retry_after_seconds;
  }
}

export async function handleApiResponse<T>(res: Response): Promise<T> {
  if (res.ok) return res.json() as Promise<T>;
  const body = await res.json().catch(() => null);
  if (body?.status === "error") throw new GraniteApiError(body);
  throw new GraniteApiError({
    status: "error",
    code: String(res.status),
    message: res.statusText || "Unexpected error",
  });
}
```

### `src/lib/api/public.ts`

```ts
import { handleApiResponse } from "./errors";

const BASE = process.env.API_BASE_URL!;

export async function getPublic<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    next: { revalidate: 60 },
    ...init,
  });
  return handleApiResponse<T>(res);
}
```

### `src/lib/api/reader.ts`

```ts
import { handleApiResponse } from "./errors";

const BASE = process.env.API_BASE_URL!;

export async function getReader<T>(path: string, token: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  return handleApiResponse<T>(res);
}

export async function postReader<T>(
  path: string,
  token: string,
  body: unknown
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  return handleApiResponse<T>(res);
}

export async function patchReader<T>(
  path: string,
  token: string,
  body: unknown
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  return handleApiResponse<T>(res);
}
```

### `src/lib/api/staff.ts`

Same pattern as `reader.ts` but pointed at `/api/v1/auth/*` and `/api/v1/staff/*` endpoints.

---

## 6. TypeScript Types

### `src/lib/api/types.ts`

```ts
// --- Pagination ---

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

// --- Taxonomy ---

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

export type Section = {
  id: number;
  name: string;
  slug: string;
  description: string;
  is_primary: boolean;
};

// --- Articles ---

export type ArticleListItem = {
  id: number;
  title: string;
  slug: string;
  excerpt: string;
  status: "draft" | "review" | "published" | "archived";
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

// --- Author ---

export type AuthorProfile = {
  id: number;
  byline: string;
  slug: string;
  title: string;
  bio: string;
  avatar_url: string;
  beat: string;
  twitter_handle: string;
  linkedin_url: string;
  email_public: string;
  article_count: number;
};

// --- Staff User ---

export type StaffUser = {
  id: number;
  username: string;
  display_name: string;
  slug: string;
  role: "contributor" | "author" | "moderator" | "editor" | "senior_editor" | "admin";
  role_display: string;
  avatar_url: string;
  title: string;
  can_publish: boolean;
  can_edit_any_article: boolean;
  can_manage_staff: boolean;
  is_editorial_admin: boolean;
};

// --- Reader ---

export type ReaderProfile = {
  id: string;
  email: string;
  username: string;
  display_name: string;
  public_name: string;
  avatar_url: string;
  bio: string;
  is_email_verified: boolean;
  date_joined: string;
  last_login: string;
  bookmark_count: number;
};

// --- Comments ---

export type Comment = {
  id: number;
  author_name: string;
  body: string;
  created_at: string;
  is_reply: boolean;
  parent: number | null;
  replies: Comment[];
};

// --- Subscription ---

export type SubscriptionPlan = {
  id: number;
  name: string;
  slug: string;
  description: string;
  price_usd: string;
  billing_period: "monthly" | "annual";
  billing_period_label: string;
  features: string[];
  article_access: "free_only" | "premium" | "all";
  article_access_label: string;
};

// --- Advertising ---

export type AdZone = {
  slug: string;
  name: string;
  campaigns: AdCampaign[];
};

export type AdCampaign = {
  id: number;
  name: string;
  creative_url: string;
  creative_type: string;
  impression_tracking_url: string;
  click_tracking_url: string;
};
```

---

## 7. Auth Architecture

### Two completely separate auth systems

| | Staff | Reader |
|---|---|---|
| Login endpoint | `POST /api/v1/auth/token/` | `POST /api/v1/accounts/login/` |
| Token source | JWT pair | JWT pair |
| Cookie name | `granite_staff_session` | `granite_reader_session` |
| Stored in | `httpOnly` cookie (via Route Handler) | `httpOnly` cookie (via Route Handler) |
| Token expiry | Access: 60 min / Refresh: 7 days | Access: 60 min / Refresh: 7 days |

### Middleware (`src/middleware.ts`)

```ts
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (pathname.startsWith("/cms") && pathname !== "/cms/login") {
    const staffToken = request.cookies.get("granite_staff_session");
    if (!staffToken) {
      return NextResponse.redirect(new URL("/cms/login", request.url));
    }
  }

  if (pathname.startsWith("/account")) {
    const readerToken = request.cookies.get("granite_reader_session");
    if (!readerToken) {
      return NextResponse.redirect(new URL("/login", request.url));
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/cms/:path*", "/account/:path*"],
};
```

### Staff login Route Handler (`src/app/api/auth/login/route.ts`)

```ts
import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  const { username, password } = await req.json();

  const upstream = await fetch(`${process.env.API_BASE_URL}/api/v1/auth/token/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

  if (!upstream.ok) {
    const err = await upstream.json();
    return NextResponse.json(err, { status: upstream.status });
  }

  const data = await upstream.json();

  const res = NextResponse.json({ user: data.user });
  res.cookies.set("granite_staff_session", data.access, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60, // 1h, matches backend
  });
  res.cookies.set("granite_staff_refresh", data.refresh, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/api/auth",
    maxAge: 60 * 60 * 24 * 7, // 7 days
  });

  return res;
}
```

Repeat the same pattern for reader login, pointing at `/api/v1/accounts/login/` and using `granite_reader_session` / `granite_reader_refresh` cookies.

---

## 8. Public Site Pages

### 8.1 Homepage (`src/app/(site)/page.tsx`)

Server component — fetch in parallel:

```ts
import { getPublic } from "@/lib/api/public";
import type { ArticleListItem, TopStorySlot } from "@/lib/api/types";

export default async function HomePage() {
  const [breaking, topStories, featured, latest] = await Promise.all([
    getPublic<ArticleListItem[]>("/api/v1/articles/breaking/"),
    getPublic<TopStorySlot[]>("/api/v1/articles/top-stories/"),
    getPublic<ArticleListItem[]>("/api/v1/articles/featured/"),
    getPublic<{ results: ArticleListItem[] }>("/api/v1/articles/"),
  ]);

  return (
    <>
      {/* BreakingBanner, TopStoriesGrid, FeaturedRow, LatestFeed */}
    </>
  );
}

export const revalidate = 60;
```

### 8.2 Article Detail (`src/app/(site)/articles/[slug]/page.tsx`)

```ts
import { getPublic } from "@/lib/api/public";
import type { ArticleDetail, Comment } from "@/lib/api/types";
import { Metadata } from "next";

export async function generateMetadata({ params }: { params: { slug: string } }): Promise<Metadata> {
  const article = await getPublic<ArticleDetail>(`/api/v1/articles/${params.slug}/`);
  return {
    title: article.seo_title || article.title,
    description: article.seo_description || article.excerpt,
    openGraph: {
      title: article.og_title || article.title,
      description: article.og_description || article.excerpt,
      images: article.resolved_og_image ? [article.resolved_og_image] : [],
      type: "article",
      publishedTime: article.published_at ?? undefined,
    },
    twitter: { card: "summary_large_image" },
    alternates: { canonical: article.canonical_url },
  };
}

export default async function ArticlePage({ params }: { params: { slug: string } }) {
  const [article, commentsData] = await Promise.all([
    getPublic<ArticleDetail>(`/api/v1/articles/${params.slug}/`),
    getPublic<{ count: number; results: Comment[] }>(`/api/v1/articles/${params.slug}/comments/`),
  ]);

  return (
    <>
      {/* ArticleDetail server component */}
      {/* AnalyticsTracker client component — fires view POST */}
      {/* CommentThread + CommentForm client components */}
    </>
  );
}

export const revalidate = 120;
```

**Analytics tracking (client component):**

```tsx
"use client";
import { useEffect } from "react";

export function AnalyticsTracker({ slug }: { slug: string }) {
  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/api/v1/analytics/articles/${slug}/view/`, {
      method: "POST",
    });
  }, [slug]);
  return null;
}
```

### 8.3 Category Page (`src/app/(site)/categories/[slug]/page.tsx`)

```ts
const data = await getPublic<{
  category: Category;
  articles: ArticleListItem[];
}>(`/api/v1/categories/${params.slug}/`);
```

Note: not paginated — render full array.

### 8.4 Tag Page (`src/app/(site)/tags/[slug]/page.tsx`)

```ts
const data = await getPublic<{
  tag: Tag;
  articles: ArticleListItem[];
}>(`/api/v1/tags/${params.slug}/`);
```

### 8.5 Section Page (`src/app/(site)/sections/[slug]/page.tsx`)

```ts
const section = await getPublic(`/api/v1/sections/${params.slug}/`);
// section includes: hero_article, categories, latest 20 articles
// paginated articles via /api/v1/sections/${slug}/articles/?page=N
```

### 8.6 Author Pages

```ts
// /authors
const authors = await getPublic<AuthorProfile[]>("/api/v1/users/");

// /authors/[slug]
const data = await getPublic<{ user: AuthorProfile; articles: ArticleListItem[] }>(
  `/api/v1/users/${params.slug}/`
);
```

API path is `/api/v1/users/` — frontend route is `/authors/`.

### 8.7 Search (`src/app/(site)/search/page.tsx`)

```ts
// Server component — receives ?q= from searchParams
const query = searchParams.q ?? "";
const data = await getPublic<PaginatedResponse<SearchResult>>(
  `/api/v1/search/?q=${encodeURIComponent(query)}&page=${page}`
);
// SearchResult.headline contains <mark> tags — render safely or strip
```

Limits: min 2 chars, max 200 chars, page_size max 50.

---

## 9. Reader Account Area

### 9.1 Registration

POST to `/api/v1/accounts/register/`:

```json
{
  "email": "reader@example.com",
  "username": "reader1",
  "password": "StrongPass123!",
  "display_name": "Reader One"
}
```

- After registration, show "check your email" message.
- Login is blocked until email verification succeeds.

### 9.2 Email Verification

```
GET /api/v1/accounts/verify-email/?token=...
```

- Route Handler or server page reads the `?token` query param and forwards to backend.
- On success, redirect to `/login`.

### 9.3 Login

POST to your Route Handler `/api/reader/login`, which proxies to `/api/v1/accounts/login/`:

```json
{
  "email": "reader@example.com",
  "password": "StrongPass123!"
}
```

- Sets `granite_reader_session` httpOnly cookie.
- Redirect to `/account`.

### 9.4 Profile

```ts
const profile = await getReader<ReaderProfile>("/api/v1/accounts/me/", token);
// PATCH /api/v1/accounts/me/ — patchable: display_name, avatar_url, bio
```

### 9.5 Bookmarks

```ts
// List
GET /api/v1/accounts/bookmarks/

// Add
POST /api/v1/accounts/bookmarks/ → { "article_slug": "slug" }

// Remove
DELETE /api/v1/accounts/bookmarks/<article-slug>/

// Duplicate → HTTP 409
```

`BookmarkButton` is a client component. Use SWR with optimistic update.

### 9.6 Reading History

```ts
POST /api/v1/accounts/history/ → { "article_slug": "slug" }
GET  /api/v1/accounts/history/
DELETE /api/v1/accounts/history/   // clear all
```

Fire the POST in a client effect on article detail pages (reader-only, skip if not logged in).

---

## 10. Subscription & Paywall

### 10.1 Plan Listing (`/subscribe`)

```ts
const plans = await getPublic<SubscriptionPlan[]>("/api/v1/subscriptions/plans/");
```

Display: name, price, billing period, features list, CTA button.

### 10.2 Reader Subscription Status

```ts
GET /api/v1/subscriptions/my-subscription/
// 404 = no subscription
```

Use to gate premium content display.

### 10.3 Subscribe Flow

```ts
POST /api/v1/subscriptions/subscribe/
{
  "plan_slug": "premium",
  "payment_method": "ecocash",
  "phone_number": "+263771234567"
}
```

Payment methods: `ecocash`, `onemoney`, `bank_card`, `bank_transfer`.

**Free plan** → activates immediately.

**Paid plan** → client-side Paynow flow:
1. POST subscribe — get back `redirect_url` and `poll_url`.
2. Redirect reader to `redirect_url` (Paynow payment page).
3. Poll `GET /api/v1/subscriptions/paynow-poll/<payment-id>/` every 3–5 seconds.
4. When `paid: true`, update paywall state and reload subscription status.

### 10.4 Cancel

```ts
POST /api/v1/subscriptions/cancel/
{ "cancel_immediately": false }
```

### 10.5 Payment History

```ts
GET /api/v1/subscriptions/payments/
// Paginated. Fields: amount_usd, currency, payment_method_label, status_label, created_at
```

---

## 11. Staff CMS

### 11.1 Login (`/cms/login`)

POST to your Route Handler `/api/auth/login`:
- Proxies to `/api/v1/auth/token/`
- Sets `granite_staff_session` + `granite_staff_refresh` httpOnly cookies
- Returns `user` object → store in React context or Zustand

### 11.2 Middleware Protection

The middleware in `src/middleware.ts` redirects all `/cms/*` (except `/cms/login`) to `/cms/login` if `granite_staff_session` cookie is absent.

### 11.3 Article Management

```ts
// List (staff sees all statuses)
GET  /api/v1/articles/?status=draft&page=1

// Create
POST /api/v1/articles/

// Edit
GET  /api/v1/articles/<slug>/
PATCH /api/v1/articles/<slug>/

// Archive (soft delete)
DELETE /api/v1/articles/<slug>/
```

Writable fields: `title`, `excerpt`, `body`, `status`, `category`, `tags`, `is_breaking`, `top_story_rank`, `featured_rank`, `image_url`, `image_alt`, `image_caption`, `image_credit`, `og_title`, `og_description`, `og_image_url`, `canonical_url`.

Status flow: `draft → review → published → archived`.

**Important:** `DELETE` archives the article — it does not hard delete.

### 11.4 Media Library

```ts
// List
GET /api/v1/media/

// Upload (multipart)
POST /api/v1/media/   form fields: file, alt_text, caption, credit

// Delete
DELETE /api/v1/media/<id>/
```

Constraints: JPEG / PNG / WebP only, max 10 MB, min 800px width.

### 11.5 Comment Moderation

```ts
GET  /api/v1/moderation/comments/?status=pending
PATCH /api/v1/moderation/comments/<id>/
{ "action": "approve" }   // or "reject"
```

### 11.6 Staff Management

```ts
GET    /api/v1/staff/
POST   /api/v1/staff/
GET    /api/v1/staff/<id>/
PATCH  /api/v1/staff/<id>/
DELETE /api/v1/staff/<id>/
```

Roles (ascending): `contributor`, `author`, `moderator`, `editor`, `senior_editor`, `admin`.

Only `senior_editor` and `admin` can access staff management endpoints.

### 11.7 Newsletter Subscribers

```ts
GET /api/v1/newsletter/subscribers/?confirmed=all
// confirmed=true | false | all
```

### 11.8 Advertising Dashboard

```ts
GET    /api/v1/ads/campaigns/
POST   /api/v1/ads/campaigns/
GET    /api/v1/ads/campaigns/<id>/
PATCH  /api/v1/ads/campaigns/<id>/
GET    /api/v1/ads/advertisers/
POST   /api/v1/ads/advertisers/
GET    /api/v1/ads/report/<campaign-id>/
```

Editor role or above required.

### 11.9 Revenue Dashboard

```ts
GET /api/v1/subscriptions/all/
GET /api/v1/subscriptions/revenue/
```

---

## 12. Shared Components

| Component | Location | Notes |
|---|---|---|
| `<ArticleCard>` | `components/site/` | Used in lists, grids, featured rows |
| `<BreakingBanner>` | `components/site/` | Client — polls or ISR |
| `<TopStoriesGrid>` | `components/site/` | 6-slot grid, `rank` ordering |
| `<CommentThread>` | `components/site/` | Server-fetched, client form |
| `<CommentForm>` | `components/site/` | Client — POST with rate-limit awareness |
| `<NewsletterSignup>` | `components/site/` | Client form, source field |
| `<Pagination>` | `components/site/` | Reads `total_pages`, `current_page` |
| `<AdSlot>` | `components/site/` | Client — impression + click tracking |
| `<BookmarkButton>` | `components/reader/` | Client, SWR optimistic |
| `<ArticleEditor>` | `components/staff/` | Rich text, media picker, status picker |
| `<StatusBadge>` | `components/staff/` | Color-coded: draft/review/published/archived |

---

## 13. SEO & Meta

Every public page must implement `generateMetadata`:

```ts
export async function generateMetadata({ params }): Promise<Metadata> {
  const article = await getPublic<ArticleDetail>(`/api/v1/articles/${params.slug}/`);
  return {
    title: article.seo_title || article.title,
    description: article.seo_description || article.excerpt,
    openGraph: {
      title: article.og_title || article.title,
      description: article.og_description,
      images: [article.resolved_og_image],
      type: "article",
      publishedTime: article.published_at ?? undefined,
    },
    twitter: { card: "summary_large_image" },
    alternates: { canonical: article.canonical_url },
  };
}
```

**OG image minimum:** 1200×630px — enforce this when accepting uploads in the CMS.

**JSON-LD NewsArticle** — add to article detail page:

```tsx
<script
  type="application/ld+json"
  dangerouslySetInnerHTML={{
    __html: JSON.stringify({
      "@context": "https://schema.org",
      "@type": "NewsArticle",
      "headline": article.title,
      "image": [article.resolved_og_image],
      "datePublished": article.published_at,
      "dateModified": article.updated_at,
      "author": { "@type": "Person", "name": article.author_name },
    }),
  }}
/>
```

**WhatsApp preview** requires `og:image` rendered server-side — Next.js App Router does this automatically via `generateMetadata`.

---

## 14. Advertising Integration

### 14.1 Fetch zone data (server component)

```ts
const zone = await getPublic<AdZone>("/api/v1/ads/zones/homepage-leaderboard/");
// Zone results are cached 60s on the backend — short ISR on the frontend is fine
```

### 14.2 `<AdSlot>` client component

```tsx
"use client";
import { useEffect } from "react";

export function AdSlot({ campaign }: { campaign: AdCampaign }) {
  useEffect(() => {
    // Fire impression when visible (use IntersectionObserver in production)
    fetch(
      `${process.env.NEXT_PUBLIC_API_BASE_URL}${campaign.impression_tracking_url}`,
      { method: "POST" }
    );
  }, [campaign.impression_tracking_url]);

  async function handleClick() {
    const res = await fetch(
      `${process.env.NEXT_PUBLIC_API_BASE_URL}${campaign.click_tracking_url}`,
      { method: "POST" }
    );
    const data = await res.json();
    if (data.redirect_url) window.open(data.redirect_url, "_blank", "noopener");
  }

  return (
    <a onClick={handleClick} style={{ cursor: "pointer" }}>
      <img src={campaign.creative_url} alt={campaign.name} />
    </a>
  );
}
```

**Rules:**
- Tracking URLs in the zone response are relative paths — prepend `NEXT_PUBLIC_API_BASE_URL`.
- Never expose the raw `click_url` directly — always go through the tracking endpoint first.
- Staff impressions are not counted by the backend.

---

## 15. Push Notifications

```ts
// 1. Get VAPID public key
GET /api/v1/notifications/vapid-public-key/
// Returns 503 if push is not configured

// 2. Subscribe browser
const reg = await navigator.serviceWorker.ready;
const sub = await reg.pushManager.subscribe({
  userVisibleOnly: true,
  applicationServerKey: vapidKey,
});

// 3. Send to backend
POST /api/v1/notifications/subscribe/
{
  "endpoint": sub.endpoint,
  "p256dh": base64encode(sub.getKey("p256dh")),
  "auth": base64encode(sub.getKey("auth")),
  "user_agent": navigator.userAgent
}

// 4. Unsubscribe
POST /api/v1/notifications/unsubscribe/
```

Put the permission flow behind a user action (button click) — browsers block auto-prompts.

---

## 16. Build Order

### Phase 1 — Foundation
- [ ] Project scaffold + env vars
- [ ] API client layer (`public.ts`, `reader.ts`, `staff.ts`, error handler)
- [ ] TypeScript types (`types.ts`)
- [ ] Site layout: `<Header>`, `<NavBar>` (sections), `<Footer>`

### Phase 2 — Public Site
- [ ] Homepage: breaking banner, top stories grid, featured row, latest feed
- [ ] Article detail: server fetch, OG meta, JSON-LD, analytics tracker
- [ ] Category pages
- [ ] Tag pages
- [ ] Section pages
- [ ] Author list + author detail
- [ ] Search page with highlight rendering
- [ ] Newsletter signup form

### Phase 3 — Reader Auth & Account
- [ ] Reader register + email verification flow
- [ ] Reader login / logout Route Handlers + cookies
- [ ] Account profile page + edit form
- [ ] Bookmarks page + `<BookmarkButton>`
- [ ] Reading history page

### Phase 4 — Subscriptions
- [ ] Plan listing page (`/subscribe`)
- [ ] Subscribe form (payment method selector)
- [ ] Paynow poll loop
- [ ] Reader subscription status page
- [ ] Payment history

### Phase 5 — Advertising
- [ ] `<AdSlot>` component with impression tracking
- [ ] Click tracking + redirect
- [ ] Zone slots on homepage, article detail

### Phase 6 — Staff CMS
- [ ] CMS login + cookie session + middleware guard
- [ ] CMS dashboard (headline stats)
- [ ] Article list (filter by status)
- [ ] Article create/edit form with `<ArticleEditor>`
- [ ] Media library + upload
- [ ] Comment moderation queue
- [ ] Newsletter subscriber list
- [ ] Advertising dashboard (campaigns + advertisers + reports)
- [ ] Subscription revenue view
- [ ] Staff management

### Phase 7 — Polish
- [ ] Push notification subscription flow
- [ ] ISR tuning (`revalidate` values per page type)
- [ ] Error boundaries + fallback UIs for API failures
- [ ] Rate-limit UI feedback (`retry_after_seconds`)
- [ ] Accessibility audit
- [ ] Lighthouse / Core Web Vitals pass

---

## 17. Deployment Checklist

- [ ] All env vars set in Vercel project settings
- [ ] `API_BASE_URL` points to production Django URL (no trailing slash)
- [ ] `NEXT_PUBLIC_SITE_URL` matches production domain
- [ ] `CORS_ALLOWED_ORIGINS` on backend includes production frontend URL
- [ ] Cookie `secure: true` in production Route Handlers
- [ ] OG images confirmed ≥1200×630px
- [ ] `generateMetadata` on every public page
- [ ] JSON-LD on article detail pages
- [ ] `robots.txt` not blocking crawlers
- [ ] Sitemap links to `/sitemap.xml` and `/feed/` working from backend
- [ ] WhatsApp share preview tested (`og:image` resolves publicly)
- [ ] Paynow polling tested end-to-end in staging
- [ ] Ad impression/click tracking verified (not double-counting)
- [ ] Staff login smoke test: correct role shown, CMS accessible
- [ ] Reader login smoke test: bookmarks and history working

---

## Source of Truth Order

When API behavior is unclear:

1. `http://127.0.0.1:8000/api/docs/` — Swagger (live)
2. `http://127.0.0.1:8000/api/schema/` — OpenAPI JSON
3. `postman/TheGraniteAPI.postman_collection.json`
4. `docs/NEXTJS_FRONTEND_GUIDE.md` — endpoint reference
5. `docs/ADVERTISING_FRONTEND_GUIDE.md` — ad-specific contract
6. Backend serializer + view files
