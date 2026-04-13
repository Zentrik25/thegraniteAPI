# RSS Feed Fix — Action Plan
**Problem:** New articles not appearing in Inoreader and other RSS feed readers.
**Root cause:** Three compounding bugs in the publish → cache invalidation pipeline.

---

## Fix 1 — `cloudflare_purge.py` (5 minutes) ← DO THIS FIRST

**File:** `core/cloudflare_purge.py`
**Lines:** 94–103

Change the `urls` list in `purge_article_cache()`:

```python
# BEFORE
urls = [
    f"{site_url}/articles/{slug}/",
    f"{site_url}/api/v1/articles/{slug}/",
    f"{site_url}/api/v1/articles/",
    f"{site_url}/api/v1/articles/top-stories/",
    f"{site_url}/api/v1/articles/breaking/",
    f"{site_url}/sitemap.xml",
    f"{site_url}/news-sitemap.xml",
    f"{site_url}/rss/latest/",          # ← WRONG URL (404)
]

# AFTER
urls = [
    f"{site_url}/articles/{slug}/",
    f"{site_url}/api/v1/articles/{slug}/",
    f"{site_url}/api/v1/articles/",
    f"{site_url}/api/v1/articles/top-stories/",
    f"{site_url}/api/v1/articles/breaking/",
    f"{site_url}/sitemap.xml",
    f"{site_url}/news-sitemap.xml",
    f"{site_url}/feed.xml",             # ← CORRECT (the actual RSS feed)
    f"{site_url}/feed",                 # ← also purge the redirect URL
]
```

**Why this fixes it:** Django's `post_save` signal fires `purge_article_cache()` on every publish. Once this URL is corrected, Cloudflare will immediately serve the fresh feed on the next reader poll.

---

## Fix 2 — `next.config.ts` redirects (10 minutes)

**File:** `thegraniteFRONTEND/next.config.ts`

Add redirect rules so `/feed`, `/rss`, and `/rss.xml` all route to `/feed.xml`:

```typescript
async redirects() {
  return [
    { source: '/feed',    destination: '/feed.xml', permanent: true },
    { source: '/rss',     destination: '/feed.xml', permanent: true },
    { source: '/rss.xml', destination: '/feed.xml', permanent: true },
  ];
},
```

