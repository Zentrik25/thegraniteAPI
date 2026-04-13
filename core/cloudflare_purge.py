"""
cloudflare_purge.py — Cloudflare cache purge helpers for The Granite Post.

Purges cached pages from Cloudflare's edge when content changes so readers
always see fresh articles rather than stale CDN-cached versions.

Requires in .env:
    CLOUDFLARE_ZONE_ID   — found in Cloudflare dashboard → right sidebar
    CLOUDFLARE_API_TOKEN — Cache Purge token scoped to your zone
    SITE_URL             — https://thegranite.co.zw

If credentials are absent the functions return False silently so they are
safe to call in development and test environments.
"""

import logging

from django.conf import settings

logger = logging.getLogger("core.cloudflare_purge")


def _credentials() -> tuple[str, str, str]:
    """Return (zone_id, api_token, site_url) from settings."""
    zone_id   = getattr(settings, "CLOUDFLARE_ZONE_ID",   "")
    api_token = getattr(settings, "CLOUDFLARE_API_TOKEN", "")
    site_url  = getattr(settings, "SITE_URL", "https://thegranite.co.zw").rstrip("/")
    return zone_id, api_token, site_url


def _purge(urls: list[str] | None = None, purge_everything: bool = False) -> bool:
    """
    Low-level Cloudflare cache purge call.

    Args:
        urls:             List of absolute URLs to purge. Used when purge_everything=False.
        purge_everything: If True, purge the entire zone cache.

    Returns:
        True if the API responded with HTTP 200, False otherwise.
    """
    import requests as http_lib

    zone_id, api_token, _ = _credentials()
    if not zone_id or not api_token:
        logger.debug("Cloudflare credentials not configured — skipping cache purge.")
        return False

    payload = {"purge_everything": True} if purge_everything else {"files": urls or []}

    try:
        response = http_lib.post(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache",
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type":  "application/json",
            },
            json=payload,
            timeout=10,
        )
        if response.status_code == 200:
            return True
        logger.warning(
            "Cloudflare purge failed (HTTP %d): %s",
            response.status_code,
            response.text[:200],
        )
        return False

    except Exception as exc:  # noqa: BLE001
        logger.error("Cloudflare purge request error: %s", exc)
        return False


def purge_article_cache(slug: str) -> bool:
    """
    Purge all Cloudflare-cached URLs associated with a single article.

    Purges:
      - The article detail page
      - The article API endpoint
      - The article list API endpoint (homepage feed)
      - Top stories and breaking news feeds
      - Sitemaps (news-sitemap may include this article)

    Args:
        slug: The article slug.

    Returns:
        True if purge succeeded, False on error or missing credentials.
    """
    _, _, site_url = _credentials()

    urls = [
        f"{site_url}/articles/{slug}/",
        f"{site_url}/api/v1/articles/{slug}/",
        f"{site_url}/api/v1/articles/",
        f"{site_url}/api/v1/articles/top-stories/",
        f"{site_url}/api/v1/articles/breaking/",
        f"{site_url}/sitemap.xml",
        f"{site_url}/news-sitemap.xml",
        f"{site_url}/feed.xml",
        f"{site_url}/feed",
    ]

    success = _purge(urls=urls)
    if success:
        logger.info("Cloudflare cache purged for article slug=%s (%d URLs)", slug, len(urls))
    return success


def purge_urls(urls: list[str]) -> bool:
    """
    Purge an arbitrary list of absolute URLs from Cloudflare's cache.

    Args:
        urls: List of absolute URLs (e.g. ["https://thegranite.co.zw/some/path/"]).

    Returns:
        True if purge succeeded, False otherwise.
    """
    success = _purge(urls=urls)
    if success:
        logger.info("Cloudflare cache purged: %d URL(s).", len(urls))
    return success


def purge_all() -> bool:
    """
    Purge the entire Cloudflare zone cache.

    Use sparingly — only for major site-wide changes such as a redesign
    or a bulk article migration. Affects all cached content for the zone.

    Returns:
        True if purge succeeded, False otherwise.
    """
    success = _purge(purge_everything=True)
    if success:
        logger.info("Cloudflare entire zone cache purged.")
    return success