**Why this fixes it:** Many feed readers (including Inoreader's auto-subscribe) try `/feed` first (WordPress convention). Currently this returns 404. With the redirect, any user subscribed to `/feed` will transparently get `/feed.xml`.

> **Note:** After deploying, ask affected users to re-subscribe or manually update their subscription URL to `https://www.thegranite.co.zw/feed.xml`. Existing 404 subscriptions won't auto-heal until the user's reader retries (which some do on 3xx, not on 404).

---

## Fix 3 — `revalidate/route.ts` (5 minutes)

**File:** `thegraniteFRONTEND/src/app/api/revalidate/route.ts`
**After line 61** (`purge("/")`):

```typescript
purge("/feed.xml");
purge("/news-sitemap.xml");
```

**Why this fixes it:** Next.js caches the `fetch()` result in `feed.xml/route.ts` for 900 seconds (Data Cache). Calling `revalidatePath("/feed.xml")` clears that cache entry so the next request fetches fresh data from the Django API immediately.

---

## Fix 4 — Call Next.js revalidate from Django on publish (1 hour)

Currently Django only calls Cloudflare's purge API. The Next.js Data Cache (internal to Vercel) is a separate cache layer that Cloudflare cannot reach. Django must call `/api/revalidate` directly.

**File:** `core/nextjs_revalidate.py` (new file):

```python
"""
nextjs_revalidate.py — Trigger Next.js on-demand ISR revalidation.

Requires in .env / Django settings:
    NEXTJS_URL              — https://www.thegranite.co.zw
    NEXTJS_REVALIDATE_SECRET — matches REVALIDATE_SECRET in the Next.js env
"""

import logging
import requests
from django.conf import settings

logger = logging.getLogger("core.nextjs_revalidate")


def revalidate_article(
    slug: str,
    section_slug: str | None = None,
    category_slug: str | None = None,
) -> bool:
    nextjs_url = getattr(settings, "NEXTJS_URL", "").rstrip("/")
    secret = getattr(settings, "NEXTJS_REVALIDATE_SECRET", "")
    if not nextjs_url:
        logger.debug("NEXTJS_URL not set — skipping revalidation.")
        return False

    payload: dict = {
        "secret": secret,
        "article_slug": slug,
        "paths": ["/feed.xml", "/news-sitemap.xml", "/sitemap.xml"],
    }
    if section_slug:
        payload["section_slug"] = section_slug
    if category_slug:
        payload["category_slug"] = category_slug

    try:
        response = requests.post(
            f"{nextjs_url}/api/revalidate",
            json=payload,
            timeout=5,
        )
        if response.status_code == 200:
            logger.info("Next.js revalidated for slug=%s", slug)
            return True
        logger.warning(
            "Next.js revalidate HTTP %d for slug=%s: %s",
            response.status_code,
            slug,
            response.text[:200],
        )
        return False
    except Exception as exc:
        logger.error("Next.js revalidate error for slug=%s: %s", slug, exc)
        return False
```

**File:** `articles/signals.py` — add signal:

```python
@receiver(post_save, sender="articles.Article")
def revalidate_nextjs_on_publish(sender, instance, **kwargs) -> None:
    if instance.status != "published":
        return
    try:
        from core.nextjs_revalidate import revalidate_article
        section_slug = getattr(instance.section, "slug", None)
        category_slug = getattr(instance.category, "slug", None)
        revalidate_article(instance.slug, section_slug, category_slug)
    except Exception as exc:
        logger.warning(
            "Next.js revalidate failed for article pk=%s slug=%s: %s",
            instance.pk,
            instance.slug,
            exc,
        )
```

**Environment variables to add:**
```
# Django .env
NEXTJS_URL=https://www.thegranite.co.zw
NEXTJS_REVALIDATE_SECRET=<same value as REVALIDATE_SECRET in Next.js>
```

---

## Fix 5 — Increase feed `page_size` to 50 (5 minutes)

**File:** `thegraniteFRONTEND/src/app/feed.xml/route.ts`, line 50:

```typescript
// BEFORE
`${API_BASE_URL}/api/v1/articles/?page_size=20&ordering=-published_at`,

// AFTER
`${API_BASE_URL}/api/v1/articles/?page_size=50&ordering=-published_at`,
```

Gives feed readers a larger history window, reducing the risk of missing articles during polling gaps.

---

## Fix 6 — Add `width`/`height` to `media:content` (15 minutes)

**File:** `thegraniteFRONTEND/src/app/feed.xml/route.ts`, line 93:

```typescript
// BEFORE
lines.push(`      <media:content url="${esc(a.image_url)}" medium="image" />`);

// AFTER
lines.push(`      <media:content url="${esc(a.image_url)}" medium="image" width="1200" height="675" />`);
```

---

## Deploy Order

1. **Fix 1** — `cloudflare_purge.py` → deploy to production immediately (Python-only, no DB migration)
2. **Fix 2** — `next.config.ts` redirects → deploy Next.js
3. **Fix 3** — `revalidate/route.ts` → deploy Next.js (same deploy as Fix 2)
4. **Fix 5 + 6** — `feed.xml/route.ts` → deploy Next.js (same deploy)
5. **Fix 4** — New `nextjs_revalidate.py` + signal → deploy Django after setting env vars

---

## Testing the Fix

After deploying Fix 1:

```bash
# 1. Publish a test article in the CMS

# 2. Immediately fetch the feed — the new article should appear
curl -I https://www.thegranite.co.zw/feed.xml | grep -i "cf-cache-status\|age\|last-modified"

# 3. Confirm CF-Cache-Status is MISS (Cloudflare fetched fresh) not HIT
# Expected: CF-Cache-Status: MISS on first request after publish

# 4. Re-fetch — should show CF-Cache-Status: HIT (now cached fresh version)
curl https://www.thegranite.co.zw/feed.xml | grep -A3 "<item>"
```

After deploying Fix 2 (redirects):
```bash
curl -I https://www.thegranite.co.zw/feed
# Expected: HTTP/2 301 Location: /feed.xml
```

---

## Timeline

| Fix | Effort | Impact |
|-----|--------|--------|
| Fix 1 (cloudflare_purge.py) | 5 min | Eliminates CDN caching delay after publish |
| Fix 2 (redirects) | 10 min | Fixes all subscriptions to `/feed` URL |
| Fix 3 (revalidate route) | 5 min | Clears Next.js Data Cache on publish |
| Fix 4 (Django webhook) | 1 hour | End-to-end immediate freshness |
| Fix 5 (page_size 50) | 5 min | More history in feed |
| Fix 6 (media dimensions) | 5 min | Better image previews in readers |

**Minimum viable fix (ship today):** Fix 1 + Fix 2 + Fix 3. This will resolve the issue for most readers within the next publish cycle.
